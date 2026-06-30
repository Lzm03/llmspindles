from typing import Literal

from pydantic import BaseModel, Field, model_validator


FilterType = Literal["raw", "broad", "sigma"]
AnnotationStatus = Literal["proposed", "accepted", "edited", "rejected"]
AnnotationSource = Literal["llm", "human", "system"]
JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
SleepStage = Literal["W", "N1", "N2", "N3", "R", "uncertain"]

DEFAULT_SPINDLE_SYSTEM_PROMPT = """You are a conservative EEG sleep spindle annotation assistant.
Annotate only definite sleep spindles visible in the target 30-second epoch. Boundary context is for
visual continuity only and must never be annotated. A definite spindle must be a short rhythmic burst,
last 0.5-2.0 seconds, be visually consistent with 11-16 Hz, show waxing-and-waning morphology, have
multi-channel support or exceptionally clear single-channel support, and not be better explained by a
sharp transient, K-complex alone, muscle activity, eye movement, baseline drift, random background,
or another artifact. If there is meaningful uncertainty, do not annotate it."""

DEFAULT_SPINDLE_USER_TEMPLATE = """Review the broad-band EEG image for subject {subject_id}, epoch
{epoch_index}, target {epoch_start_sec}-{epoch_end_sec} recording seconds. Channels: {channels}.
YASA hints: {yasa_candidates}. The image includes {boundary_context_before_sec}s before and
{boundary_context_after_sec}s after the target epoch. Inspect the entire target epoch, not only YASA
peaks. Return strict JSON only."""


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
    segment_duration_sec: float = Field(default=30, ge=30, le=30)
    channels: list[int] = Field(default_factory=list)
    filter_type: FilterType = "broad"
    prompt_config: "GptPromptConfig | None" = None


class CandidateSegment(BaseModel):
    start_sec: float
    end_sec: float
    peak_time_sec: float
    score: float = 0
    channels: list[str] = Field(default_factory=list)
    event_start_sec: float | None = None
    event_end_sec: float | None = None
    event_duration_sec: float | None = None
    spectral_ratio: float | None = None
    waxing_score: float | None = None
    screening_reason: str | None = None


class GptPromptConfig(BaseModel):
    system_prompt: str = DEFAULT_SPINDLE_SYSTEM_PROMPT
    user_prompt_template: str = DEFAULT_SPINDLE_USER_TEMPLATE
    model_name: str = "gpt-5.4"
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = "medium"
    verbosity: Literal["low", "medium", "high"] = "low"
    json_schema: str = ""


class SpindleEvidenceChecklist(BaseModel):
    short_rhythmic_burst: bool
    duration_0_5_to_2_0_sec: bool
    visual_11_16_hz_rhythm: bool
    waxing_waning_morphology: bool
    multi_channel_or_strong_single_channel_support: bool
    broadband_eeg_reasonable: bool


class SpindleExclusionChecklist(BaseModel):
    not_sharp_transient: bool
    not_k_complex_alone: bool
    not_muscle_activity: bool
    not_eye_movement: bool
    not_baseline_drift: bool
    not_random_background: bool
    not_other_artifact: bool


class ReviewedSpindleEvent(BaseModel):
    event_id: str
    start_sec: float
    end_sec: float
    duration_sec: float
    channels: list[str]
    confidence: Literal["high"]
    evidence: SpindleEvidenceChecklist
    exclusion_checked: SpindleExclusionChecklist


class GptSpindleReviewResult(BaseModel):
    subject_id: str
    epoch_index: int
    target_epoch_start_sec: float
    target_epoch_end_sec: float
    time_reference: Literal["recording_absolute_seconds"]
    image_quality: Literal["good", "usable", "poor"]
    contains_definite_spindle: bool
    definite_spindle_events: list[ReviewedSpindleEvent] = Field(default_factory=list)
    rejected_or_uncertain_notes: list[str] = Field(default_factory=list)
    image_quality_note: str = ""


