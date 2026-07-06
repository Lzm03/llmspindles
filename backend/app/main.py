from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response

from .annotations import delete_annotation, delete_annotations_for_file, list_annotations, upsert_annotation
from .eeg import _file_path, get_window, load_recording_metadata, png_to_base64, render_segment_png, save_upload
from .llm import EPOCH_REVIEW_SCHEMA, analyze_n2_epoch_pair, analyze_png
from .jobs import MAX_BATCH_SEGMENTS, cancel_job, create_job, delete_jobs_for_file, get_job, list_jobs, resume_incomplete_jobs
from .models import AnalysisJob, Annotation, AnnotationInput, BatchAnalysisRequest, FilterType, GptPromptConfig, RenderResponse, SegmentRequest, SpindleSleepOnsetReport, UploadResponse, WindowResponse
from .models import AutoN2PairRequest, AutoN2PairResult, SleepEpoch, SleepEpochInput, SleepOnsetResult
from .sleep_epochs import backfill_spindle_negatives, delete_sleep_epoch, delete_sleep_epochs_for_file, derive_sleep_onset, find_spindle_onset_proxy, list_sleep_epochs, upsert_sleep_epoch
from .sleep_onset import build_spindle_sleep_onset_report
from .settings import MAX_RENDER_SECONDS, UPLOAD_DIR

app = FastAPI(title="EEG Stable Sleep-Onset Annotation")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def resume_jobs() -> None:
    resume_incomplete_jobs()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...), sampling_rate: float | None = Form(default=None)) -> UploadResponse:
    if not file.filename or not file.filename.lower().endswith((".mat", ".edf")):
        raise HTTPException(status_code=400, detail="Only .mat and .edf files are supported.")
    try:
        return save_upload(await file.read(), file.filename, sampling_rate)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/files/{file_id}", response_model=UploadResponse)
def file_metadata(file_id: str) -> UploadResponse:
    try:
        meta, _ = load_recording_metadata(file_id)
        return meta
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/files/{file_id}")
def delete_file(file_id: str) -> dict:
    try:
        recording_path = _file_path(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown file_id.")
    metadata_path = UPLOAD_DIR / f"{file_id}.json"
    deleted_annotations = delete_annotations_for_file(file_id)
    deleted_jobs = delete_jobs_for_file(file_id)
    deleted_sleep_epochs = delete_sleep_epochs_for_file(file_id)
    recording_path.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)
    return {"deleted": True, "annotations_deleted": deleted_annotations, "jobs_deleted": deleted_jobs, "sleep_epochs_deleted": deleted_sleep_epochs}


@app.get("/api/sleep-epochs", response_model=list[SleepEpoch])
def sleep_epochs(file_id: str) -> list[SleepEpoch]:
    return list_sleep_epochs(file_id)


