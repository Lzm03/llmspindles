from __future__ import annotations

import json
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from threading import Lock, Thread
from time import monotonic
from pathlib import Path
from urllib.parse import urlencode

from .annotations import upsert_annotation
from .eeg import detect_spindle_candidates, load_recording_metadata, render_segment_png
from .llm import analyze_epoch_png
from .models import AnalysisJob, AnnotationInput, BatchAnalysisRequest, CandidateSegment, GptPromptConfig, ReviewedEpoch
from .settings import JOB_FILE, LLM_REVIEW_WORKERS

MAX_BATCH_SEGMENTS = 500
BOUNDARY_CONTEXT_SEC = 5.0
_lock = Lock()
_running: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list[AnalysisJob]:
    raw = json.loads(JOB_FILE.read_text(encoding="utf-8"))
    return [AnalysisJob.model_validate(item) for item in raw]


def _save(items: list[AnalysisJob]) -> None:
    JOB_FILE.write_text(json.dumps([item.model_dump() for item in items], indent=2), encoding="utf-8")


def _update(job_id: str, **changes) -> AnalysisJob:
    with _lock:
        items = _load()
        for index, job in enumerate(items):
            if job.id == job_id:
                updated = job.model_copy(update={**changes, "updated_at": _now()})
                items[index] = updated
                _save(items)
                return updated
    raise KeyError("Analysis job not found.")


def create_job(payload: BatchAnalysisRequest) -> AnalysisJob:
    meta, _ = load_recording_metadata(payload.file_id)
    end_sec = min(payload.end_sec, meta.duration_sec)
    if end_sec <= payload.start_sec:
        raise ValueError("Batch analysis range is empty.")
    detection_started = monotonic()
    screening_candidates = detect_spindle_candidates(
        payload.file_id,
        payload.start_sec,
        end_sec,
        payload.channels,
        payload.segment_duration_sec,
    )
    candidate_detection_elapsed_sec = round(monotonic() - detection_started, 1)
    candidates_by_epoch: dict[tuple[float, float], CandidateSegment] = {}
    for candidate in screening_candidates:
        key = (candidate.start_sec, candidate.end_sec)
        if key not in candidates_by_epoch or candidate.score > candidates_by_epoch[key].score:
            candidates_by_epoch[key] = candidate
    candidates = sorted(candidates_by_epoch.values(), key=lambda item: item.start_sec)
    total = len(candidates)
    if total < 1:
        raise ValueError("No spindle-like candidates were found in the selected range.")
    if total > MAX_BATCH_SEGMENTS:
        raise ValueError(f"Batch analysis is limited to {MAX_BATCH_SEGMENTS} candidate segments per job.")
    now = _now()
    job = AnalysisJob(
        id=uuid.uuid4().hex,
        file_id=payload.file_id,
        status="queued",
        start_sec=payload.start_sec,
        end_sec=end_sec,
        segment_duration_sec=payload.segment_duration_sec,
        channels=payload.channels,
        filter_type=payload.filter_type,
        total_segments=total,
        elapsed_sec=candidate_detection_elapsed_sec,
        candidate_detection_elapsed_sec=candidate_detection_elapsed_sec,
        candidate_count=len(screening_candidates),
        candidate_segments=candidates,
        screening_candidates=screening_candidates,
        prompt_config=payload.prompt_config or GptPromptConfig(),
        created_at=now,
        updated_at=now,
    )
    with _lock:
        items = _load()
        items.append(job)
        _save(items)
    _start(job.id)
    return job


def get_job(job_id: str) -> AnalysisJob:
    for job in _load():
        if job.id == job_id:
            return job
    raise KeyError("Analysis job not found.")


def list_jobs(file_id: str | None = None) -> list[AnalysisJob]:
    jobs = _load()
    if file_id:
        jobs = [job for job in jobs if job.file_id == file_id]
    return sorted(jobs, key=lambda item: item.created_at, reverse=True)


def cancel_job(job_id: str) -> AnalysisJob:
    job = get_job(job_id)
    if job.status in ("completed", "failed", "cancelled"):
        return job
    return _update(job_id, status="cancelled", estimated_remaining_sec=0)


def delete_jobs_for_file(file_id: str) -> int:
    with _lock:
        items = _load()
        deleted = len([item for item in items if item.file_id == file_id])
        for item in items:
            if item.file_id == file_id and item.status in ("queued", "running"):
                item.status = "cancelled"
        _save([item for item in items if item.file_id != file_id])
        return deleted


def resume_incomplete_jobs() -> None:
    for job in _load():
        if job.status in ("queued", "running"):
            _update(job.id, status="queued")
            _start(job.id)


def _start(job_id: str) -> None:
    with _lock:
        if job_id in _running:
            return
        _running.add(job_id)
    Thread(target=_run, args=(job_id,), daemon=True).start()


