from __future__ import annotations

import base64
import json

from .models import CandidateSegment, GptPromptConfig, GptSpindleReviewResult, LlmAnnotationResult, N2EpochAssessment
from .settings import OPENAI_API_KEY, OPENAI_PROMPT_ID, OPENAI_PROMPT_VERSION, OPENAI_VISION_MODEL

SYSTEM_PROMPT = """
You are a conservative EEG sleep spindle annotation assistant.

Your task is to identify ONLY definite sleep spindles in EEG visualization images.

Definition of a definite sleep spindle:
A candidate event should be labeled as a sleep spindle ONLY if all of the following visual criteria are clearly satisfied:

1. It is a short rhythmic EEG burst.
2. Its duration is approximately 0.5-2.0 seconds.
3. It shows clear sigma-like activity, visually consistent with approximately 11-16 Hz.
4. It has a spindle-like waxing-and-waning amplitude envelope.
5. It is visible in more than one relevant EEG channel at approximately the same time, or is extremely clear in one channel and not contradicted by neighboring channels.
6. It is not better explained by artifact, sharp transient, K-complex alone, muscle activity, eye movement, baseline drift, or random background rhythm.

Important rule:
If there is any meaningful uncertainty, DO NOT annotate the event.

Do not output uncertain, possible, likely, suspicious, or low-confidence events.
Only output events that are clearly and confidently sleep spindles.

Output must be strict JSON only.
Do not include explanations outside JSON.
Do not invent time values or channel names.
Do not estimate events outside the visible image.
Be conservative rather than sensitive.
""".strip()

USER_PROMPT = """
Please analyze this EEG visualization image and return ONLY definite sleep spindle annotations.

Strict rule:
Only annotate a segment if you are highly confident it is a true sleep spindle.
Do not annotate possible, uncertain, weak, ambiguous, or artifact-like events.

Return strict JSON only.
""".strip()

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "contains_definite_spindle": {"type": "boolean"},
        "definite_spindle_events": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "start_time_sec": {"type": "number"},
                    "end_time_sec": {"type": "number"},
                    "channels": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["start_time_sec", "end_time_sec", "channels", "confidence"],
            },
        },
    },
    "required": ["contains_definite_spindle", "definite_spindle_events"],
}

EPOCH_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "subject_id": {"type": "string"},
        "epoch_index": {"type": "integer"},
        "target_epoch_start_sec": {"type": "number"},
        "target_epoch_end_sec": {"type": "number"},
        "time_reference": {"type": "string", "enum": ["recording_absolute_seconds"]},
        "image_quality": {"type": "string", "enum": ["good", "usable", "poor"]},
        "contains_definite_spindle": {"type": "boolean"},
        "definite_spindle_events": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "event_id": {"type": "string"}, "start_sec": {"type": "number"},
                    "end_sec": {"type": "number"}, "duration_sec": {"type": "number"},
                    "channels": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["high"]},
                    "evidence": {
                        "type": "object", "additionalProperties": False,
                        "properties": {name: {"type": "boolean"} for name in [
                            "short_rhythmic_burst", "duration_0_5_to_2_0_sec", "visual_11_16_hz_rhythm",
                            "waxing_waning_morphology", "multi_channel_or_strong_single_channel_support",
                            "broadband_eeg_reasonable",
                        ]},
                        "required": ["short_rhythmic_burst", "duration_0_5_to_2_0_sec", "visual_11_16_hz_rhythm", "waxing_waning_morphology", "multi_channel_or_strong_single_channel_support", "broadband_eeg_reasonable"],
                    },
                    "exclusion_checked": {
                        "type": "object", "additionalProperties": False,
                        "properties": {name: {"type": "boolean"} for name in [
                            "not_sharp_transient", "not_k_complex_alone", "not_muscle_activity",
                            "not_eye_movement", "not_baseline_drift", "not_random_background", "not_other_artifact",
                        ]},
                        "required": ["not_sharp_transient", "not_k_complex_alone", "not_muscle_activity", "not_eye_movement", "not_baseline_drift", "not_random_background", "not_other_artifact"],
                    },
                },
                "required": ["event_id", "start_sec", "end_sec", "duration_sec", "channels", "confidence", "evidence", "exclusion_checked"],
            },
        },
        "rejected_or_uncertain_notes": {"type": "array", "items": {"type": "string"}},
        "image_quality_note": {"type": "string"},
    },
    "required": ["subject_id", "epoch_index", "target_epoch_start_sec", "target_epoch_end_sec", "time_reference", "image_quality", "contains_definite_spindle", "definite_spindle_events", "rejected_or_uncertain_notes", "image_quality_note"],
}


