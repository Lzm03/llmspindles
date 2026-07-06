from __future__ import annotations

import base64
import io
import json
import math
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import h5py
from scipy import io as scipy_io
from scipy import signal

from .models import ArrayCandidate, CandidateSegment, FilterType, UploadResponse, WindowResponse
from .settings import DEFAULT_CHANNEL_LIMIT, MAX_WINDOW_POINTS, UPLOAD_DIR

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _visible_keys(mat: dict[str, Any]) -> list[str]:
    return [key for key in mat.keys() if not key.startswith("__")]


def _load_container(path: Path) -> tuple[Any, str]:
    try:
        return scipy_io.loadmat(path, squeeze_me=True, struct_as_record=False), "mat"
    except (NotImplementedError, ValueError) as exc:
        try:
            return h5py.File(path, "r"), "mat-v7.3"
        except OSError:
            raise ValueError(f"Unable to read MATLAB file: {exc}") from exc


def _file_path(file_id: str) -> Path:
    matches = list(UPLOAD_DIR.glob(f"{file_id}.*"))
    for match in matches:
        if match.suffix.lower() != ".json":
            return match
    raise FileNotFoundError("Unknown file_id.")


def _clean_label(label: str, fallback: str) -> str:
    text = (label or "").strip()
    return text if text else fallback


def _repair_header_field(raw: bytes, separator: str) -> bytes:
    text = raw.decode("ascii", errors="ignore")
    repaired = "".join(char if char.isdigit() else separator for char in text)
    return repaired.encode("ascii", errors="ignore").ljust(len(raw), b" ")[: len(raw)]


def _repaired_edf_copy(path: Path) -> str | None:
    with path.open("rb") as source:
        content = bytearray(source.read())
    if len(content) < 256:
        return None
    original_date = bytes(content[168:176])
    original_time = bytes(content[176:184])
    repaired_date = _repair_header_field(original_date, ".")
    repaired_time = _repair_header_field(original_time, ".")
    if repaired_date == original_date and repaired_time == original_time:
        return None
    content[168:176] = repaired_date
    content[176:184] = repaired_time
    handle = tempfile.NamedTemporaryFile(prefix="edf-repair-", suffix=path.suffix, delete=False)
    try:
        handle.write(content)
        handle.flush()
        return handle.name
    finally:
        handle.close()


def _open_edf_reader(path: Path) -> tuple[Any, str | None]:
    try:
        import pyedflib
    except ImportError as exc:
        raise RuntimeError("EDF support is not available in this deployment.") from exc
    try:
        return pyedflib.EdfReader(str(path)), None
    except OSError as exc:
        message = str(exc).lower()
        if "startdate" not in message and "starttime" not in message:
            raise
        repaired = _repaired_edf_copy(path)
        if not repaired:
            raise
        try:
            return pyedflib.EdfReader(repaired), repaired
        except Exception:
            os.unlink(repaired)
            raise


def _load_edf_with_mne(path: Path) -> tuple[np.ndarray, float, list[str]]:
    try:
        import mne
    except ImportError as exc:
        raise RuntimeError("EDF fallback support is not available in this deployment.") from exc
    raw = mne.io.read_raw_edf(path, preload=True, verbose="ERROR", infer_types=False)
    # MNE returns Volts, while the rest of this application and YASA use µV.
    data = raw.get_data() * 1e6
    sample_rate = float(raw.info["sfreq"])
    labels = [_clean_label(name, f"Ch {index + 1}") for index, name in enumerate(raw.ch_names)]
    return data, sample_rate, labels