def _review_candidate(job: AnalysisJob, candidate: CandidateSegment) -> tuple[ReviewedEpoch, int]:
    # Keep the narrow sigma band inside the numeric candidate detector only.
    # Visual confirmation uses broad-band context to avoid amplifying narrow-band artifacts.
    # Show extra signal around the fixed target epoch so a spindle crossing a
    # 30-second boundary is not visually truncated.
    meta, _ = load_recording_metadata(job.file_id)
    review_start_sec = max(0.0, candidate.start_sec - BOUNDARY_CONTEXT_SEC)
    review_end_sec = min(meta.duration_sec, candidate.end_sec + BOUNDARY_CONTEXT_SEC)
    hints = [item for item in job.screening_candidates if candidate.start_sec <= item.peak_time_sec < candidate.end_sec]
    png = render_segment_png(
        job.file_id, review_start_sec, review_end_sec, job.channels, "broad",
        target_start_sec=candidate.start_sec, target_end_sec=candidate.end_sec,
    )
    selected = job.channels or list(range(min(meta.channel_count, 12)))
    channel_labels = [meta.channel_labels[index] if index < len(meta.channel_labels) else f"Ch {index + 1}" for index in selected]
    subject_id = Path(meta.filename).stem or job.file_id
    epoch_index = int(candidate.start_sec // 30)
    result = analyze_epoch_png(
        png=png, config=job.prompt_config, subject_id=subject_id, epoch_index=epoch_index,
        epoch_start_sec=candidate.start_sec, epoch_end_sec=candidate.end_sec,
        channels=channel_labels, yasa_candidates=hints,
        context_before_sec=candidate.start_sec - review_start_sec,
        context_after_sec=review_end_sec - candidate.end_sec,
    )
    created = 0
    for event in result.definite_spindle_events:
        upsert_annotation(
            AnnotationInput(
                file_id=job.file_id,
                source="llm",
                status="accepted",
                start_time_sec=event.start_sec,
                end_time_sec=event.end_sec,
                channels=event.channels,
                confidence=0.9,
                filter_type_used="broad",
            )
        )
        created += 1
    query = urlencode({"channels": ",".join(str(item) for item in job.channels)})
    reviewed = ReviewedEpoch(
        subject_id=subject_id, epoch_index=epoch_index, start_sec=candidate.start_sec,
        end_sec=candidate.end_sec,
        image_path=f"/api/review-epoch-image/{job.file_id}/{epoch_index}?{query}",
        boundary_context_before_sec=candidate.start_sec - review_start_sec,
        boundary_context_after_sec=review_end_sec - candidate.end_sec,
        yasa_candidates=hints, gpt_result=result,
        accepted_spindle_count=len(result.definite_spindle_events),
        label="N2_like" if result.definite_spindle_events else "not_N2_like",
    )
    return reviewed, created


def _derive_review_onset(reviews: list[ReviewedEpoch]) -> tuple[int | None, float | None]:
    ordered = sorted(reviews, key=lambda item: item.epoch_index)
    for current, following in zip(ordered, ordered[1:], strict=False):
        if current.label == "N2_like" and following.label == "N2_like" and following.epoch_index == current.epoch_index + 1:
            return current.epoch_index, current.start_sec
    return None, None


def _run(job_id: str) -> None:
    try:
        job = _update(job_id, status="running", error=None)
        started = monotonic() - job.candidate_detection_elapsed_sec
        initial_completed = job.completed_segments
        candidates = job.candidate_segments[initial_completed:]
        if not candidates:
            _update(
                job_id,
                status="completed",
                progress_percent=100,
                estimated_remaining_sec=0,
                current_segment_start_sec=None,
                completed_at=_now(),
            )
            return

        workers = min(LLM_REVIEW_WORKERS, len(candidates))
        completed = initial_completed
        successful = job.successful_segments
        failed = job.failed_segments
        annotations_created = job.annotations_created
        last_error = None

        with ThreadPoolExecutor(max_workers=workers) as executor:
            queued = iter(candidates)
            in_flight: dict[Future[tuple[ReviewedEpoch, int]], CandidateSegment] = {}

            def submit_next() -> bool:
                current = get_job(job_id)
                if current.status == "cancelled":
                    return False
                try:
                    candidate = next(queued)
                except StopIteration:
                    return False
                in_flight[executor.submit(_review_candidate, current, candidate)] = candidate
                _update(job_id, current_segment_start_sec=candidate.start_sec)
                return True

            while len(in_flight) < workers and submit_next():
                pass

            while in_flight:
                current = get_job(job_id)
                if current.status == "cancelled":
                    for future in in_flight:
                        future.cancel()
                    return
                done, _ = wait(in_flight.keys(), return_when=FIRST_COMPLETED)
                for future in done:
                    candidate = in_flight.pop(future)
                    current_job = get_job(job_id)
                    current_reviews = list(current_job.reviewed_epochs)
                    onset_epoch = current_job.sleep_onset_epoch
                    onset_time = current_job.sleep_onset_time_sec
                    try:
                        reviewed, created = future.result()
                        annotations_created += created
                        successful += 1
                        current_reviews = [item for item in current_reviews if item.epoch_index != reviewed.epoch_index]
                        current_reviews.append(reviewed)
                        current_reviews.sort(key=lambda item: item.epoch_index)
                        onset_epoch, onset_time = _derive_review_onset(current_reviews)
                    except Exception as exc:
                        failed += 1
                        last_error = str(exc)
                    completed += 1
                    elapsed = monotonic() - started
                    average = elapsed / max(1, completed - initial_completed)
                    remaining = average * (job.total_segments - completed)
                    changes = {
                        "completed_segments": completed,
                        "successful_segments": successful,
                        "failed_segments": failed,
                        "annotations_created": annotations_created,
                        "progress_percent": round(completed / job.total_segments * 100, 2),
                        "elapsed_sec": round(elapsed, 1),
                        "estimated_remaining_sec": round(max(0, remaining), 1),
                        "current_segment_start_sec": candidate.start_sec,
                        "reviewed_epochs": current_reviews,
                        "sleep_onset_epoch": onset_epoch,
                        "sleep_onset_time_sec": onset_time,
                    }
                    if last_error:
                        changes["error"] = last_error
                    _update(job_id, **changes)
                    submit_next()
        _update(
            job_id,
            status="completed",
            progress_percent=100,
            estimated_remaining_sec=0,
            current_segment_start_sec=None,
            completed_at=_now(),
        )
    except Exception as exc:
        _update(job_id, status="failed", error=str(exc), estimated_remaining_sec=None)
    finally:
        with _lock:
            _running.discard(job_id)
