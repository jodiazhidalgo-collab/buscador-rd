from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from api.btdigg_rd import voice_transcription as voice  # noqa: E402


class FakeResponse:
    status_code = 200
    text = '{"text": "John Wick 4"}'

    def json(self):
        return {"text": "John Wick 4"}


def test_openai_compatible_transcription_sends_movie_context(tmp_path, monkeypatch):
    audio = tmp_path / "voice.webm"
    audio.write_bytes(b"fake-audio")
    captured = {}

    monkeypatch.setattr(voice, "VOICE_OPENAI_API_KEY", "local-whisper")
    monkeypatch.setattr(voice, "VOICE_OPENAI_BASE_URL", "http://whisper:9000/v1")
    monkeypatch.setattr(voice, "VOICE_OPENAI_MODEL", "whisper-1")
    monkeypatch.setattr(voice, "VOICE_OPENAI_PROMPT", "Titulos de peliculas: John Wick 4.")
    monkeypatch.setattr(voice, "VOICE_OPENAI_TEMPERATURE", "0")

    def fake_post(url, headers, files, data, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["data"] = dict(data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(voice.requests, "post", fake_post)

    result = voice.transcribe_audio_file(audio, filename="voice.webm", content_type="audio/webm", language="es")

    assert result["text"] == "John Wick 4"
    assert captured["url"] == "http://whisper:9000/v1/audio/transcriptions"
    assert captured["headers"]["Authorization"] == "Bearer local-whisper"
    assert captured["data"] == {
        "model": "whisper-1",
        "response_format": "json",
        "language": "es",
        "prompt": "Titulos de peliculas: John Wick 4.",
        "temperature": "0",
    }
