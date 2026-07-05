from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import requests

from .config import (
    VOICE_OPENAI_API_KEY,
    VOICE_OPENAI_BASE_URL,
    VOICE_OPENAI_MODEL,
    VOICE_OPENAI_PROMPT,
    VOICE_OPENAI_TEMPERATURE,
    VOICE_TRANSCRIBE_PROVIDER,
    VOICE_TRANSCRIBE_TIMEOUT_SEC,
    VOICE_TRANSCRIBE_TOKEN,
    VOICE_TRANSCRIBE_URL,
)


class VoiceTranscriptionError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 500, provider: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.provider = provider


def _openai_compatible_provider_label() -> str:
    base_url = (VOICE_OPENAI_BASE_URL or "").lower()
    if "api.openai.com" in base_url:
        return "openai"
    return "whisper"


def selected_voice_transcription_provider() -> str:
    provider = (VOICE_TRANSCRIBE_PROVIDER or "auto").strip().lower()
    if provider in {"http", "custom"}:
        return "http"
    if provider == "openai":
        return _openai_compatible_provider_label()
    if provider in {"off", "disabled", "none"}:
        return "disabled"
    if VOICE_TRANSCRIBE_URL:
        return "http"
    if VOICE_OPENAI_API_KEY:
        return _openai_compatible_provider_label()
    return "disabled"


def _safe_audio_name(filename: str, content_type: str) -> str:
    name = Path(str(filename or "voice.webm").replace("\\", "/")).name.strip() or "voice.webm"
    lowered = name.lower()
    if "." in lowered:
        return name
    if "mp4" in content_type:
        return name + ".mp4"
    if "ogg" in content_type:
        return name + ".ogg"
    if "wav" in content_type:
        return name + ".wav"
    return name + ".webm"


def _parse_text_response(response: requests.Response) -> str:
    text = (response.text or "").strip()
    if not text:
        return ""
    try:
        data = response.json()
    except ValueError:
        return text
    if isinstance(data, dict):
        for key in ("text", "transcript", "transcription"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
    return text


def _clean_transcript_text(text: str) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip(" \t\r\n\"'")
    if not clean:
        return ""
    clean = _trim_prompt_leak(clean)
    clean = _collapse_repeated_chunks(clean)
    return clean.strip(" \t\r\n\"'")


def _trim_prompt_leak(text: str) -> str:
    chunks = _list_chunks(text)
    if len(chunks) < 3:
        return text
    prompt_markers = _prompt_markers()
    if not prompt_markers:
        return text
    later_chunks = {_fold(chunk) for chunk in chunks[1:]}
    if prompt_markers & later_chunks:
        return chunks[0]
    return text


def _collapse_repeated_chunks(text: str) -> str:
    chunks = _list_chunks(text)
    if len(chunks) < 4:
        return text
    folded = [_fold(chunk) for chunk in chunks if _fold(chunk)]
    if not folded:
        return text
    first = folded[0]
    repeats = sum(1 for item in folded if item == first)
    if repeats >= 3 and len(set(folded)) <= 3:
        return chunks[0]
    return text


def _list_chunks(text: str) -> list[str]:
    return [chunk.strip(" \t\r\n.?!¡¿\"'") for chunk in re.split(r"[,;\n]+", text) if chunk.strip(" \t\r\n.?!¡¿\"'")]


def _prompt_markers() -> set[str]:
    prompt = VOICE_OPENAI_PROMPT
    if ":" in prompt:
        prompt = prompt.split(":", 1)[1]
    markers = {_fold(chunk) for chunk in _list_chunks(prompt)}
    return {marker for marker in markers if len(marker) >= 4}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text.casefold()))


def _raise_http_error(provider: str, response: requests.Response) -> None:
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message") or error.get("code") or "").strip()
            else:
                detail = str(error or payload.get("message") or "").strip()
    except Exception:
        detail = (response.text or "").strip()[:180]
    message = detail or f"HTTP {response.status_code}"
    raise VoiceTranscriptionError(
        "transcriber_http_error",
        message,
        status_code=502,
        provider=provider,
    )


def _transcribe_with_http(path: Path, filename: str, content_type: str, language: str) -> dict[str, Any]:
    if not VOICE_TRANSCRIBE_URL:
        raise VoiceTranscriptionError("transcriber_url_missing", "Falta BTDIGG_VOICE_TRANSCRIBE_URL", 503, "http")
    headers = {}
    if VOICE_TRANSCRIBE_TOKEN:
        headers["Authorization"] = f"Bearer {VOICE_TRANSCRIBE_TOKEN}"
    with path.open("rb") as fh:
        response = requests.post(
            VOICE_TRANSCRIBE_URL,
            headers=headers,
            files={"audio": (_safe_audio_name(filename, content_type), fh, content_type or "application/octet-stream")},
            data={"language": language or "es"},
            timeout=max(3.0, float(VOICE_TRANSCRIBE_TIMEOUT_SEC or 20)),
        )
    if response.status_code >= 400:
        _raise_http_error("http", response)
    text = _clean_transcript_text(_parse_text_response(response))
    if not text:
        raise VoiceTranscriptionError("empty_transcript", "El transcriptor no devolvio texto", 502, "http")
    return {"text": text, "provider": "http"}


def _transcribe_with_openai(path: Path, filename: str, content_type: str, language: str) -> dict[str, Any]:
    provider_label = _openai_compatible_provider_label()
    if not VOICE_OPENAI_API_KEY:
        raise VoiceTranscriptionError("openai_key_missing", "Falta API key de transcripcion", 503, provider_label)
    url = f"{VOICE_OPENAI_BASE_URL}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {VOICE_OPENAI_API_KEY}"}
    data = {
        "model": VOICE_OPENAI_MODEL or "gpt-4o-mini-transcribe",
        "response_format": "json",
    }
    if language:
        data["language"] = language
    if VOICE_OPENAI_PROMPT:
        data["prompt"] = VOICE_OPENAI_PROMPT
    if VOICE_OPENAI_TEMPERATURE:
        data["temperature"] = VOICE_OPENAI_TEMPERATURE
    with path.open("rb") as fh:
        response = requests.post(
            url,
            headers=headers,
            files={"file": (_safe_audio_name(filename, content_type), fh, content_type or "application/octet-stream")},
            data=data,
            timeout=max(3.0, float(VOICE_TRANSCRIBE_TIMEOUT_SEC or 20)),
        )
    if response.status_code >= 400:
        _raise_http_error(provider_label, response)
    text = _clean_transcript_text(_parse_text_response(response))
    if not text:
        raise VoiceTranscriptionError("empty_transcript", "El transcriptor no devolvio texto", 502, provider_label)
    return {"text": text, "provider": provider_label, "model": data["model"]}


def transcribe_audio_file(path: Path, filename: str = "", content_type: str = "", language: str = "es") -> dict[str, Any]:
    provider = selected_voice_transcription_provider()
    if provider == "http":
        return _transcribe_with_http(path, filename, content_type, language)
    if provider in {"openai", "whisper"}:
        return _transcribe_with_openai(path, filename, content_type, language)
    raise VoiceTranscriptionError(
        "transcriber_not_configured",
        "No hay transcriptor configurado",
        status_code=503,
        provider="disabled",
    )
