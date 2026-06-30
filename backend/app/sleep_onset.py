from __future__ import annotations

import math

from .models import Annotation, SpindleSleepOnsetReport, SpindleSupportedEpoch, VerifiedSpindle

EPOCH_SECONDS = 30.0
METHOD_NOTE = (
    "Sleep onset was estimated using a project-specific spindle-supported stable N2 rule: "
    "the start of the first epoch in the first pair of two consecutive epochs containing "
    "at least one verified spindle."
)


def _confidence_label(value: float | None, source: str) -> str:
    if value is None:
        return "high" if source == "human" else "medium"
    if value >= 0.8:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


def annotation_to_verified_spindle(annotation: Annotation) -> VerifiedSpindle:
    epoch_index = math.floor(annotation.start_time_sec / EPOCH_SECONDS)
    epoch_start = epoch_index * EPOCH_SECONDS
    return VerifiedSpindle(
        candidate_id=annotation.id,
        channel=", ".join(annotation.channels) or "unspecified",
        start_sec=round(annotation.start_time_sec, 3),
        end_sec=round(annotation.end_time_sec, 3),
        duration_sec=round(annotation.end_time_sec - annotation.start_time_sec, 3),
        epoch_index=epoch_index,
        epoch_start_sec=epoch_start,
        epoch_end_sec=epoch_start + EPOCH_SECONDS,
        confidence=_confidence_label(annotation.confidence, annotation.source),
        reason="Human-accepted spindle." if annotation.source == "human" else "Accepted agent-verified spindle.",
    )


def aggregate_spindle_epochs(
    duration_sec: float,
    annotations: list[Annotation],
) -> list[SpindleSupportedEpoch]:
    complete_epoch_count = max(0, math.floor(duration_sec / EPOCH_SECONDS))
    accepted = [
        annotation_to_verified_spindle(item)
        for item in annotations
        if item.status == "accepted"
        and 0 <= item.start_time_sec < complete_epoch_count * EPOCH_SECONDS
        and item.end_time_sec > item.start_time_sec
    ]
    by_epoch: dict[int, list[VerifiedSpindle]] = {}
    for spindle in accepted:
        by_epoch.setdefault(spindle.epoch_index, []).append(spindle)

    epochs: list[SpindleSupportedEpoch] = []
    for epoch_index in range(complete_epoch_count):
        spindles = sorted(by_epoch.get(epoch_index, []), key=lambda item: item.start_sec)
        has_spindle = bool(spindles)
        start = epoch_index * EPOCH_SECONDS
        epochs.append(SpindleSupportedEpoch(
            epoch_index=epoch_index,
            start_sec=start,
            end_sec=start + EPOCH_SECONDS,
            accepted_spindles=spindles,
            has_accepted_spindle=has_spindle,
            label="N2_like" if has_spindle else "not_N2_like",
            accepted_spindle_count=len(spindles),
        ))
    return epochs


def detect_spindle_supported_sleep_onset(
    subject_id: str,
    epochs: list[SpindleSupportedEpoch],
) -> SpindleSleepOnsetReport:
    for current, following in zip(epochs, epochs[1:], strict=False):
        if (
            current.label == "N2_like"
            and following.label == "N2_like"
            and following.epoch_index == current.epoch_index + 1
        ):
            supporting_spindles = [*current.accepted_spindles, *following.accepted_spindles]
            return SpindleSleepOnsetReport(
                subject_id=subject_id,
                detected=True,
                sleep_onset_epoch=current.epoch_index,
                sleep_onset_time_sec=current.start_sec,
                sleep_onset_time_min=round(current.start_sec / 60.0, 3),
                supporting_epochs=[current.epoch_index, following.epoch_index],
                epoch_summary=epochs,
                supporting_spindles=supporting_spindles,
                method_note=METHOD_NOTE,
            )
    return SpindleSleepOnsetReport(
        subject_id=subject_id,
        detected=False,
        epoch_summary=epochs,
        reason="No pair of consecutive spindle-supported N2-like epochs was found.",
        method_note=(
            "The result does not mean the subject did not sleep. It means the current "
            "spindle-supported N2 criterion was not satisfied."
        ),
    )


def build_spindle_sleep_onset_report(
    subject_id: str,
    duration_sec: float,
    annotations: list[Annotation],
) -> SpindleSleepOnsetReport:
    epochs = aggregate_spindle_epochs(duration_sec, annotations)
    return detect_spindle_supported_sleep_onset(subject_id, epochs)