def inspect_edf_file(path: Path, filename: str) -> UploadResponse:
    try:
        reader, repaired_path = _open_edf_reader(path)
        try:
            signal_count = reader.signals_in_file
            labels = [_clean_label(label, f"Ch {index + 1}") for index, label in enumerate(reader.getSignalLabels())]
            sample_rates = np.asarray(reader.getSampleFrequencies(), dtype=float)
            groups: dict[float, list[int]] = {}
            for index, rate in enumerate(sample_rates):
                if np.isfinite(rate) and rate > 0:
                    groups.setdefault(float(rate), []).append(index)
            if not groups:
                raise ValueError("No readable EDF signal channels found.")
            target_rate, channel_indices = max(groups.items(), key=lambda item: (len(item[1]), item[0]))
            sample_count = int(reader.getNSamples()[channel_indices[0]])
            for channel_index in channel_indices[1:]:
                sample_count = min(sample_count, int(reader.getNSamples()[channel_index]))
            data = np.vstack([reader.readSignal(index)[:sample_count] for index in channel_indices])
            candidates = [
                ArrayCandidate(
                    key="edf_signals",
                    shape=list(data.shape),
                    dtype=str(data.dtype),
                    ndim=data.ndim,
                    role_hint="edf_data",
                )
            ]
            return UploadResponse(
                file_id=path.stem,
                filename=filename,
                detected_arrays=candidates,
                selected_data_key="edf_signals",
                sampling_rate_key="edf_header",
                sampling_rate=float(target_rate),
                channel_count=data.shape[0],
                sample_count=data.shape[1],
                duration_sec=data.shape[1] / float(target_rate),
                source_format="edf",
                channel_labels=[labels[index] for index in channel_indices],
            )
        finally:
            reader.close()
            if repaired_path:
                Path(repaired_path).unlink(missing_ok=True)
    except Exception:
        data, sample_rate, labels = _load_edf_with_mne(path)
        candidates = [
            ArrayCandidate(
                key="edf_signals",
                shape=list(data.shape),
                dtype=str(data.dtype),
                ndim=data.ndim,
                role_hint="edf_data",
            )
        ]
        return UploadResponse(
            file_id=path.stem,
            filename=filename,
            detected_arrays=candidates,
            selected_data_key="edf_signals",
            sampling_rate_key="edf_header_mne",
            sampling_rate=sample_rate,
            channel_count=data.shape[0],
            sample_count=data.shape[1],
            duration_sec=data.shape[1] / sample_rate,
            source_format="edf",
            channel_labels=labels,
        )


