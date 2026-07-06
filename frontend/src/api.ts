import type { AnalysisJob, Annotation, AnnotationStatus, AutoN2PairResult, FilterType, GptPromptConfig, LlmResult, SleepEpoch, SleepOnsetResult, SleepStage, SpindleSleepOnsetReport, UploadResponse, WindowResponse } from "./types";

const jsonHeaders = { "Content-Type": "application/json" };

async function readJson<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "Request failed");
  }
  return payload as T;
}

export async function uploadRecording(file: File, samplingRate?: number): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  if (samplingRate && samplingRate > 0) form.append("sampling_rate", String(samplingRate));
  return readJson<UploadResponse>(await fetch("/api/upload", { method: "POST", body: form }));
}

export async function fetchFileMetadata(fileId: string): Promise<UploadResponse> {
  return readJson<UploadResponse>(await fetch(`/api/files/${encodeURIComponent(fileId)}`));
}

export async function deleteFile(fileId: string): Promise<void> {
  await readJson(await fetch(`/api/files/${encodeURIComponent(fileId)}`, { method: "DELETE" }));
}

export async function fetchWindow(args: {
  fileId: string;
  startSec: number;
  durationSec: number;
  channels: number[];
  filterType: FilterType;
}): Promise<WindowResponse> {
  const params = new URLSearchParams({
    file_id: args.fileId,
    start_sec: String(args.startSec),
    duration_sec: String(args.durationSec),
    channels: args.channels.join(","),
    filter_type: args.filterType
  });
  return readJson<WindowResponse>(await fetch(`/api/eeg/window?${params.toString()}`));
}

export async function renderSegment(args: {
  fileId: string;
  startSec: number;
  endSec: number;
  channels: number[];
  filterType: FilterType;
}): Promise<string> {
  const payload = {
    file_id: args.fileId,
    start_sec: args.startSec,
    end_sec: args.endSec,
    channels: args.channels,
    filter_type: args.filterType
  };
  const result = await readJson<{ image_base64: string; mime_type: string }>(
    await fetch("/api/render-segment", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) })
  );
  return `data:${result.mime_type};base64,${result.image_base64}`;
}

export async function analyzeSegment(args: {
  fileId: string;
  startSec: number;
  endSec: number;
  channels: number[];
  filterType: FilterType;
}): Promise<{ result: LlmResult; annotations: Annotation[] }> {
  const payload = {
    file_id: args.fileId,
    start_sec: args.startSec,
    end_sec: args.endSec,
    channels: args.channels,
    filter_type: args.filterType
  };
  return readJson(await fetch("/api/analyze-segment", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }));
}

export async function fetchAnnotations(fileId: string): Promise<Annotation[]> {
  return readJson<Annotation[]>(await fetch(`/api/annotations?file_id=${encodeURIComponent(fileId)}`));
}

export async function fetchSleepEpochs(fileId: string): Promise<SleepEpoch[]> {
  return readJson<SleepEpoch[]>(await fetch(`/api/sleep-epochs?file_id=${encodeURIComponent(fileId)}`));
}

export async function saveSleepEpoch(args: {
  fileId: string;
  epochIndex: number;
  stage: SleepStage;
  spindlePresent: boolean;
  notes: string;
}): Promise<SleepEpoch> {
  return readJson<SleepEpoch>(await fetch("/api/sleep-epochs", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      file_id: args.fileId,
      epoch_index: args.epochIndex,
      stage: args.stage,
      source: "human",
      spindle_present: args.spindlePresent,
      notes: args.notes
    })
  }));
}

export async function autoScoreN2Pair(args: {
  fileId: string;
  firstEpochIndex: number;
  channels: number[];
  filterType: FilterType;
}): Promise<AutoN2PairResult> {
  return readJson<AutoN2PairResult>(await fetch("/api/auto-score-n2-pair", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      file_id: args.fileId,
      first_epoch_index: args.firstEpochIndex,
      channels: args.channels,
      filter_type: args.filterType
    })
  }));
}

export async function fetchSleepOnset(fileId: string): Promise<SleepOnsetResult> {
  return readJson<SleepOnsetResult>(await fetch(`/api/sleep-onset/${encodeURIComponent(fileId)}`));
}

export async function fetchSpindleSleepOnset(fileId: string): Promise<SpindleSleepOnsetReport> {
  return readJson<SpindleSleepOnsetReport>(await fetch(`/api/spindle-sleep-onset/${encodeURIComponent(fileId)}`));
}

