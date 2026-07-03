from __future__ import annotations

import re
import time
from typing import Any

from .blackbox import voice_event
from .retention import cleanup_voice_diagnostic_runs


ALLOWED_EVENTS = {
    "voice_click",
    "voice_busy_click",
    "voice_support_detected",
    "voice_permission_state",
    "voice_android_warmup_start",
    "voice_android_warmup_ok",
    "voice_android_warmup_fail",
    "voice_start_called",
    "voice_onstart",
    "voice_audiostart",
    "voice_soundstart",
    "voice_speechstart",
    "voice_result",
    "voice_nomatch",
    "voice_error",
    "voice_end",
    "voice_timeout_no_start",
    "voice_no_speech_timeout",
    "voice_manual_stop",
    "voice_unsupported",
    "voice_insecure_context",
}

FINAL_STATUS = {
    "voice_result": "ok",
    "voice_error": "error",
    "voice_timeout_no_start": "error",
    "voice_no_speech_timeout": "error",
    "voice_manual_stop": "cancelled",
    "voice_unsupported": "error",
    "voice_insecure_context": "error",
}

ALLOWED_DATA_KEYS = {
    "alternatives_count",
    "audio_track_count",
    "button_disabled",
    "elapsed_ms",
    "error",
    "event_error",
    "got_result",
    "has_media_devices",
    "has_speech_recognition",
    "is_secure_context",
    "language",
    "languages",
    "message",
    "mobile",
    "permission_error",
    "permission_state",
    "platform",
    "recognition_ctor",
    "result_count",
    "screen",
    "state",
    "timeout_ms",
    "touch_points",
    "track_count",
    "transcript_preview",
    "url",
    "user_agent",
    "vendor",
    "visibility",
    "viewport",
    "warmup_status",
}


def _clean_trace_id(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:90].strip("._-")
    if text:
        return text
    return f"voice-{int(time.time() * 1000)}"


def _compact(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, list):
        return [_compact(item) for item in value[:8]]
    if isinstance(value, dict):
        return {str(k)[:40]: _compact(v) for k, v in list(value.items())[:12]}
    text = str(value or "").strip()
    if len(text) > 220:
        return text[:220] + "...[truncated]"
    return text


def _clean_data(raw: Any, user_agent: str = "") -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key, value in source.items():
        clean_key = str(key or "").strip()
        if clean_key not in ALLOWED_DATA_KEYS:
            continue
        out[clean_key] = _compact(value)
    if user_agent and "user_agent" not in out:
        out["user_agent"] = _compact(user_agent)
    return out


def record_voice_diagnostic(payload: dict[str, Any], user_agent: str = "") -> tuple[dict[str, Any], int]:
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload no valido"}, 400

    trace_id = _clean_trace_id(payload.get("trace_id"))
    event = str(payload.get("event") or "").strip().lower()
    if event not in ALLOWED_EVENTS:
        return {"ok": False, "error": "evento voice no valido", "trace_id": trace_id}, 400

    data = _clean_data(payload.get("data"), user_agent=user_agent)
    status = FINAL_STATUS.get(event)
    voice_event(trace_id, event, status=status, **data)

    if event == "voice_click":
        cleanup_voice_diagnostic_runs()

    return {"ok": True, "trace_id": trace_id, "event": event}, 200
