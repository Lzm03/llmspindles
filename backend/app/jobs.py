from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from threading import Lock, Thread
from time import monotonic

from .annotations import upsert_annotation
from .eeg import load_recording_metadata, render_segment_png
from .llm import analyze_png
from .models import AnalysisJob, AnnotationInput, BatchAnalysisRequest
from .settings import JOB_FILE

MAX_BATCH_SEGMENTS = 500
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
    total = math.ceil((end_sec - payload.start_sec) / payload.segment_duration_sec)
    if total > MAX_BATCH_SEGMENTS:
        raise ValueError(f"Batch analysis is limited to {MAX_BATCH_SEGMENTS} segments per job.")
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


def _run(job_id: str) -> None:
    started = monotonic()
    try:
        job = _update(job_id, status="running", error=None)
        initial_completed = job.completed_segments
        for index in range(initial_completed, job.total_segments):
            job = get_job(job_id)
            if job.status == "cancelled":
                return
            segment_start = job.start_sec + index * job.segment_duration_sec
            segment_end = min(segment_start + job.segment_duration_sec, job.end_sec)
            _update(job_id, current_segment_start_sec=segment_start)
            try:
                png = render_segment_png(job.file_id, segment_start, segment_end, job.channels, job.filter_type)
                result = analyze_png(png)
                created = 0
                for event in result.definite_spindle_events:
                    upsert_annotation(
                        AnnotationInput(
                            file_id=job.file_id,
                            source="llm",
                            status="proposed",
                            start_time_sec=event.start_time_sec,
                            end_time_sec=event.end_time_sec,
                            channels=event.channels,
                            confidence=event.confidence,
                            filter_type_used=job.filter_type,
                        )
                    )
                    created += 1
                successful = job.successful_segments + 1
                failed = job.failed_segments
            except Exception as exc:
                created = 0
                successful = job.successful_segments
                failed = job.failed_segments + 1
                error = str(exc)
            completed = index + 1
            elapsed = monotonic() - started
            average = elapsed / max(1, completed - initial_completed)
            remaining = average * (job.total_segments - completed)
            changes = {
                "completed_segments": completed,
                "successful_segments": successful,
                "failed_segments": failed,
                "annotations_created": job.annotations_created + created,
                "progress_percent": round(completed / job.total_segments * 100, 2),
                "elapsed_sec": round(elapsed, 1),
                "estimated_remaining_sec": round(remaining, 1),
            }
            if failed > job.failed_segments:
                changes["error"] = error
            _update(job_id, **changes)
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