def analyze_epoch_png(
    png: bytes,
    config: GptPromptConfig,
    subject_id: str,
    epoch_index: int,
    epoch_start_sec: float,
    epoch_end_sec: float,
    channels: list[str],
    yasa_candidates: list[CandidateSegment],
    context_before_sec: float,
    context_after_sec: float,
) -> GptSpindleReviewResult:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("OpenAI support is not installed in this deployment.") from exc
    variables = {
        "subject_id": subject_id, "epoch_index": str(epoch_index),
        "epoch_start_sec": f"{epoch_start_sec:.3f}", "epoch_end_sec": f"{epoch_end_sec:.3f}",
        "channels": json.dumps(channels),
        "yasa_candidates": json.dumps([item.model_dump() for item in yasa_candidates]),
        "boundary_context_before_sec": f"{context_before_sec:.3f}",
        "boundary_context_after_sec": f"{context_after_sec:.3f}",
    }
    user_prompt = config.user_prompt_template
    for name, value in variables.items():
        user_prompt = user_prompt.replace("{" + name + "}", value)
    image_b64 = base64.b64encode(png).decode("ascii")
    try:
        configured_schema = json.loads(config.json_schema) if config.json_schema.strip() else EPOCH_REVIEW_SCHEMA
    except json.JSONDecodeError as exc:
        raise ValueError(f"Prompt JSON schema is not valid JSON: {exc}") from exc
    request = {
        "model": config.model_name,
        "instructions": config.system_prompt,
        "reasoning": {"effort": config.reasoning_effort},
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": user_prompt},
            {"type": "input_image", "image_url": f"data:image/png;base64,{image_b64}"},
        ]}],
        "text": {"verbosity": config.verbosity, "format": {
            "type": "json_schema", "name": "gpt_spindle_epoch_review",
            "schema": configured_schema, "strict": True,
        }},
    }
    response = OpenAI(api_key=OPENAI_API_KEY).responses.create(**request)
    try:
        result = GptSpindleReviewResult.model_validate(json.loads(response.output_text))
    except Exception as exc:
        raise RuntimeError(f"Malformed epoch review response: {exc}") from exc

    accepted = []
    rejected = list(result.rejected_or_uncertain_notes)
    for event in result.definite_spindle_events:
        checks_pass = all(event.evidence.model_dump().values()) and all(event.exclusion_checked.model_dump().values())
        valid = (
            epoch_start_sec <= event.start_sec < event.end_sec <= epoch_end_sec
            and 0.5 <= event.end_sec - event.start_sec <= 2.0
            and checks_pass
        )
        if valid:
            event.duration_sec = round(event.end_sec - event.start_sec, 3)
            accepted.append(event)
        else:
            rejected.append(f"Excluded out-of-target or criterion-incomplete event {event.event_id}.")
    return result.model_copy(update={
        "subject_id": subject_id, "epoch_index": epoch_index,
        "target_epoch_start_sec": epoch_start_sec, "target_epoch_end_sec": epoch_end_sec,
        "contains_definite_spindle": bool(accepted), "definite_spindle_events": accepted,
        "rejected_or_uncertain_notes": rejected,
    })


