from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from threading import Lock

from .eeg import load_recording_metadata
from .models import SleepEpoch, SleepEpochInput, SleepOnsetResult
from .settings import SLEEP_EPOCH_FILE

EPOCH_SECONDS = 30.0
_lock = Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list[SleepEpoch]:
    return [SleepEpoch.model_validate(item) for item in json.loads(SLEEP_EPOCH_FILE.read_text(encoding="utf-8"))]


def _save(items: list[SleepEpoch]) -> None:
    SLEEP_EPOCH_FILE.write_text(json.dumps([item.model_dump() for item in items], indent=2), encoding="utf-8")


def list_sleep_epochs(file_id: str) -> list[SleepEpoch]:
    return sorted((item for item in _load() if item.file_id == file_id), key=lambda item: item.epoch_index)


def find_spindle_onset_proxy(epochs: list[SleepEpoch]) -> SleepEpoch | None:
    by_index = {item.epoch_index: item for item in epochs}
    return next(
        (
            item for item in epochs
            if item.spindle_present
            and (following := by_index.get(item.epoch_index + 1)) is not None
            and following.spindle_present
        ),
        None,
    )


def backfill_spindle_negatives(file_id: str, before_epoch_index: int) -> int:
    """Mark missing earlier epochs false after the first positive pair is confirmed."""
    if before_epoch_index <= 0:
        return 0
    meta, _ = load_recording_metadata(file_id)
    now = _now()
    with _lock:
        items = _load()
        existing = {item.epoch_index for item in items if item.file_id == file_id}
        created = 0
        for epoch_index in range(before_epoch_index):
            if epoch_index in existing:
                continue
            start = epoch_index * EPOCH_SECONDS
            end = start + EPOCH_SECONDS
            if end > meta.duration_sec:
                break
            items.append(SleepEpoch(
                id=uuid.uuid4().hex,
                file_id=file_id,
                epoch_index=epoch_index,
                start_time_sec=start,
                end_time_sec=end,
                stage="uncertain",
                source="system",
                spindle_present=False,
                notes="Auto-filled false before the first consecutive spindle-positive epoch pair.",
                created_at=now,
                updated_at=now,
            ))
            created += 1
        if created:
            _save(items)
        return created


def upsert_sleep_epoch(payload: SleepEpochInput) -> SleepEpoch:
    meta, _ = load_recording_metadata(payload.file_id)
    start = payload.epoch_index * EPOCH_SECONDS
    end = min(start + EPOCH_SECONDS, meta.duration_sec)
    if start >= meta.duration_sec:
        raise ValueError("Epoch starts outside the recording.")
    if end - start < EPOCH_SECONDS:
        raise ValueError("The final partial window cannot be scored as a complete 30-second epoch.")
    now = _now()
    with _lock:
        items = _load()
        for index, item in enumerate(items):
            if item.file_id == payload.file_id and item.epoch_index == payload.epoch_index:
                updated = SleepEpoch(
                    **payload.model_dump(), id=item.id, start_time_sec=start, end_time_sec=end,
                    created_at=item.created_at, updated_at=now,
                )
                items[index] = updated
                _save(items)
                return updated
        created = SleepEpoch(
            **payload.model_dump(), id=uuid.uuid4().hex, start_time_sec=start, end_time_sec=end,
            created_at=now, updated_at=now,
        )
        items.append(created)
        _save(items)
        return created


def delete_sleep_epoch(file_id: str, epoch_index: int) -> None:
    with _lock:
        items = _load()
        filtered = [item for item in items if not (item.file_id == file_id and item.epoch_index == epoch_index)]
        if len(filtered) == len(items):
            raise KeyError("Sleep epoch annotation not found.")
        _save(filtered)


def delete_sleep_epochs_for_file(file_id: str) -> int:
    with _lock:
        items = _load()
        filtered = [item for item in items if item.file_id != file_id]
        deleted = len(items) - len(filtered)
        _save(filtered)
        return deleted


def derive_sleep_onset(file_id: str) -> SleepOnsetResult:
    epochs = list_sleep_epochs(file_id)
    by_index = {item.epoch_index: item for item in epochs}
    for epoch in epochs:
        following = by_index.get(epoch.epoch_index + 1)
        if epoch.stage == "N2" and following and following.stage == "N2":
            return SleepOnsetResult(
                detected=True,
                onset_time_sec=epoch.start_time_sec,
                first_epoch_index=epoch.epoch_index,
                confirming_epoch_index=following.epoch_index,
            )
    return SleepOnsetResult(detected=False)
