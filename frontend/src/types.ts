export type FilterType = "raw" | "broad" | "sigma";
export type AnnotationStatus = "proposed" | "accepted" | "edited" | "rejected";
export type SleepStage = "W" | "N1" | "N2" | "N3" | "R" | "uncertain";

export interface ArrayCandidate {
  key: string;
  shape: number[];
  dtype: string;
  ndim: number;
  role_hint?: string | null;
}

export interface UploadResponse {
  file_id: string;
  filename: string;
  detected_arrays: ArrayCandidate[];
  selected_data_key: string;
  sampling_rate_key?: string | null;
  sampling_rate: number;
  channel_count: number;
  sample_count: number;
  duration_sec: number;
  source_format?: string;
  channel_labels?: string[];
}

export interface WindowResponse {
  file_id: string;
  start_sec: number;
  duration_sec: number;
  sampling_rate: number;
  effective_sampling_rate: number;
  channels: number[];
  channel_labels: string[];
  times_sec: number[];
  data: number[][];
}

export interface SpindleEvent {
  start_time_sec: number;
  end_time_sec: number;
  channels: string[];
  confidence: number;
}

export interface LlmResult {
  contains_definite_spindle: boolean;
  definite_spindle_events: SpindleEvent[];
}

export interface Annotation {
  id: string;
  file_id: string;
  source: "llm" | "human" | "system";
  status: AnnotationStatus;
  label: "sleep_spindle";
  start_time_sec: number;
  end_time_sec: number;
  channels: string[];
  confidence?: number | null;
  filter_type_used: FilterType;
  created_at: string;
  updated_at: string;
}

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface CandidateSegment {
  start_sec: number;
  end_sec: number;
  peak_time_sec: number;
  score: number;
  channels: string[];
  event_start_sec?: number | null;
  event_end_sec?: number | null;
  event_duration_sec?: number | null;
  spectral_ratio?: number | null;
  waxing_score?: number | null;
  screening_reason?: string | null;
}

export interface GptPromptConfig {
  system_prompt: string;
  user_prompt_template: string;
  model_name: string;
  reasoning_effort: "none" | "low" | "medium" | "high" | "xhigh";
  verbosity: "low" | "medium" | "high";
  json_schema: string;
}

export interface ReviewedSpindleEvent {
  event_id: string;
  start_sec: number;
  end_sec: number;
  duration_sec: number;
  channels: string[];
  confidence: "high";
  evidence: Record<string, boolean>;
  exclusion_checked: Record<string, boolean>;
}

export interface GptSpindleReviewResult {
  subject_id: string;
  epoch_index: number;
  target_epoch_start_sec: number;
  target_epoch_end_sec: number;
  time_reference: "recording_absolute_seconds";
  image_quality: "good" | "usable" | "poor";
  contains_definite_spindle: boolean;
  definite_spindle_events: ReviewedSpindleEvent[];
  rejected_or_uncertain_notes: string[];
  image_quality_note: string;
}

export interface ReviewedEpoch {
  subject_id: string;
  epoch_index: number;
  start_sec: number;
  end_sec: number;
  image_path: string;
  boundary_context_before_sec: number;
  boundary_context_after_sec: number;
  yasa_candidates: CandidateSegment[];
  gpt_result: GptSpindleReviewResult;
  accepted_spindle_count: number;
  label: "N2_like" | "not_N2_like";
}

export interface AnalysisJob {
  id: string;
  file_id: string;
  status: JobStatus;
  start_sec: number;
  end_sec: number;
  segment_duration_sec: number;
  channels: number[];
  filter_type: FilterType;
  total_segments: number;
  completed_segments: number;
  successful_segments: number;
  failed_segments: number;
  annotations_created: number;
  progress_percent: number;
  elapsed_sec: number;
  candidate_detection_elapsed_sec: number;
  estimated_remaining_sec?: number | null;
  current_segment_start_sec?: number | null;
  candidate_count?: number;
  candidate_segments: CandidateSegment[];
  screening_candidates?: CandidateSegment[];
  reviewed_epochs: ReviewedEpoch[];
  prompt_config: GptPromptConfig;
  sleep_onset_epoch?: number | null;
  sleep_onset_time_sec?: number | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface SleepEpoch {
  id: string;
  file_id: string;
  epoch_index: number;
  start_time_sec: number;
  end_time_sec: number;
  stage: SleepStage;
  source: "llm" | "human";
  confidence?: number | null;
  spindle_present: boolean;
  k_complex_present: boolean;
  arousal_present: boolean;
  rationale: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface N2EpochAssessment {
  epoch_offset: 0 | 1;
  classification: "N2" | "not_N2" | "uncertain";
  confidence: number;
  spindle_present: boolean;
  k_complex_present: boolean;
  arousal_or_artifact_present: boolean;
  rationale: string;
}

export interface AutoN2PairResult {
  assessments: N2EpochAssessment[];
  saved_epochs: SleepEpoch[];
  sleep_onset: SleepOnsetResult;
}

export interface VerifiedSpindle {
  candidate_id: string;
  channel: string;
  start_sec: number;
  end_sec: number;
  duration_sec: number;
  epoch_index: number;
  epoch_start_sec: number;
  epoch_end_sec: number;
  confidence: "high" | "medium" | "low";
  reason?: string | null;
}

export interface SpindleSupportedEpoch {
  epoch_index: number;
  start_sec: number;
  end_sec: number;
  accepted_spindles: VerifiedSpindle[];
  has_accepted_spindle: boolean;
  label: "N2_like" | "not_N2_like";
  accepted_spindle_count: number;
}

export interface SpindleSleepOnsetReport {
  subject_id: string;
  detected: boolean;
  sleep_onset_epoch?: number | null;
  sleep_onset_time_sec?: number | null;
  sleep_onset_time_min?: number | null;
  supporting_epochs: number[];
  epoch_summary: SpindleSupportedEpoch[];
  supporting_spindles: VerifiedSpindle[];
  reason?: string | null;
  method_note: string;
}

export interface SleepOnsetResult {
  detected: boolean;
  onset_time_sec?: number | null;
  first_epoch_index?: number | null;
  confirming_epoch_index?: number | null;
  criterion: "first_of_two_consecutive_30s_N2_epochs";
}
