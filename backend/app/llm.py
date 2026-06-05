from __future__ import annotations

import base64
import json

from .models import LlmAnnotationResult
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