def analyze_png(png: bytes) -> LlmAnnotationResult:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("OpenAI support is not installed in this deployment.") from exc
    client = OpenAI(api_key=OPENAI_API_KEY)
    image_b64 = base64.b64encode(png).decode("ascii")
    request = {
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": USER_PROMPT},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{image_b64}"},
                ],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "sleep_spindle_annotation",
                "schema": SCHEMA,
                "strict": True,
            }
        },
    }
    if OPENAI_PROMPT_ID:
        request["prompt"] = {"id": OPENAI_PROMPT_ID, "version": OPENAI_PROMPT_VERSION}
        request["reasoning"] = {"summary": "auto"}
        request["store"] = True
        request["include"] = [
            "reasoning.encrypted_content",
            "web_search_call.action.sources",
        ]
    else:
        request["model"] = OPENAI_VISION_MODEL
        request["instructions"] = SYSTEM_PROMPT
    response = client.responses.create(**request)
    try:
        payload = json.loads(response.output_text)
        return LlmAnnotationResult.model_validate(payload)
    except Exception as exc:
        raise RuntimeError(f"Malformed model response: {exc}") from exc


N2_PAIR_INSTRUCTIONS = """
You are a conservative sleep EEG staging assistant. You will receive two broad-band (0.5-30 Hz),
multi-channel EEG images, each showing one consecutive, fixed 30-second epoch. Assess each epoch as
N2, not_N2, or uncertain.

Use visible AASM-style N2 evidence: a definite sleep spindle (11-16 Hz, at least 0.5 s) or a definite
K-complex not associated with arousal. An epoch may continue as N2 from the preceding N2 epoch if its
background remains compatible and no wakefulness, arousal, stage transition, or uninterpretable artifact
is evident. Use the broad-band image for background activity, spindles, K-complexes, arousals, and
artifacts. Because only EEG images are provided, choose uncertain whenever EOG/EMG or image limitations
prevent a confident decision. Do not infer exact sleep stages other than N2. Return concise rationales.
""".strip()

N2_PAIR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "assessments": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "epoch_offset": {"type": "integer", "enum": [0, 1]},
                    "classification": {"type": "string", "enum": ["N2", "not_N2", "uncertain"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "spindle_present": {"type": "boolean"},
                    "k_complex_present": {"type": "boolean"},
                    "arousal_or_artifact_present": {"type": "boolean"},
                    "rationale": {"type": "string"},
                },
                "required": ["epoch_offset", "classification", "confidence", "spindle_present", "k_complex_present", "arousal_or_artifact_present", "rationale"],
            },
        }
    },
    "required": ["assessments"],
}


def analyze_n2_epoch_pair(
    first_broad_png: bytes,
    second_broad_png: bytes,
    first_start_sec: float,
) -> list[N2EpochAssessment]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("OpenAI support is not installed in this deployment.") from exc
    client = OpenAI(api_key=OPENAI_API_KEY)
    content = [
        {"type": "input_text", "text": f"Assess epoch 0 ({first_start_sec:.1f}-{first_start_sec + 30:.1f}s) and epoch 1 ({first_start_sec + 30:.1f}-{first_start_sec + 60:.1f}s)."},
        {"type": "input_text", "text": "Epoch 0 broad-band image (primary staging view):"},
        {"type": "input_image", "image_url": f"data:image/png;base64,{base64.b64encode(first_broad_png).decode('ascii')}"},
        {"type": "input_text", "text": "Epoch 1 broad-band image (primary staging view):"},
        {"type": "input_image", "image_url": f"data:image/png;base64,{base64.b64encode(second_broad_png).decode('ascii')}"},
    ]
    response = client.responses.create(
        model=OPENAI_VISION_MODEL,
        instructions=N2_PAIR_INSTRUCTIONS,
        input=[{"role": "user", "content": content}],
        text={"format": {"type": "json_schema", "name": "n2_epoch_pair", "schema": N2_PAIR_SCHEMA, "strict": True}},
    )
    try:
        payload = json.loads(response.output_text)
        assessments = [N2EpochAssessment.model_validate(item) for item in payload["assessments"]]
        by_offset = {item.epoch_offset: item for item in assessments}
        if set(by_offset) != {0, 1}:
            raise ValueError("Expected one assessment for each epoch offset.")
        return [by_offset[0], by_offset[1]]
    except Exception as exc:
        raise RuntimeError(f"Malformed N2 assessment response: {exc}") from exc