def _scan_values(value: Any, path: str, output: list[tuple[str, np.ndarray]], depth: int = 0) -> None:
    if depth > 8:
        return
    if isinstance(value, h5py.Dataset):
        if value.dtype.kind in "biufc":
            output.append((path, np.asarray(value)))
        return
    if isinstance(value, (h5py.File, h5py.Group)):
        for key in value.keys():
            if not key.startswith("#"):
                _scan_values(value[key], f"{path}.{key}" if path else key, output, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not key.startswith("__"):
                _scan_values(item, f"{path}.{key}" if path else key, output, depth + 1)
        return
    if hasattr(value, "_fieldnames"):
        for key in value._fieldnames:
            _scan_values(getattr(value, key), f"{path}.{key}" if path else key, output, depth + 1)
        return
    arr = np.asarray(value)
    if arr.dtype == object:
        for index, item in enumerate(arr.flat):
            _scan_values(item, f"{path}[{index}]", output, depth + 1)
        return
    if np.issubdtype(arr.dtype, np.number):
        output.append((path, arr))


def _all_numeric_values(container: Any) -> list[tuple[str, np.ndarray]]:
    values: list[tuple[str, np.ndarray]] = []
    _scan_values(container, "", values)
    return values


def _as_float_scalar(value: Any) -> float | None:
    arr = np.asarray(value)
    if arr.size != 1:
        return None
    try:
        scalar = float(arr.reshape(-1)[0])
    except (TypeError, ValueError):
        return None
    if np.isfinite(scalar) and 1 <= scalar <= 10000:
        return scalar
    return None


def inspect_mat_file(path: Path, filename: str, sampling_rate_override: float | None = None) -> UploadResponse:
    mat, source_format = _load_container(path)
    candidates: list[ArrayCandidate] = []
    scalar_rates: list[tuple[str, float]] = []
    data_candidates: list[tuple[str, np.ndarray]] = []

    numeric_values = _all_numeric_values(mat)
    for key, arr in numeric_values:
        scalar = _as_float_scalar(arr)
        if scalar is not None and ("rate" in key.lower() or "fs" in key.lower() or "sampling" in key.lower()):
            scalar_rates.append((key, scalar))
        if arr.ndim == 1 and arr.size >= 100:
            reshaped = arr.reshape(1, -1)
            data_candidates.append((key, reshaped))
            candidates.append(ArrayCandidate(key=key, shape=list(arr.shape), dtype=str(arr.dtype), ndim=arr.ndim, role_hint="single_channel_eeg"))
        elif arr.ndim == 2 and min(arr.shape) >= 1 and max(arr.shape) >= 100:
            role = "eeg_data" if min(arr.shape) <= 512 else None
            data_candidates.append((key, arr))
            candidates.append(ArrayCandidate(key=key, shape=list(arr.shape), dtype=str(arr.dtype), ndim=arr.ndim, role_hint=role))
        elif arr.ndim == 3 and max(arr.shape) >= 100:
            sample_axis = int(np.argmax(arr.shape))
            moved = np.moveaxis(arr, sample_axis, -1)
            flattened = moved.reshape(-1, moved.shape[-1])
            data_candidates.append((key, flattened))
            candidates.append(ArrayCandidate(key=key, shape=list(arr.shape), dtype=str(arr.dtype), ndim=arr.ndim, role_hint="epoched_eeg"))
        elif scalar is not None:
            candidates.append(ArrayCandidate(key=key, shape=list(arr.shape), dtype=str(arr.dtype), ndim=arr.ndim, role_hint="sampling_rate"))

    if not data_candidates:
        discovered = ", ".join(f"{key}: {list(arr.shape)} {arr.dtype}" for key, arr in numeric_values[:25]) or "no numeric arrays"
        raise ValueError(f"No EEG candidate found. Discovered: {discovered}")

    selected_key, data = max(data_candidates, key=lambda item: item[1].size)
    if sampling_rate_override is not None:
        if not np.isfinite(sampling_rate_override) or sampling_rate_override <= 0:
            raise ValueError("Sampling rate override must be a positive number.")
        scalar_rates.insert(0, ("manual_override", float(sampling_rate_override)))
    if not scalar_rates:
        for key, arr in numeric_values:
            scalar = _as_float_scalar(arr)
            if scalar is not None:
                scalar_rates.append((key, scalar))
                break
    if not scalar_rates:
        raise ValueError("No sampling rate scalar found in .mat file.")

    rate_key, sampling_rate = scalar_rates[0]
    channels, samples = normalize_channels_samples(data).shape
    duration = samples / sampling_rate
    return UploadResponse(
        file_id=path.stem,
        filename=filename,
        detected_arrays=candidates,
        selected_data_key=selected_key,
        sampling_rate_key=rate_key,
        sampling_rate=sampling_rate,
        channel_count=channels,
        sample_count=samples,
        duration_sec=duration,
        source_format=source_format,
        channel_labels=[f"Ch {index + 1}" for index in range(channels)],
    )


def save_upload(upload_file: bytes, filename: str, sampling_rate_override: float | None = None) -> UploadResponse:
    file_id = uuid.uuid4().hex
    suffix = Path(filename).suffix.lower()
    path = UPLOAD_DIR / f"{file_id}{suffix}"
    path.write_bytes(upload_file)
    try:
        if suffix == ".edf":
            if sampling_rate_override is not None:
                raise ValueError("Sampling rate override is not needed for EDF files.")
            meta = inspect_edf_file(path, filename)
        elif suffix == ".mat":
            meta = inspect_mat_file(path, filename, sampling_rate_override)
        else:
            raise ValueError("Only .mat and .edf files are supported.")
        (UPLOAD_DIR / f"{file_id}.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
        return meta
    except Exception:
        path.unlink(missing_ok=True)
        raise


def load_recording_metadata(file_id: str) -> tuple[UploadResponse, np.ndarray]:
    path = _file_path(file_id)
    metadata_path = UPLOAD_DIR / f"{file_id}.json"
    if metadata_path.exists():
        meta = UploadResponse.model_validate_json(metadata_path.read_text(encoding="utf-8"))
    else:
        meta = inspect_edf_file(path, path.name) if path.suffix.lower() == ".edf" else inspect_mat_file(path, path.name)
    if meta.source_format == "edf":
        try:
            reader, repaired_path = _open_edf_reader(path)
            try:
                labels = [_clean_label(label, f"Ch {index + 1}") for index, label in enumerate(reader.getSignalLabels())]
                sample_rates = np.asarray(reader.getSampleFrequencies(), dtype=float)
                channel_indices = [index for index, label in enumerate(labels) if label in meta.channel_labels and sample_rates[index] == meta.sampling_rate]
                data = np.vstack([reader.readSignal(index) for index in channel_indices])
            finally:
                reader.close()
                if repaired_path:
                    Path(repaired_path).unlink(missing_ok=True)
        except Exception:
            data, _, labels = _load_edf_with_mne(path)
            if meta.channel_labels:
                index_by_label = {label: index for index, label in enumerate(labels)}
                selected = [index_by_label[label] for label in meta.channel_labels if label in index_by_label]
                data = data[np.asarray(selected)] if selected else data
    else:
        mat, _ = _load_container(path)
        values = dict(_all_numeric_values(mat))
        if meta.selected_data_key not in values:
            raise ValueError(f"Selected EEG path no longer exists: {meta.selected_data_key}")
        raw = np.asarray(values[meta.selected_data_key], dtype=float)
        if raw.ndim == 1:
            raw = raw.reshape(1, -1)
        elif raw.ndim == 3:
            sample_axis = int(np.argmax(raw.shape))
            moved = np.moveaxis(raw, sample_axis, -1)
            raw = moved.reshape(-1, moved.shape[-1])
        data = normalize_channels_samples(raw)
    return meta, data


def normalize_channels_samples(data: np.ndarray) -> np.ndarray:
    if data.ndim != 2:
        raise ValueError("EEG data must be 2D.")
    rows, cols = data.shape
    if rows > cols and cols <= 512:
        data = data.T
    return np.asarray(data, dtype=float)


def parse_channels(channels: str | None, channel_count: int, fallback_limit: int = DEFAULT_CHANNEL_LIMIT) -> list[int]:
    if not channels:
        return list(range(min(channel_count, fallback_limit)))
    parsed: list[int] = []
    for part in channels.split(","):
        if not part.strip():
            continue
        idx = int(part.strip())
        if idx < 0 or idx >= channel_count:
            raise ValueError(f"Channel index out of range: {idx}")
        parsed.append(idx)
    return parsed or list(range(min(channel_count, fallback_limit)))


def filter_eeg(data: np.ndarray, sampling_rate: float, filter_type: FilterType) -> np.ndarray:
    centered = data - np.nanmedian(data, axis=1, keepdims=True)
    if filter_type == "raw":
        return centered
    low, high = (0.5, 30.0) if filter_type == "broad" else (11.0, 16.0)
    nyquist = sampling_rate / 2
    high = min(high, nyquist * 0.95)
    if low >= high:
        return centered
    # SOS is numerically stable for the very low 0.5 Hz corner used at common
    # EEG sampling rates. Direct-form coefficients can generate huge edge
    # transients which then hide the real trace after display scaling.
    sos = signal.butter(4, [low / nyquist, high / nyquist], btype="bandpass", output="sos")
    default_padlen = 3 * (2 * len(sos) + 1)
    if centered.shape[1] <= default_padlen + 1:
        return signal.sosfilt(sos, centered, axis=1)
    return signal.sosfiltfilt(sos, centered, axis=1)


def filter_eeg_window(
    data: np.ndarray,
    start: int,
    end: int,
    sampling_rate: float,
    filter_type: FilterType,
) -> np.ndarray:
    """Filter with real neighboring samples, then crop the requested window."""
    if start < 0 or end > data.shape[1] or end <= start:
        raise ValueError("Requested filter window is outside the recording.")
    if filter_type == "raw":
        return filter_eeg(data[:, start:end], sampling_rate, filter_type)

    low = 0.5 if filter_type == "broad" else 11.0
    context_cycles = 10.0 if filter_type == "broad" else 3.0
    context_samples = max(
        int(math.ceil((context_cycles / low) * sampling_rate)),
        int(math.ceil(2.0 * sampling_rate)),
    )
    context_start = max(0, start - context_samples)
    context_end = min(data.shape[1], end + context_samples)
    filtered = filter_eeg(data[:, context_start:context_end], sampling_rate, filter_type)
    crop_start = start - context_start
    return filtered[:, crop_start : crop_start + (end - start)]


def robust_scale(data: np.ndarray) -> np.ndarray:
    scaled = data.copy()
    for i in range(scaled.shape[0]):
        channel = scaled[i]
        scale = np.nanpercentile(np.abs(channel), 95)
        if not np.isfinite(scale) or scale == 0:
            scale = np.nanstd(channel) or 1.0
        scaled[i] = channel / scale
    return np.nan_to_num(scaled)


def get_window(file_id: str, start_sec: float, duration_sec: float, channels_arg: str | None, filter_type: FilterType) -> WindowResponse:
    meta, data = load_recording_metadata(file_id)
    channels = parse_channels(channels_arg, meta.channel_count)
    start = max(0, int(start_sec * meta.sampling_rate))
    end = min(meta.sample_count, int((start_sec + duration_sec) * meta.sampling_rate))
    if end <= start:
        raise ValueError("Requested window is empty.")
    selected_data = data[np.array(channels)]
    filtered = robust_scale(filter_eeg_window(selected_data, start, end, meta.sampling_rate, filter_type))
    stride = max(1, int(np.ceil(filtered.shape[1] / MAX_WINDOW_POINTS)))
    down = filtered[:, ::stride]
    times = (np.arange(start, end, stride)[: down.shape[1]] / meta.sampling_rate).astype(float)
    return WindowResponse(
        file_id=file_id,
        start_sec=start / meta.sampling_rate,
        duration_sec=(end - start) / meta.sampling_rate,
        sampling_rate=meta.sampling_rate,
        effective_sampling_rate=meta.sampling_rate / stride,
        channels=channels,
        channel_labels=[meta.channel_labels[idx] if idx < len(meta.channel_labels) else f"Ch {idx + 1}" for idx in channels],
        times_sec=times.round(4).tolist(),
        data=down.round(5).tolist(),
    )


def render_segment_png(
    file_id: str,
    start_sec: float,
    end_sec: float,
    channels: list[int],
    filter_type: FilterType,
    target_start_sec: float | None = None,
    target_end_sec: float | None = None,
) -> bytes:
    meta, data = load_recording_metadata(file_id)
    selected = channels or list(range(min(meta.channel_count, DEFAULT_CHANNEL_LIMIT)))
    for idx in selected:
        if idx < 0 or idx >= meta.channel_count:
            raise ValueError(f"Channel index out of range: {idx}")
    start = max(0, int(start_sec * meta.sampling_rate))
    end = min(meta.sample_count, int(end_sec * meta.sampling_rate))
    if end <= start:
        raise ValueError("Selected segment is empty.")
    selected_data = data[np.array(selected)]
    segment = robust_scale(filter_eeg_window(selected_data, start, end, meta.sampling_rate, filter_type))
    times = np.arange(start, end) / meta.sampling_rate
    offsets = np.arange(len(selected))[::-1] * 2.5

    fig_height = max(4, min(14, 0.45 * len(selected) + 2))
    fig, ax = plt.subplots(figsize=(13, fig_height), dpi=160)
    if target_start_sec is not None and target_end_sec is not None:
        ax.axvspan(times[0], target_start_sec, color="#d9e1de", alpha=0.62, zorder=0)
        ax.axvspan(target_end_sec, times[-1], color="#d9e1de", alpha=0.62, zorder=0)
        ax.axvline(target_start_sec, color="#0f8064", linewidth=1.1, linestyle="--")
        ax.axvline(target_end_sec, color="#0f8064", linewidth=1.1, linestyle="--")
    for i, channel in enumerate(segment):
        ax.plot(times, channel + offsets[i], color="#172554", linewidth=0.7)
    ax.set_yticks(offsets)
    ax.set_yticklabels([meta.channel_labels[idx] if idx < len(meta.channel_labels) else f"Ch {idx + 1}" for idx in selected])
    ax.set_xlabel("Time (seconds)")
    title = f"EEG segment {start_sec:.2f}-{end_sec:.2f}s ({filter_type})"
    if target_start_sec is not None and target_end_sec is not None:
        title += f" | target epoch {target_start_sec:.2f}-{target_end_sec:.2f}s"
    ax.set_title(title)
    ax.grid(axis="x", color="#d4d4d8", linewidth=0.6)
    ax.set_xlim(times[0], times[-1] if len(times) > 1 else times[0] + 1)
    ax.set_facecolor("#fbfbf8")
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    return buffer.getvalue()


def png_to_base64(png: bytes) -> str:
    return base64.b64encode(png).decode("ascii")


def _smooth_signal(values: np.ndarray, width: int) -> np.ndarray:
    if width <= 1:
        return values
    kernel = np.ones(width, dtype=float) / width
    return np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="same"), 1, values)


