from __future__ import annotations

import json
import uuid
from threading import Lock
from datetime import datetime, timezone

from .models import Annotation, AnnotationInput
from .settings import ANNOTATION_FILE

_lock = Lock()

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list[Annotation]:
    raw = json.loads(ANNOTATION_FILE.read_text(encoding="utf-8"))
    return [Annotation.model_validate(item) for item in raw]


def _save(items: list[Annotation]) -> None:
    ANNOTATION_FILE.write_text(json.dumps([item.model_dump() for item in items], indent=2), encoding="utf-8")


def list_annotations(file_id: str | None = None) -> list[Annotation]:
    items = _load()
    if file_id:
        items = [item for item in items if item.file_id == file_id]
    return items


def upsert_annotation(payload: AnnotationInput) -> Annotation:
    with _lock:
        items = _load()
        now = _now()
        if payload.id:
            for idx, item in enumerate(items):
                if item.id == payload.id:
                    updated = Annotation(**payload.model_dump(), created_at=item.created_at, updated_at=now)
                    items[idx] = updated
                    _save(items)
                    return updated
        created = Annotation(**payload.model_dump(exclude={"id"}), id=payload.id or uuid.uuid4().hex, created_at=now, updated_at=now)
        items.append(created)
        _save(items)
        return created


def delete_annotation(annotation_id: str) -> None:
    with _lock:
        items = _load()
        filtered = [item for item in items if item.id != annotation_id]
        if len(filtered) == len(items):
            raise KeyError("Annotation not found.")
        _save(filtered)


def delete_annotations_for_file(file_id: str) -> int:
    with _lock:
        items = _load()
        filtered = [item for item in items if item.file_id != file_id]
        deleted = len(items) - len(filtered)
        _save(filtered)
        return deleted
