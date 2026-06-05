from typing import Literal

from pydantic import BaseModel, Field, model_validator


FilterType = Literal["raw", "broad", "sigma"]
AnnotationStatus = Literal["proposed", "accepted", "edited", "rejected"]
AnnotationSource = Literal["llm", "human"]
JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class ArrayCandidate(BaseModel):
    key: str
    shape: list[int]
    dtype: str
    ndim: int
    role_hint: str | None = None


class UploadResponse(BaseModel):
    file_id: str
    filename: str
    detected_arrays: list[ArrayCandidate]
    selected_data_key: str
    sampling_rate_key: str | None
    sampling_rate: float
    channel_count: int
    sample_count: int
    duration_sec: float
    source_format: str = "mat"
    channel_labels: list[str] = Field(default_factory=list)


class WindowResponse(BaseModel):
    file_id: str
    start_sec: float
    duration_sec: float
    sampling_rate: float
    effective_sampling_rate: float
    channels: list[int]
    channel_labels: list[str]
    times_sec: list[float]
    data: list[list[float]]


class SegmentRequest(BaseModel):
    file_id: str
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    channels: list[int] = Field(default_factory=list)
    filter_type: FilterType = "broad"


class RenderResponse(BaseModel):
    image_base64: str
    mime_type: str = "image/png"


class SpindleEvent(BaseModel):
    start_time_sec: float
    end_time_sec: float
    channels: list[str]
    confidence: float = Field(ge=0, le=1)


class LlmAnnotationResult(BaseModel):
    contains_definite_spindle: bool
    definite_spindle_events: list[SpindleEvent]


class Annotation(BaseModel):
    id: str
    file_id: str
    source: AnnotationSource
    status: AnnotationStatus
    label: Literal["sleep_spindle"] = "sleep_spindle"
    start_time_sec: float
    end_time_sec: float
    channels: list[str]
    confidence: float | None = None
    filter_type_used: FilterType = "broad"
    created_at: str
    updated_at: str


class AnnotationInput(BaseModel):
    id: str | None = None
    file_id: str
    source: AnnotationSource = "human"
    status: AnnotationStatus = "accepted"
    label: Literal["sleep_spindle"] = "sleep_spindle"
    start_time_sec: float
    end_time_sec: float
    channels: list[str]
    confidence: float | None = Field(default=None, ge=0, le=1)
    filter_type_used: FilterType = "broad"

    @model_validator(mode="after")
    def validate_time_range(self) -> "AnnotationInput":
        if self.end_time_sec <= self.start_time_sec:
            raise ValueError("Annotation end_time_sec must be greater than start_time_sec.")
        return self


class BatchAnalysisRequest(BaseModel):
    file_id: str
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    segment_duration_sec: float = Field(default=10, ge=2, le=120)
    channels: list[int] = Field(default_factory=list)
    filter_type: FilterType = "broad"


class AnalysisJob(BaseModel):
    id: str
    file_id: str
    status: JobStatus
    start_sec: float
    end_sec: float
    segment_duration_sec: float
    channels: list[int]
    filter_type: FilterType
    total_segments: int
    completed_segments: int = 0
    successful_segments: int = 0
    failed_segments: int = 0
    annotations_created: int = 0
    progress_percent: float = 0
    elapsed_sec: float = 0
    estimated_remaining_sec: float | None = None
    current_segment_start_sec: float | None = None
    error: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None