export function exportSleepEpochs(fileId: string, report: SpindleSleepOnsetReport): void {
  const onset = report.sleep_onset_time_sec == null ? "" : report.sleep_onset_time_sec.toFixed(3);
  const lastSupportingEpoch = report.supporting_epochs[report.supporting_epochs.length - 1];
  const exportedEpochs = lastSupportingEpoch == null
    ? report.epoch_summary
    : report.epoch_summary.filter((epoch) => epoch.epoch_index <= lastSupportingEpoch);
  const rows = [
    "# criterion,first_two_consecutive_30s_epochs_with_definite_spindle",
    `# spindle_based_onset_proxy_sec,${onset}`,
    "epoch_index,start_sec,end_sec,spindle_present",
    ...exportedEpochs.map((epoch) =>
      `${epoch.epoch_index},${epoch.start_sec.toFixed(3)},${epoch.end_sec.toFixed(3)},${epoch.has_accepted_spindle}`
    )
  ];
  const blob = new Blob([`${rows.join("\n")}\n`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `spindle-epoch-gt-${fileId}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function updateAnnotation(annotation: Annotation, status: AnnotationStatus): Promise<Annotation> {
  return readJson<Annotation>(
    await fetch("/api/annotations", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ ...annotation, status, source: status === "accepted" ? annotation.source : annotation.source })
    })
  );
}

export async function createManualAnnotation(args: {
  fileId: string;
  startSec: number;
  endSec: number;
  channels: string[];
  filterType: FilterType;
}): Promise<Annotation> {
  return readJson<Annotation>(
    await fetch("/api/annotations", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        file_id: args.fileId,
        source: "human",
        status: "accepted",
        label: "sleep_spindle",
        start_time_sec: args.startSec,
        end_time_sec: args.endSec,
        channels: args.channels,
        confidence: null,
        filter_type_used: args.filterType
      })
    })
  );
}

export async function deleteAnnotation(id: string): Promise<void> {
  await readJson(await fetch(`/api/annotations/${id}`, { method: "DELETE" }));
}

export async function startAnalysisJob(args: {
  fileId: string;
  startSec: number;
  endSec: number;
  segmentDurationSec: number;
  channels: number[];
  filterType: FilterType;
  promptConfig?: GptPromptConfig;
  reviewWithGpt?: boolean;
}): Promise<AnalysisJob> {
  return readJson<AnalysisJob>(
    await fetch("/api/analysis-jobs", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        file_id: args.fileId,
        start_sec: args.startSec,
        end_sec: args.endSec,
        segment_duration_sec: args.segmentDurationSec,
        channels: args.channels,
        filter_type: args.filterType,
        prompt_config: args.promptConfig,
        review_with_gpt: args.reviewWithGpt ?? true
      })
    })
  );
}

export async function fetchAnalysisJob(jobId: string): Promise<AnalysisJob> {
  return readJson<AnalysisJob>(await fetch(`/api/analysis-jobs/${encodeURIComponent(jobId)}`));
}

export async function fetchAnalysisJobs(fileId: string): Promise<AnalysisJob[]> {
  return readJson<AnalysisJob[]>(await fetch(`/api/analysis-jobs?file_id=${encodeURIComponent(fileId)}`));
}

export async function cancelAnalysisJob(jobId: string): Promise<AnalysisJob> {
  return readJson<AnalysisJob>(await fetch(`/api/analysis-jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }));
}

export async function fetchJobConfig(): Promise<{ max_segments_per_job: number; prompt_config: GptPromptConfig }> {
  return readJson(await fetch("/api/analysis-jobs/config"));
}

export async function exportYasaCandidates(jobId: string, fileId: string): Promise<void> {
  const response = await fetch(`/api/analysis-jobs/${encodeURIComponent(jobId)}/yasa-candidates.csv`);
  if (!response.ok) {
    await readJson(response);
    return;
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `yasa-spindle-intervals-${fileId}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function exportAnnotations(fileId: string): Promise<void> {
  const response = await fetch(`/api/annotations/export/${encodeURIComponent(fileId)}`);
  if (!response.ok) {
    await readJson(response);
    return;
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `spindle-annotations-${fileId}.txt`;
  anchor.click();
  URL.revokeObjectURL(url);
}
