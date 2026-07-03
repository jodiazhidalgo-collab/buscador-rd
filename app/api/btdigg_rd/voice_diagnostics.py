from __future__ import annotations

import re
import time
from typing import Any

from .blackbox import voice_event
from .retention import cleanup_voice_diagnostic_runs


ALLOWED_EVENTS = {
    "voice_record_click",
    "voice_busy_click",
    "voice_permission_state",
    "voice_get_user_media_start",
    "voice_get_user_media_ok",
    "voice_get_user_media_error",
    "voice_recorder_start",
    "voice_audio_detected",
    "voice_silence_auto_stop",
    "voice_no_speech_timeout",
    "voice_manual_stop",
    "voice_recorder_stop",
    "voice_recorder_error",
    "voice_upload_start",
    "voice_upload_ok",
    "voice_upload_error",
    "voice_transcribe_request",
    "voice_transcribe_provider_start",
    "voice_transcribe_ok",
    "voice_transcribe_error",
    "voice_resolver_start",
    "voice_resolver_ok",
    "voice_resolver_error",
    "voice_unsupported",
    "voice_insecure_context",
    "voice_cleanup",
}

FINAL_STATUS = {
    "voice_upload_ok": "ok",
    "voice_transcribe_ok": "ok",
    "voice_get_user_media_error": "error",
    "voice_recorder_error": "error",
    "voice_upload_error": "error",
    "voice_transcribe_error": "error",
    "voice_no_speech_timeout": "error",
    "voice_manual_stop": "cancelled",
    "voice_unsupported": "error",
    "voice_insecure_context": "error",
}

ALLOWED_DATA_KEYS = {
    "alternatives_count",
    "audio_size",
    "button_disabled",
    "content_type",
    "duration_ms",
    "elapsed_ms",
    "error",
    "file_ext",
    "has_media_devices",
    "has_media_recorder",
    "is_secure_context",
    "lang",
    "languages",
    "message",
    "mime_type",
    "mobile",
    "permission_error",
    "permission_state",
    "platform",
    "provider",
    "reason",
    "resolved",
    "response_ok",
    "screen",
    "state",
    "status_code",
    "text_len",
    "timeout_ms",
    "touch_points",
    "transcript_preview",
    "url",
    "user_agent",
    "vendor",
    "visibility",
    "viewport",
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

    if event == "voice_record_click":
        cleanup_voice_diagnostic_runs()

    return {"ok": True, "trace_id": trace_id, "event": event}, 200
