export type FilterType = "raw" | "broad" | "sigma";
export type AnnotationStatus = "proposed" | "accepted" | "edited" | "rejected";

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
  source: "llm" | "human";
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
  estimated_remaining_sec?: number | null;
  current_segment_start_sec?: number | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}
