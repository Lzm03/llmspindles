from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .annotations import delete_annotation, delete_annotations_for_file, list_annotations, upsert_annotation
from .eeg import _file_path, get_window, load_recording_metadata, png_to_base64, render_segment_png, save_upload
from .llm import analyze_png
from .jobs import MAX_BATCH_SEGMENTS, cancel_job, create_job, delete_jobs_for_file, get_job, list_jobs, resume_incomplete_jobs
from .models import AnalysisJob, Annotation, AnnotationInput, BatchAnalysisRequest, FilterType, RenderResponse, SegmentRequest, UploadResponse, WindowResponse
from .settings import MAX_RENDER_SECONDS, UPLOAD_DIR

app = FastAPI(title="EEG Spindle Annotation MVP")

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
    recording_path.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)
    return {"deleted": True, "annotations_deleted": deleted_annotations, "jobs_deleted": deleted_jobs}


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
def analysis_job_config() -> dict[str, int]:
    return {"max_segments_per_job": MAX_BATCH_SEGMENTS}


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