def _find_contiguous_regions(mask: np.ndarray) -> list[tuple[int, int]]:
    if mask.size == 0:
        return []
    edges = np.diff(mask.astype(np.int8), prepend=0, append=0)
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    return [(int(start), int(end)) for start, end in zip(starts, ends, strict=False)]


def detect_spindle_candidates(
    file_id: str,
    start_sec: float,
    end_sec: float,
    channels: list[int],
    review_window_sec: float,
) -> list[CandidateSegment]:
    meta, data = load_recording_metadata(file_id)
    selected = channels or list(range(min(meta.channel_count, DEFAULT_CHANNEL_LIMIT)))
    for idx in selected:
        if idx < 0 or idx >= meta.channel_count:
            raise ValueError(f"Channel index out of range: {idx}")
    start = max(0, int(start_sec * meta.sampling_rate))
    end = min(meta.sample_count, int(end_sec * meta.sampling_rate))
    if end <= start:
        return []

    segment = np.asarray(data[np.asarray(selected), start:end], dtype=float)
    # Remove channel DC offsets; YASA expects EEG amplitudes in microvolts.
    segment -= np.nanmedian(segment, axis=1, keepdims=True)
    try:
        import yasa
    except ImportError as exc:
        raise RuntimeError("YASA spindle detection is not installed. Run: pip install -r requirements.txt") from exc

    labels = [meta.channel_labels[index] if index < len(meta.channel_labels) else f"Ch {index + 1}" for index in selected]
    # Use the YASA 0.6.5 publication-era defaults without overriding them:
    # 12-15 Hz, 0.5-2 s, 500 ms merge distance, relative power 0.20,
    # correlation 0.65, RMS 1.5 SD, and independent per-channel detection.
    result = yasa.spindles_detect(segment, sf=meta.sampling_rate, ch_names=labels, verbose=False)
    if result is None:
        return []
    rows = result.summary().sort_values("Start").to_dict("records")
    if not rows:
        return []

    # YASA reports one row per channel. Merge temporally overlapping rows into
    # one multi-channel physiological event before creating GPT review epochs.
    groups: list[list[dict[str, Any]]] = []
    for row in rows:
        if groups and float(row["Start"]) <= max(float(item["End"]) for item in groups[-1]) + 0.15:
            groups[-1].append(row)
        else:
            groups.append([row])

    review_half_window = max(review_window_sec / 2, 1.5)
    candidates: list[CandidateSegment] = []
    for group in groups:
        detected_start_sec = start_sec + min(float(row["Start"]) for row in group)
        detected_end_sec = start_sec + max(float(row["End"]) for row in group)
        peak_time_sec = start_sec + float(max(group, key=lambda row: float(row["RelPower"]))["Peak"])
        detected_duration_sec = detected_end_sec - detected_start_sec
        spectral_ratio = float(np.mean([float(row["RelPower"]) for row in group]))
        event_channels = sorted({str(row["Channel"]) for row in group})

        if abs(review_window_sec - 30.0) < 1e-6:
            # GPT reviews fixed, recording-aligned 30-second epochs so that
            # verification and downstream N2-like aggregation share boundaries.
            candidate_start = math.floor(peak_time_sec / 30.0) * 30.0
            candidate_end = min(meta.duration_sec, candidate_start + 30.0)
        else:
            candidate_start = max(start_sec, peak_time_sec - review_half_window)
            candidate_end = min(end_sec, peak_time_sec + review_half_window)
        if candidate_end - candidate_start < 2.0:
            deficit = 2.0 - (candidate_end - candidate_start)
            candidate_start = max(start_sec, candidate_start - deficit / 2)
            candidate_end = min(end_sec, candidate_end + deficit / 2)

        candidates.append(
            CandidateSegment(
                start_sec=round(candidate_start, 3),
                end_sec=round(candidate_end, 3),
                peak_time_sec=round(peak_time_sec, 3),
                score=round(spectral_ratio, 4),
                event_start_sec=round(detected_start_sec, 3),
                event_end_sec=round(detected_end_sec, 3),
                event_duration_sec=round(detected_duration_sec, 3),
                spectral_ratio=round(spectral_ratio, 4),
                waxing_score=None,
                screening_reason=(
                    "YASA 0.6.5 defaults: 12-15 Hz, 0.5-2.0 s, relative power >= 0.20, "
                    "broad/sigma correlation >= 0.65, RMS >= mean + 1.5 SD."
                ),
                channels=event_channels,
            )
        )

    candidates.sort(key=lambda item: item.event_start_sec or item.peak_time_sec)
    return candidates