@app.post("/api/sleep-epochs", response_model=SleepEpoch)
def save_sleep_epoch(payload: SleepEpochInput) -> SleepEpoch:
    try:
        saved = upsert_sleep_epoch(payload)
        proxy_epoch = find_spindle_onset_proxy(list_sleep_epochs(payload.file_id))
        if proxy_epoch is not None:
            backfill_spindle_negatives(payload.file_id, proxy_epoch.epoch_index)
        return saved
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/sleep-epochs/{file_id}/{epoch_index}")
def remove_sleep_epoch(file_id: str, epoch_index: int) -> dict[str, bool]:
    try:
        delete_sleep_epoch(file_id, epoch_index)
        return {"deleted": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/sleep-onset/{file_id}", response_model=SleepOnsetResult)
def sleep_onset(file_id: str) -> SleepOnsetResult:
    try:
        load_recording_metadata(file_id)
        return derive_sleep_onset(file_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/auto-score-n2-pair", response_model=AutoN2PairResult)
def auto_score_n2_pair(payload: AutoN2PairRequest) -> AutoN2PairResult:
    try:
        meta, _ = load_recording_metadata(payload.file_id)
        first_start = payload.first_epoch_index * 30.0
        if first_start + 60.0 > meta.duration_sec:
            raise ValueError("Two complete 30-second epochs are required from the selected start.")
        first_broad_png = render_segment_png(payload.file_id, first_start, first_start + 30.0, payload.channels, "broad")
        second_broad_png = render_segment_png(payload.file_id, first_start + 30.0, first_start + 60.0, payload.channels, "broad")
        assessments = analyze_n2_epoch_pair(
            first_broad_png,
            second_broad_png,
            first_start,
        )
        existing = {item.epoch_index: item for item in list_sleep_epochs(payload.file_id)}
        saved: list[SleepEpoch] = []
        for assessment in assessments:
            epoch_index = payload.first_epoch_index + assessment.epoch_offset
            if epoch_index in existing and existing[epoch_index].source == "human":
                saved.append(existing[epoch_index])
                continue
            confident_n2 = (
                assessment.classification == "N2"
                and assessment.confidence >= 0.8
                and not assessment.arousal_or_artifact_present
            )
            saved.append(upsert_sleep_epoch(SleepEpochInput(
                file_id=payload.file_id,
                epoch_index=epoch_index,
                stage="N2" if confident_n2 else "uncertain",
                source="llm",
                confidence=assessment.confidence,
                spindle_present=assessment.spindle_present,
                k_complex_present=assessment.k_complex_present,
                arousal_present=assessment.arousal_or_artifact_present,
                rationale=assessment.rationale,
                notes="Auto-scored from broad-band views of two consecutive 30-second epochs.",
            )))
        return AutoN2PairResult(
            assessments=assessments,
            saved_epochs=saved,
            sleep_onset=derive_sleep_onset(payload.file_id),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sleep-epochs/export/{file_id}", response_class=PlainTextResponse)
def export_sleep_epochs(file_id: str) -> PlainTextResponse:
    try:
        meta, _ = load_recording_metadata(file_id)
        report = build_spindle_sleep_onset_report(
            subject_id=Path(meta.filename).stem or file_id,
            duration_sec=meta.duration_sec,
            annotations=list_annotations(file_id),
        )
        rows = [
            "# criterion,first_two_consecutive_30s_epochs_with_definite_spindle",
            f"# spindle_based_onset_proxy_sec,{'' if report.sleep_onset_time_sec is None else f'{report.sleep_onset_time_sec:.3f}'}",
            "epoch_index,start_sec,end_sec,spindle_present",
        ]
        last_supporting_epoch = report.supporting_epochs[-1] if report.supporting_epochs else None
        exported_epochs = (
            report.epoch_summary
            if last_supporting_epoch is None
            else [item for item in report.epoch_summary if item.epoch_index <= last_supporting_epoch]
        )
        for item in exported_epochs:
            rows.append(
                f"{item.epoch_index},{item.start_sec:.3f},{item.end_sec:.3f},"
                f"{str(item.has_accepted_spindle).lower()}"
            )
        return PlainTextResponse("\n".join(rows) + "\n", media_type="text/csv")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/eeg/window", response_model=WindowResponse)
def eeg_window(
    file_id: str,
    start_sec: float = Query(ge=0),
    duration_sec: float = Query(gt=0, le=300),
    channels: str | None = None,
    filter_type: FilterType = "broad",
) -> WindowResponse:
    try:
        return get_window(file_id, start_sec, duration_sec, channels, filter_type)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_segment(payload: SegmentRequest) -> None:
    if payload.end_sec <= payload.start_sec:
        raise HTTPException(status_code=400, detail="end_sec must be greater than start_sec.")
    if payload.end_sec - payload.start_sec > MAX_RENDER_SECONDS:
        raise HTTPException(status_code=400, detail=f"Segment is too large. Limit is {MAX_RENDER_SECONDS:g} seconds.")


@app.post("/api/render-segment", response_model=RenderResponse)
def render_segment(payload: SegmentRequest) -> RenderResponse:
    _validate_segment(payload)
    try:
        png = render_segment_png(payload.file_id, payload.start_sec, payload.end_sec, payload.channels, payload.filter_type)
        return RenderResponse(image_base64=png_to_base64(png))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/review-epoch-image/{file_id}/{epoch_index}")
def review_epoch_image(
    file_id: str,
    epoch_index: int,
    channels: str | None = None,
    start_sec: float | None = None,
    end_sec: float | None = None,
) -> Response:
    try:
        meta, _ = load_recording_metadata(file_id)
        target_start = start_sec if start_sec is not None else epoch_index * 30.0
        target_end = end_sec if end_sec is not None else target_start + 30.0
        if target_end <= target_start:
            raise ValueError("end_sec must be greater than start_sec.")
        if target_end > meta.duration_sec:
            raise ValueError("Review interval exceeds the recording duration.")
        selected = [int(value) for value in channels.split(",") if value.strip()] if channels else []
        png = render_segment_png(
            file_id, target_start, target_end,
            selected, "broad", target_start_sec=target_start, target_end_sec=target_end,
        )
        return Response(content=png, media_type="image/png")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/analyze-segment")
def analyze_segment(payload: SegmentRequest) -> dict:
    _validate_segment(payload)
    try:
        png = render_segment_png(payload.file_id, payload.start_sec, payload.end_sec, payload.channels, payload.filter_type)
        result = analyze_png(png)
        saved: list[Annotation] = []
        for event in result.definite_spindle_events:
            saved.append(
                upsert_annotation(
                    AnnotationInput(
                        file_id=payload.file_id,
                        source="llm",
                        status="proposed",
                        start_time_sec=event.start_time_sec,
                        end_time_sec=event.end_time_sec,
                        channels=event.channels,
                        confidence=event.confidence,
                        filter_type_used=payload.filter_type,
                    )
                )
            )
        return {"result": result.model_dump(), "annotations": [item.model_dump() for item in saved]}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/annotations", response_model=list[Annotation])
def annotations(file_id: str | None = None) -> list[Annotation]:
    return list_annotations(file_id)


@app.get("/api/spindle-sleep-onset/{file_id}", response_model=SpindleSleepOnsetReport)
def spindle_sleep_onset(file_id: str) -> SpindleSleepOnsetReport:
    try:
        meta, _ = load_recording_metadata(file_id)
        subject_id = Path(meta.filename).stem or file_id
        return build_spindle_sleep_onset_report(
            subject_id=subject_id,
            duration_sec=meta.duration_sec,
            annotations=list_annotations(file_id),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/annotations", response_model=Annotation)
def save_annotation(payload: AnnotationInput) -> Annotation:
    try:
        return upsert_annotation(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/annotations/{annotation_id}")
def remove_annotation(annotation_id: str) -> dict[str, bool]:
    try:
        delete_annotation(annotation_id)
        return {"deleted": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/annotations/export/{file_id}", response_class=PlainTextResponse)
def export_annotations(file_id: str) -> PlainTextResponse:
    try:
        load_recording_metadata(file_id)
        annotations = sorted(
            (
                item
                for item in list_annotations(file_id)
                if item.label == "sleep_spindle" and item.status != "rejected"
            ),
            key=lambda item: (item.start_time_sec, item.end_time_sec),
        )
        text = "\n".join(f"{item.start_time_sec:.3f}\t{item.end_time_sec:.3f}" for item in annotations)
        if text:
            text += "\n"
        return PlainTextResponse(text, media_type="text/plain")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/analysis-jobs/config")
def analysis_job_config() -> dict:
    config = GptPromptConfig().model_copy(update={"json_schema": json.dumps(EPOCH_REVIEW_SCHEMA, indent=2)})
    return {"max_segments_per_job": MAX_BATCH_SEGMENTS, "prompt_config": config.model_dump()}


@app.get("/api/analysis-jobs/{job_id}/yasa-candidates.csv", response_class=PlainTextResponse)
def export_yasa_candidates(job_id: str) -> PlainTextResponse:
    """Export every physiological event returned by YASA before agent review."""
    try:
        job = get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    rows = ["candidate_id,start_sec,end_sec,duration_sec,peak_sec,channels,relative_power"]
    for index, candidate in enumerate(job.screening_candidates, start=1):
        start = candidate.event_start_sec if candidate.event_start_sec is not None else candidate.start_sec
        end = candidate.event_end_sec if candidate.event_end_sec is not None else candidate.end_sec
        duration = candidate.event_duration_sec if candidate.event_duration_sec is not None else end - start
        channels = "|".join(label.replace('"', '""') for label in candidate.channels)
        relative_power = "" if candidate.spectral_ratio is None else f"{candidate.spectral_ratio:.4f}"
        rows.append(
            f'{index},{start:.3f},{end:.3f},{duration:.3f},{candidate.peak_time_sec:.3f},'
            f'"{channels}",{relative_power}'
        )
    return PlainTextResponse("\n".join(rows) + "\n", media_type="text/csv")


@app.post("/api/analysis-jobs", response_model=AnalysisJob)
def start_analysis_job(payload: BatchAnalysisRequest) -> AnalysisJob:
    try:
        return create_job(payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/analysis-jobs", response_model=list[AnalysisJob])
def analysis_jobs(file_id: str | None = None) -> list[AnalysisJob]:
    return list_jobs(file_id)


@app.get("/api/analysis-jobs/{job_id}", response_model=AnalysisJob)
def analysis_job(job_id: str) -> AnalysisJob:
    try:
        return get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/analysis-jobs/{job_id}/cancel", response_model=AnalysisJob)
def stop_analysis_job(job_id: str) -> AnalysisJob:
    try:
        return cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