class ReviewedEpoch(BaseModel):
    subject_id: str
    epoch_index: int
    start_sec: float
    end_sec: float
    image_path: str
    boundary_context_before_sec: float
    boundary_context_after_sec: float
    yasa_candidates: list[CandidateSegment] = Field(default_factory=list)
    gpt_result: GptSpindleReviewResult
    accepted_spindle_count: int
    label: Literal["N2_like", "not_N2_like"]


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
    candidate_detection_elapsed_sec: float = 0
    estimated_remaining_sec: float | None = None
    current_segment_start_sec: float | None = None
    candidate_segments: list[CandidateSegment] = Field(default_factory=list)
    screening_candidates: list[CandidateSegment] = Field(default_factory=list)
    reviewed_epochs: list[ReviewedEpoch] = Field(default_factory=list)
    prompt_config: GptPromptConfig = Field(default_factory=GptPromptConfig)
    sleep_onset_epoch: int | None = None
    sleep_onset_time_sec: float | None = None
    candidate_count: int = 0
    error: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None


class SleepEpoch(BaseModel):
    id: str
    file_id: str
    epoch_index: int = Field(ge=0)
    start_time_sec: float = Field(ge=0)
    end_time_sec: float = Field(gt=0)
    stage: SleepStage
    source: AnnotationSource = "human"
    confidence: float | None = Field(default=None, ge=0, le=1)
    spindle_present: bool = False
    k_complex_present: bool = False
    arousal_present: bool = False
    rationale: str = ""
    notes: str = ""
    created_at: str
    updated_at: str


class SleepEpochInput(BaseModel):
    file_id: str
    epoch_index: int = Field(ge=0)
    stage: SleepStage
    source: AnnotationSource = "human"
    confidence: float | None = Field(default=None, ge=0, le=1)
    spindle_present: bool = False
    k_complex_present: bool = False
    arousal_present: bool = False
    rationale: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=500)


class SleepOnsetResult(BaseModel):
    detected: bool
    onset_time_sec: float | None = None
    first_epoch_index: int | None = None
    confirming_epoch_index: int | None = None
    criterion: str = "first_of_two_consecutive_30s_N2_epochs"


class AutoN2PairRequest(BaseModel):
    file_id: str
    first_epoch_index: int = Field(ge=0)
    channels: list[int] = Field(default_factory=list)
    filter_type: FilterType = "broad"


class N2EpochAssessment(BaseModel):
    epoch_offset: Literal[0, 1]
    classification: Literal["N2", "not_N2", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    spindle_present: bool
    k_complex_present: bool
    arousal_or_artifact_present: bool
    rationale: str


class AutoN2PairResult(BaseModel):
    assessments: list[N2EpochAssessment]
    saved_epochs: list[SleepEpoch]
    sleep_onset: SleepOnsetResult


class VerifiedSpindle(BaseModel):
    candidate_id: str
    channel: str
    start_sec: float
    end_sec: float
    duration_sec: float
    epoch_index: int
    epoch_start_sec: float
    epoch_end_sec: float
    confidence: Literal["high", "medium", "low"]
    reason: str | None = None


class SpindleSupportedEpoch(BaseModel):
    epoch_index: int
    start_sec: float
    end_sec: float
    accepted_spindles: list[VerifiedSpindle] = Field(default_factory=list)
    has_accepted_spindle: bool
    label: Literal["N2_like", "not_N2_like"]
    accepted_spindle_count: int


class SpindleSleepOnsetReport(BaseModel):
    subject_id: str
    detected: bool
    sleep_onset_epoch: int | None = None
    sleep_onset_time_sec: float | None = None
    sleep_onset_time_min: float | None = None
    supporting_epochs: list[int] = Field(default_factory=list)
    epoch_summary: list[SpindleSupportedEpoch] = Field(default_factory=list)
    supporting_spindles: list[VerifiedSpindle] = Field(default_factory=list)
    reason: str | None = None
    method_note: str
