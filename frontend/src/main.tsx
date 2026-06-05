import React from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  BrainCircuit,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Download,
  FileUp,
  Image,
  Loader2,
  MousePointer2,
  PanelRight,
  Play,
  Plus,
  Search,
  Sparkles,
  Square,
  Trash2,
  X
} from "lucide-react";
import Plot from "react-plotly.js";
import * as api from "./api";
import type { AnalysisJob, Annotation, FilterType, LlmResult, UploadResponse, WindowResponse } from "./types";
import "./styles.css";

const filterOptions: FilterType[] = ["raw", "broad", "sigma"];
const durationOptions = [5, 10, 30, 60];
const WORKSPACE_KEY = "spindle-lab-workspace-v1";
const ANALYSIS_TIMING_KEY = "spindle-lab-analysis-timing-v1";

function makeChannelSelection(count: number): number[] {
  return Array.from({ length: Math.min(count, 12) }, (_, index) => index);
}

function App() {
  const [meta, setMeta] = React.useState<UploadResponse | null>(null);
  const [windowData, setWindowData] = React.useState<WindowResponse | null>(null);
  const [annotations, setAnnotations] = React.useState<Annotation[]>([]);
  const [filterType, setFilterType] = React.useState<FilterType>("broad");
  const [startSec, setStartSec] = React.useState(0);
  const [durationSec, setDurationSec] = React.useState(10);
  const [segmentStart, setSegmentStart] = React.useState(0);
  const [segmentEnd, setSegmentEnd] = React.useState(10);
  const [channelsText, setChannelsText] = React.useState("1-12");
  const [renderedImage, setRenderedImage] = React.useState<string | null>(null);
  const [llmResult, setLlmResult] = React.useState<LlmResult | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [batchStart, setBatchStart] = React.useState(0);
  const [batchEnd, setBatchEnd] = React.useState(60);
  const [batchSegmentDuration, setBatchSegmentDuration] = React.useState(10);
  const [activeJob, setActiveJob] = React.useState<AnalysisJob | null>(null);
  const [maxBatchSegments, setMaxBatchSegments] = React.useState(500);
  const [restored, setRestored] = React.useState(false);
  const [singleAnalysisProgress, setSingleAnalysisProgress] = React.useState(0);
  const [singleAnalysisElapsed, setSingleAnalysisElapsed] = React.useState(0);
  const [singleAnalysisEstimate, setSingleAnalysisEstimate] = React.useState(() => {
    const saved = Number(localStorage.getItem(ANALYSIS_TIMING_KEY));
    return Number.isFinite(saved) && saved > 0 ? saved : 30;
  });
  const [uploadSamplingRate, setUploadSamplingRate] = React.useState<number | "">("");
  const [manualChannelsText, setManualChannelsText] = React.useState("1-12");
  const [annotationMode, setAnnotationMode] = React.useState(false);

  const selectedChannels = React.useMemo(() => parseChannels(channelsText, meta?.channel_count ?? 0), [channelsText, meta]);
  const manualChannels = React.useMemo(() => parseChannels(manualChannelsText, meta?.channel_count ?? 0), [manualChannelsText, meta]);

  async function run<T>(label: string, action: () => Promise<T>): Promise<T | null> {
    setBusy(label);
    setError(null);
    try {
      return await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function onUpload(file: File) {
    let samplingRate = uploadSamplingRate === "" ? undefined : uploadSamplingRate;
    setBusy("upload");
    setError(null);
    let result: UploadResponse;
    try {
      result = await api.uploadRecording(file, samplingRate);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (!message.includes("No sampling rate scalar found in .mat file")) {
        setError(message);
        setBusy(null);
        return;
      }
      const entered = window.prompt("This MAT file does not contain a sampling rate. Enter the sampling rate in Hz:", samplingRate ? String(samplingRate) : "250");
      if (entered === null) {
        setBusy(null);
        return;
      }
      const parsed = Number(entered);
      if (!Number.isFinite(parsed) || parsed <= 0) {
        setError("Sampling rate must be a positive number.");
        setBusy(null);
        return;
      }
      samplingRate = parsed;
      setUploadSamplingRate(parsed);
      try {
        result = await api.uploadRecording(file, parsed);
      } catch (retryError) {
        setError(retryError instanceof Error ? retryError.message : String(retryError));
        setBusy(null);
        return;
      }
    }
    setBusy(null);
    setMeta(result);
    const initialChannels = makeChannelSelection(result.channel_count);
    const initialChannelsText = channelRangeText(initialChannels);
    setChannelsText(initialChannelsText);
    setManualChannelsText(initialChannelsText);
    setStartSec(0);
    setSegmentStart(0);
    setSegmentEnd(Math.min(10, result.duration_sec));
    setBatchStart(0);
    setBatchEnd(Math.min(60, result.duration_sec));
    const ann = await api.fetchAnnotations(result.file_id).catch(() => []);
    setAnnotations(ann);
    const initialWindow = await api.fetchWindow({ fileId: result.file_id, startSec: 0, durationSec: 10, channels: initialChannels, filterType: "broad" });
    setWindowData(initialWindow);
  }

  async function loadWindow(nextStart = startSec) {
    if (!meta) return;
    const result = await run("window", () =>
      api.fetchWindow({ fileId: meta.file_id, startSec: nextStart, durationSec, channels: selectedChannels, filterType })
    );
    if (result) {
      setWindowData(result);
      setSegmentStart(result.start_sec);
      setSegmentEnd(result.start_sec + result.duration_sec);
      setManualChannelsText(channelRangeText(result.channels));
      setRenderedImage(null);
      setLlmResult(null);
      setSingleAnalysisProgress(0);
      setSingleAnalysisElapsed(0);
    }
  }

  async function render(filterOverride?: FilterType) {
    if (!meta) return;
    const image = await run("render", () =>
      api.renderSegment({
        fileId: meta.file_id,
        startSec: segmentStart,
        endSec: segmentEnd,
        channels: selectedChannels,
        filterType: filterOverride ?? filterType
      })
    );
    if (image) setRenderedImage(image);
  }

  async function analyze() {
    if (!meta) return;
    const startedAt = performance.now();
    setSingleAnalysisProgress(2);
    setSingleAnalysisElapsed(0);
    const result = await run("analyze", () =>
      api.analyzeSegment({
        fileId: meta.file_id,
        startSec: segmentStart,
        endSec: segmentEnd,
        channels: selectedChannels,
        filterType
      })
    );
    const elapsed = Math.max(1, (performance.now() - startedAt) / 1000);
    setSingleAnalysisElapsed(elapsed);
    setSingleAnalysisProgress(100);
    const nextEstimate = singleAnalysisEstimate * 0.7 + elapsed * 0.3;
    setSingleAnalysisEstimate(nextEstimate);
    localStorage.setItem(ANALYSIS_TIMING_KEY, String(nextEstimate));
    if (!result) return;
    setLlmResult(result.result);
    setAnnotations(await api.fetchAnnotations(meta.file_id));
  }

  async function setStatus(annotation: Annotation, status: Annotation["status"]) {
    const updated = await run("annotation", () => api.updateAnnotation(annotation, status));
    if (updated) setAnnotations((items) => items.map((item) => (item.id === updated.id ? updated : item)));
  }

  async function remove(annotation: Annotation) {
    const ok = await run("annotation", () => api.deleteAnnotation(annotation.id));
    if (ok !== null) setAnnotations((items) => items.filter((item) => item.id !== annotation.id));
  }

  async function saveManualAnnotation() {
    if (!meta) return;
    if (segmentEnd <= segmentStart) {
      setError("Annotation end time must be after start time.");
      return;
    }
    const channelLabels = labelsForChannels(manualChannels, meta.channel_labels);
    if (!channelLabels.length) {
      setError("Select at least one channel for the manual annotation.");
      return;
    }
    const saved = await run("annotation", () =>
      api.createManualAnnotation({
        fileId: meta.file_id,
        startSec: segmentStart,
        endSec: segmentEnd,
        channels: channelLabels,
        filterType
      })
    );
    if (saved) {
      setAnnotations((items) => [saved, ...items]);
      setLlmResult(null);
    }
  }

  async function importAnnotationFile(file: File) {
    if (!meta) return;
    const ranges = parseAnnotationText(await file.text(), meta.duration_sec);
    if (!ranges.length) {
      setError("No valid spindle time ranges found in the txt file.");
      return;
    }
    const channelLabels = labelsForChannels(manualChannels.length ? manualChannels : selectedChannels, meta.channel_labels);
    if (!channelLabels.length) {
      setError("Select at least one channel before importing annotations.");
      return;
    }
    const imported = await run("annotation", async () => {
      const saved: Annotation[] = [];
      for (const range of ranges) {
        saved.push(await api.createManualAnnotation({
          fileId: meta.file_id,
          startSec: range.start,
          endSec: range.end,
          channels: channelLabels,
          filterType
        }));
      }
      return saved;
    });
    if (imported) {
      setAnnotations((items) => [...imported, ...items]);
      const first = imported[0];
      setSegmentStart(first.start_time_sec);
      setSegmentEnd(first.end_time_sec);
      setStartSec(Math.max(0, first.start_time_sec));
      setLlmResult(null);
    }
  }

  function usePlotSelection(event: { range?: { x?: [number, number] }; points?: Array<{ x?: number }> } | null) {
    const range = event?.range?.x;
    const pointTimes = event?.points?.map((point) => Number(point.x)).filter(Number.isFinite) ?? [];
    const nextStart = range ? range[0] : Math.min(...pointTimes);
    const nextEnd = range ? range[1] : Math.max(...pointTimes);
    if (!Number.isFinite(nextStart) || !Number.isFinite(nextEnd) || nextEnd <= nextStart) return;
    setSegmentStart(roundTime(nextStart));
    setSegmentEnd(roundTime(nextEnd));
  }

  React.useEffect(() => {
    const saved = localStorage.getItem(WORKSPACE_KEY);
    void api.fetchJobConfig().then((config) => setMaxBatchSegments(config.max_segments_per_job)).catch(() => undefined);
    if (!saved) {
      setRestored(true);
      return;
    }
    try {
      const state = JSON.parse(saved);
      setStartSec(state.startSec ?? 0);
      setDurationSec(state.durationSec ?? 10);
      setFilterType(state.filterType ?? "broad");
      setChannelsText(state.channelsText ?? "1-12");
      setBatchStart(state.batchStart ?? 0);
      setBatchEnd(state.batchEnd ?? 60);
      setBatchSegmentDuration(state.batchSegmentDuration ?? 10);
      void api.fetchFileMetadata(state.fileId).then(async (metadata) => {
        setMeta(metadata);
        const ann = await api.fetchAnnotations(metadata.file_id).catch(() => []);
        setAnnotations(ann);
        const window = await api.fetchWindow({
          fileId: metadata.file_id,
          startSec: state.startSec ?? 0,
          durationSec: state.durationSec ?? 10,
          channels: parseChannels(state.channelsText ?? "1-12", metadata.channel_count),
          filterType: state.filterType ?? "broad"
        });
        setWindowData(window);
        setSegmentStart(window.start_sec);
        setSegmentEnd(window.start_sec + window.duration_sec);
        setManualChannelsText(channelRangeText(window.channels));
        if (state.activeJobId) {
          setActiveJob(await api.fetchAnalysisJob(state.activeJobId).catch(() => null));
        }
      }).catch(() => localStorage.removeItem(WORKSPACE_KEY)).finally(() => setRestored(true));
    } catch {
      localStorage.removeItem(WORKSPACE_KEY);
      setRestored(true);
    }
  }, []);

  React.useEffect(() => {
    if (!restored || !meta) return;
    localStorage.setItem(WORKSPACE_KEY, JSON.stringify({
      fileId: meta.file_id, startSec, durationSec, filterType, channelsText,
      batchStart, batchEnd, batchSegmentDuration, activeJobId: activeJob?.id ?? null
    }));
  }, [restored, meta, startSec, durationSec, filterType, channelsText, batchStart, batchEnd, batchSegmentDuration, activeJob?.id]);

  React.useEffect(() => {
    if (!activeJob || !["queued", "running"].includes(activeJob.status)) return;
    const timer = window.setInterval(() => {
      void api.fetchAnalysisJob(activeJob.id).then(async (job) => {
        setActiveJob(job);
        if (job.status === "completed" || job.status === "failed" || job.status === "cancelled") {
          if (meta) setAnnotations(await api.fetchAnnotations(meta.file_id));
        } else if (meta && job.completed_segments !== activeJob.completed_segments) {
          setAnnotations(await api.fetchAnnotations(meta.file_id));
        }
      }).catch((err) => setError(err instanceof Error ? err.message : String(err)));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [activeJob?.id, activeJob?.status, activeJob?.completed_segments, meta?.file_id]);

  React.useEffect(() => {
    if (busy !== "analyze") return;
    const started = performance.now() - singleAnalysisElapsed * 1000;
    const timer = window.setInterval(() => {
      const elapsed = (performance.now() - started) / 1000;
      setSingleAnalysisElapsed(elapsed);
      setSingleAnalysisProgress(Math.min(94, Math.max(2, elapsed / singleAnalysisEstimate * 88)));
    }, 250);
    return () => window.clearInterval(timer);
  }, [busy, singleAnalysisEstimate]);

  async function startBatch() {
    if (!meta) return;
    const job = await run("batch", () => api.startAnalysisJob({
      fileId: meta.file_id,
      startSec: batchStart,
      endSec: batchEnd,
      segmentDurationSec: batchSegmentDuration,
      channels: selectedChannels,
      filterType
    }));
    if (job) setActiveJob(job);
  }

  async function cancelBatch() {
    if (!activeJob) return;
    const job = await run("batch", () => api.cancelAnalysisJob(activeJob.id));
    if (job) setActiveJob(job);
  }

  async function removeCurrentFile() {
    if (!meta || !window.confirm("Remove this recording and all of its annotations and analysis jobs?")) return;
    const removed = await run("delete-file", () => api.deleteFile(meta.file_id));
    if (removed === null) return;
    setMeta(null);
    setWindowData(null);
    setAnnotations([]);
    setActiveJob(null);
    setRenderedImage(null);
    setLlmResult(null);
    setStartSec(0);
    setSegmentStart(0);
    setSegmentEnd(10);
    setBatchStart(0);
    setBatchEnd(60);
    setSingleAnalysisProgress(0);
    setSingleAnalysisElapsed(0);
    localStorage.removeItem(WORKSPACE_KEY);
  }

  const batchSegmentCount = Math.max(0, Math.ceil((batchEnd - batchStart) / Math.max(1, batchSegmentDuration)));

  const plot = buildPlot(windowData, annotations, { start: segmentStart, end: segmentEnd, active: annotationMode });
  const acceptedCount = annotations.filter((item) => item.status === "accepted").length;
  const proposedCount = annotations.filter((item) => item.status === "proposed").length;

  return (
    <main className="app-frame">
      <header className="topbar">
        <div className="product-mark"><BrainCircuit size={21} /><div><strong>Spindle Lab</strong><span>EEG annotation workspace</span></div></div>
        <div className="dataset-status">
          <span className={`status-dot ${meta ? "ready" : ""}`} />
          <div><strong>{meta?.filename ?? "No recording loaded"}</strong><span>{meta ? `${meta.channel_count} channels / ${meta.sampling_rate} Hz / ${formatTime(meta.duration_sec)}` : "Upload a MATLAB EEG recording to begin"}</span></div>
        </div>
        <div className="topbar-metrics">
          <span><b>{proposedCount}</b> proposed</span>
          <span><b>{acceptedCount}</b> accepted</span>
          <button className="export-action" disabled={!meta} onClick={() => meta && void api.exportAnnotations(meta.file_id)}><Download size={15} /> Export</button>
          <label className={`import-annotations ${!meta ? "disabled" : ""}`}><FileUp size={15} /> Import TXT<input type="file" accept=".txt,text/plain" disabled={!meta} onChange={(event) => { const file = event.target.files?.[0]; event.currentTarget.value = ""; if (file) void importAnnotationFile(file); }} /></label>
          <button className="remove-action" disabled={!meta} onClick={() => void removeCurrentFile()}><Trash2 size={15} /> Remove</button>
          <label className="upload-action"><FileUp size={15} /> Import File<input type="file" accept=".mat,.edf" onChange={(event) => event.target.files?.[0] && void onUpload(event.target.files[0])} /></label>
        </div>
      </header>

      <div className="workspace">
        <aside className="control-panel">
          <div className="panel-heading"><span>Recording controls</span><Activity size={16} /></div>
          {!meta && <><label className="upload-drop"><FileUp size={22} /><strong>Import EEG recording</strong><span>MATLAB .mat or EDF .edf</span><input type="file" accept=".mat,.edf" onChange={(event) => event.target.files?.[0] && void onUpload(event.target.files[0])} /></label><div className="sampling-override"><label>Sampling rate override</label><div className="input-unit"><input type="number" min="1" placeholder="Optional, e.g. 250" value={uploadSamplingRate} onChange={(event) => setUploadSamplingRate(event.target.value === "" ? "" : Number(event.target.value))} /><span>Hz</span></div><small>Used only for MAT files that do not contain a sampling rate. EDF reads sampling rate from the file header.</small></div></>}
          {meta && <div className="recording-facts"><div><span>Samples</span><b>{meta.sample_count.toLocaleString()}</b></div><div><span>Duration</span><b>{formatTime(meta.duration_sec)}</b></div></div>}

          <div className="control-section">
            <div className="section-label">Signal view</div>
            <div className="field"><label>Filter band</label><div className="segmented">{filterOptions.map((option) => <button key={option} className={filterType === option ? "active" : ""} onClick={() => setFilterType(option)}>{option}</button>)}</div></div>
            <div className="field"><label>Channels</label><input value={channelsText} onChange={(event) => setChannelsText(event.target.value)} placeholder="1-12 or 1,2,34" /><small>{selectedChannels.length} selected, max 32</small></div>
            <div className="grid-2">
              <div className="field"><label>Start time</label><div className="input-unit"><input type="number" value={startSec} onChange={(event) => setStartSec(Number(event.target.value))} /><span>sec</span></div><small>{formatMinutes(startSec)}</small></div>
              <div className="field"><label>Window</label><select value={durationSec} onChange={(event) => setDurationSec(Number(event.target.value))}>{durationOptions.map((value) => <option key={value} value={value}>{value} sec</option>)}</select></div>
            </div>
            <button className="primary" disabled={!meta || busy === "window"} onClick={() => void loadWindow()}>{busy === "window" ? <Loader2 className="spin" size={15} /> : <Play size={15} />} Load signal window</button>
          </div>

          <div className="control-section">
            <div className="section-label">Current analysis scope</div>
            <div className="current-scope">
              <Clock3 size={15} />
              <div><strong>{windowData ? `${windowData.start_sec.toFixed(2)} - ${(windowData.start_sec + windowData.duration_sec).toFixed(2)} s` : "No window loaded"}</strong><span>Analysis follows the visible signal window</span></div>
            </div>
          </div>
          <div className="control-section">
            <div className="section-label">Batch analysis</div>
            <div className="grid-2">
              <div className="field"><label>From</label><div className="input-unit"><input type="number" value={batchStart} onChange={(event) => setBatchStart(Number(event.target.value))} /><span>sec</span></div></div>
              <div className="field"><label>To</label><div className="input-unit"><input type="number" value={batchEnd} onChange={(event) => setBatchEnd(Number(event.target.value))} /><span>sec</span></div></div>
            </div>
            <div className="field"><label>Seconds per segment</label><select value={batchSegmentDuration} onChange={(event) => setBatchSegmentDuration(Number(event.target.value))}>{[5, 10, 20, 30, 60].map((value) => <option key={value} value={value}>{value} seconds</option>)}</select></div>
            <div className={`batch-estimate ${batchSegmentCount > maxBatchSegments ? "invalid" : ""}`}><span>{batchSegmentCount} segments</span><span>Maximum {maxBatchSegments}</span></div>
            <button className="primary ai-action" disabled={!meta || batchSegmentCount < 1 || batchSegmentCount > maxBatchSegments || activeJob?.status === "running" || activeJob?.status === "queued"} onClick={() => void startBatch()}><Sparkles size={15} /> Start batch analysis</button>
          </div>
          {meta && <details className="candidates"><summary>Source arrays</summary>{meta.detected_arrays.map((item) => <div key={item.key} className={item.key === meta.selected_data_key ? "candidate selected" : "candidate"}><span>{item.key}</span><small>{item.shape.join(" x ")} {item.role_hint ?? ""}</small></div>)}</details>}
          {error && <div className="error"><X size={15} /><span>{error}</span></div>}
        </aside>

        <section className="signal-workspace">
          <div className="signal-header">
            <div><span className="eyebrow">EEG trace</span><h1>{windowData ? `${windowData.start_sec.toFixed(1)} - ${(windowData.start_sec + windowData.duration_sec).toFixed(1)} seconds` : "Signal viewer"}</h1></div>
            <div className="trace-meta"><span>{filterType} band</span><span>{selectedChannels.length} channels</span><span>{windowData ? `${windowData.effective_sampling_rate.toFixed(0)} Hz display` : "Awaiting data"}</span></div>
            <div className="signal-actions">
              <button title="Render broad image" disabled={!windowData || busy === "render"} onClick={() => void render("broad")}><Image size={15} /><span>Broad</span></button>
              <button title="Render sigma image" disabled={!windowData || busy === "render"} onClick={() => void render("sigma")}><Image size={15} /><span>Sigma</span></button>
              <button className="analyze-window" disabled={!windowData || busy === "analyze"} onClick={() => void analyze()}>{busy === "analyze" ? <Loader2 className="spin" size={15} /> : <Sparkles size={15} />}<span>Analyze view</span></button>
              <button className={annotationMode ? "select-window active" : "select-window"} title="Toggle box select" disabled={!windowData} onClick={() => setAnnotationMode((value) => !value)}><MousePointer2 size={15} /><span>Select</span></button>
              <div className="navigation"><button title="Previous window" disabled={!meta} onClick={() => { const next = Math.max(0, startSec - durationSec); setStartSec(next); void loadWindow(next); }}><ChevronLeft size={17} /></button><button title="Next window" disabled={!meta} onClick={() => { const next = startSec + durationSec; setStartSec(next); void loadWindow(next); }}><ChevronRight size={17} /></button></div>
            </div>
          </div>
          <div className="trace-stage">{windowData ? <Plot {...plot} onSelected={usePlotSelection} /> : <div className="empty-state"><div className="empty-wave"><Activity size={32} /></div><strong>No signal window loaded</strong><span>Import a recording and load a time window to inspect stacked EEG traces.</span></div>}</div>
          <footer className="signal-footer"><span><span className="legend-line signal" /> Signal</span><span><span className="legend-line proposed" /> LLM proposed</span><span><span className="legend-line accepted" /> Accepted</span><span><span className="legend-line current" /> Current selection</span><span className="footer-hint">{annotationMode ? "Drag over the trace to set annotation time" : "Scroll to zoom / drag to inspect"}</span></footer>
        </section>

        <aside className="review-panel">
          <div className="panel-heading"><span>Review queue</span><PanelRight size={16} /></div>
          <div className="selection-summary"><div><span>Selected interval</span><strong>{segmentStart.toFixed(2)} - {segmentEnd.toFixed(2)} s</strong></div><span className="filter-chip">{filterType}</span></div>
          <div className="manual-tool">
            <div className="manual-tool-head"><span className="section-label">Manual annotation</span><button disabled={!windowData} onClick={() => setAnnotationMode((value) => !value)}><MousePointer2 size={13} /> {annotationMode ? "Selecting" : "Box select"}</button></div>
            <div className="grid-2">
              <div className="field"><label>Start</label><div className="input-unit"><input type="number" step="0.01" value={segmentStart} onChange={(event) => setSegmentStart(Number(event.target.value))} /><span>sec</span></div><small>{formatMinutes(segmentStart)}</small></div>
              <div className="field"><label>End</label><div className="input-unit"><input type="number" step="0.01" value={segmentEnd} onChange={(event) => setSegmentEnd(Number(event.target.value))} /><span>sec</span></div><small>{formatMinutes(segmentEnd)}</small></div>
            </div>
            <div className="field"><label>Channels</label><input value={manualChannelsText} onChange={(event) => setManualChannelsText(event.target.value)} placeholder="1-12 or 1,2,34" /><small>{manualChannels.length} channels saved with this annotation</small></div>
            <button className="primary manual-save" disabled={!meta || !windowData || busy === "annotation"} onClick={() => void saveManualAnnotation()}>{busy === "annotation" ? <Loader2 className="spin" size={15} /> : <Plus size={15} />} Save manual spindle</button>
          </div>
          {renderedImage ? <img className="preview" src={renderedImage} alt="Rendered EEG segment" /> : <div className="preview-empty"><Image size={20} /><span>Rendered segment preview</span></div>}
          {(busy === "analyze" || singleAnalysisProgress === 100) && <div className={`single-progress ${busy === "analyze" ? "running" : "completed"}`}><div className="job-progress-head"><div><span>Analyze view</span><strong>{Math.round(singleAnalysisProgress)}%</strong></div><span>{busy === "analyze" ? `${formatDuration(Math.max(0, singleAnalysisEstimate - singleAnalysisElapsed))} remaining` : `Completed in ${formatDuration(singleAnalysisElapsed)}`}</span></div><div className="progress-track"><span style={{ width: `${singleAnalysisProgress}%` }} /></div><div className="job-progress-meta"><span>{busy === "analyze" ? "LLM analysis in progress" : "Analysis complete"}</span><span>Estimated from recent analyses</span></div></div>}
          {activeJob && <div className={`job-progress ${activeJob.status}`}><div className="job-progress-head"><div><span>Batch analysis</span><strong>{activeJob.progress_percent.toFixed(1)}%</strong></div><span>{activeJob.completed_segments} / {activeJob.total_segments}</span></div><div className="progress-track"><span style={{ width: `${activeJob.progress_percent}%` }} /></div><div className="job-progress-meta"><span>{activeJob.status}</span><span>{activeJob.estimated_remaining_sec != null ? `${formatDuration(activeJob.estimated_remaining_sec)} remaining` : "Estimating time"}</span></div><div className="job-progress-meta"><span>{activeJob.annotations_created} annotations</span><span>{activeJob.failed_segments} failed segments</span></div>{["queued", "running"].includes(activeJob.status) && <button className="cancel-job" onClick={() => void cancelBatch()}><Square size={11} /> Cancel analysis</button>}{activeJob.error && <small className="job-error">{activeJob.error}</small>}</div>}
          {llmResult && <div className={`llm-result ${llmResult.contains_definite_spindle ? "positive" : "negative"}`}><div><Sparkles size={15} /><strong>{llmResult.contains_definite_spindle ? "Definite spindle proposed" : "No definite spindle detected"}</strong></div><details><summary>View model response</summary><pre>{JSON.stringify(llmResult, null, 2)}</pre></details></div>}
          <div className="queue-header"><div><span className="section-label">Annotations</span><small>{annotations.length} total</small></div><span>{proposedCount} pending</span></div>
          <div className="annotation-list">
            {annotations.length === 0 && <div className="queue-empty"><Search size={20} /><strong>No annotations yet</strong><span>Run an analysis to populate the review queue.</span></div>}
            {annotations.map((annotation) => <article key={annotation.id} className={`annotation ${annotation.status}`}><div className="annotation-top"><span className="status-label">{annotation.status}</span><span className="confidence">{annotation.confidence ? `${Math.round(annotation.confidence * 100)}%` : "manual"}</span></div><strong>{annotation.start_time_sec.toFixed(2)} - {annotation.end_time_sec.toFixed(2)} s</strong><span className="channel-list">{annotation.channels.join(", ")}</span><div className="annotation-bottom"><small>{annotation.source} / {annotation.filter_type_used}</small><div className="icon-row"><button title="Accept annotation" onClick={() => void setStatus(annotation, "accepted")}><Check size={14} /></button><button title="Reject annotation" onClick={() => void setStatus(annotation, "rejected")}><X size={14} /></button><button title="Delete annotation" onClick={() => void remove(annotation)}><Trash2 size={14} /></button></div></div></article>)}
          </div>
        </aside>
      </div>
      {busy && <div className="busy-indicator"><Loader2 className="spin" size={14} /><span>{busy === "analyze" ? "Analyzing EEG segment" : "Processing recording"}</span></div>}
    </main>
  );
}

function parseChannels(text: string, count: number): number[] {
  if (!count) return [];
  const values = new Set<number>();
  for (const rawPart of text.split(",")) {
    const part = rawPart.trim();
    if (!part) continue;
    if (part.includes("-")) {
      const [a, b] = part.split("-").map((value) => Number(value.trim()));
      for (let value = a; value <= b; value += 1) if (value >= 1 && value <= count) values.add(value - 1);
    } else {
      const value = Number(part);
      if (value >= 1 && value <= count) values.add(value - 1);
    }
  }
  return Array.from(values).slice(0, 32);
}

function channelRangeText(channels: number[]): string {
  if (!channels.length) return "";
  return `${channels[0] + 1}-${channels[channels.length - 1] + 1}`;
}

function formatTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${(seconds - minutes * 60).toFixed(1)}s`;
}

function formatMinutes(seconds: number): string {
  if (!Number.isFinite(seconds)) return "0.00 min";
  return `${(seconds / 60).toFixed(2)} min`;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.max(0, Math.ceil(seconds))}s`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.ceil((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function labelsForChannels(channels: number[], labels?: string[]): string[] {
  return channels.map((channel) => labels?.[channel] ?? `Ch ${channel + 1}`);
}

function roundTime(value: number): number {
  return Math.round(value * 100) / 100;
}

function parseAnnotationText(text: string, durationSec: number): Array<{ start: number; end: number }> {
  const ranges: Array<{ start: number; end: number }> = [];
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const values = trimmed.match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? [];
    if (values.length < 2) continue;
    const [start, end] = values;
    if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
    if (start < 0 || end <= start || end > durationSec) continue;
    ranges.push({ start: roundTime(start), end: roundTime(end) });
  }
  return ranges;
}

function buildPlot(windowData: WindowResponse | null, annotations: Annotation[], selection: { start: number; end: number; active: boolean }) {
  const offsets = windowData?.data.map((_, index) => (windowData.data.length - index - 1) * 2.5) ?? [];
  const windowStart = windowData?.start_sec ?? 0;
  const windowEnd = windowData ? windowData.start_sec + windowData.duration_sec : 0;
  const xTicks = windowData ? buildTimeTicks(windowStart, windowEnd) : null;
  const traces =
    windowData?.data.map((channel, index) => ({
      x: windowData.times_sec,
      y: channel.map((value) => value + offsets[index]),
      type: "scattergl" as const,
      mode: "lines" as const,
      name: windowData.channel_labels[index],
      line: { color: "#18345f", width: 1 }
    })) ?? [];
  const annotationShapes =
    windowData?.file_id
      ? annotations
          .filter(
            (item) =>
              item.status !== "rejected" &&
              item.end_time_sec >= windowStart &&
              item.start_time_sec <= windowEnd
          )
          .map((item) => ({
            type: "rect" as const,
            xref: "x" as const,
            yref: "paper" as const,
            x0: item.start_time_sec,
            x1: item.end_time_sec,
            y0: 0,
            y1: 1,
            fillcolor: item.status === "proposed" ? "rgba(245, 158, 11, 0.18)" : "rgba(34, 197, 94, 0.18)",
            line: { color: item.status === "proposed" ? "#d97706" : "#16a34a", width: 1 }
          }))
      : [];
  const selectionShape =
    windowData && selection.end > selection.start && selection.end >= windowStart && selection.start <= windowEnd
      ? [{
          type: "rect" as const,
          xref: "x" as const,
          yref: "paper" as const,
          x0: Math.max(selection.start, windowStart),
          x1: Math.min(selection.end, windowEnd),
          y0: 0,
          y1: 1,
          fillcolor: "rgba(8, 122, 98, 0.08)",
          line: { color: selection.active ? "#087a62" : "#7aa99b", width: 1, dash: "dot" }
        }]
      : [];
  const shapes = [...annotationShapes, ...selectionShape];
  return {
    data: traces,
    layout: {
      autosize: true,
      height: 680,
      margin: { l: 68, r: 18, t: 12, b: 46 },
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#ffffff",
      dragmode: selection.active ? "select" as const : "zoom" as const,
      xaxis: {
        title: "Time",
        range: windowData ? [windowStart, windowEnd] : undefined,
        autorange: windowData ? false : true,
        tickmode: xTicks ? "array" as const : undefined,
        tickvals: xTicks?.values,
        ticktext: xTicks?.labels,
        showgrid: true,
        gridcolor: "#edf0ee",
        zeroline: false,
        color: "#65726d"
      },
      yaxis: {
        tickvals: offsets,
        ticktext: windowData?.channel_labels ?? [],
        showgrid: false,
        zeroline: false,
        color: "#65726d"
      },
      shapes,
      showlegend: false
    },
    config: { responsive: true, displaylogo: false, scrollZoom: true, modeBarButtonsToRemove: ["lasso2d"] }
  };
}

function buildTimeTicks(start: number, end: number): { values: number[]; labels: string[] } {
  const duration = Math.max(1, end - start);
  const targetTicks = 7;
  const rawStep = duration / targetTicks;
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const step = steps.find((value) => value >= rawStep) ?? 600;
  const first = Math.ceil(start / step) * step;
  const values: number[] = [];
  for (let value = first; value <= end + step * 0.25; value += step) {
    values.push(roundTime(value));
  }
  if (!values.includes(roundTime(start))) values.unshift(roundTime(start));
  if (!values.includes(roundTime(end))) values.push(roundTime(end));
  return {
    values,
    labels: values.map((value) => `${value.toFixed(value % 1 === 0 ? 0 : 1)} s<br>${(value / 60).toFixed(2)} min`)
  };
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
