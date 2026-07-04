from __future__ import annotations

import importlib
import io
import json


def _voice_events(root, trace_id: str) -> list[dict]:
    matches = list((root / "diagnostics" / "btdigg" / "voice").glob(f"*/{trace_id}/events.jsonl"))
    assert len(matches) == 1
    return [json.loads(line) for line in matches[0].read_text(encoding="utf-8").splitlines() if line.strip()]


def test_voice_blackbox_uses_separate_collection(isolated_data_dir, reload_data_dir_modules):
    reload_data_dir_modules("api.btdigg_rd.voice_diagnostics")
    blackbox = importlib.import_module("api.btdigg_rd.blackbox")

    blackbox.voice_event("voice-contract", "voice_record_click", is_secure_context=True, has_media_recorder=True)

    events = _voice_events(isolated_data_dir, "voice-contract")
    assert events[0]["trace_kind"] == "voice"
    assert events[0]["event"] == "voice_record_click"
    assert events[0]["phase"] == "voice"
    assert not (isolated_data_dir / "diagnostics" / "btdigg" / "jobs" / "voice-contract").exists()


def test_voice_diagnostic_route_writes_compact_trace(client, isolated_data_dir):
    response = client.post(
        "/api/voice/diagnostic",
        json={
            "trace_id": "voice-route-contract",
            "event": "voice_upload_error",
            "data": {
                "error": "transcriber_not_configured",
                "transcript_preview": "x" * 500,
                "ignored_key": "must_not_be_saved",
            },
        },
        headers={"User-Agent": "pytest-mobile"},
    )

    assert response.status_code == 200
    assert response.json["ok"] is True

    record = _voice_events(isolated_data_dir, "voice-route-contract")[0]
    assert record["event"] == "voice_upload_error"
    assert record["data"]["error"] == "transcriber_not_configured"
    assert "ignored_key" not in record["data"]
    assert record["data"]["user_agent"] == "pytest-mobile"
    assert len(record["data"]["transcript_preview"]) < 260


def test_voice_diagnostic_rejects_old_speech_recognition_events(client):
    response = client.post(
        "/api/voice/diagnostic",
        json={"trace_id": "voice-old", "event": "voice_android_warmup_ok", "data": {}},
    )

    assert response.status_code == 400
    assert response.json["ok"] is False


def test_voice_diagnostic_accepts_mediarecorder_lifecycle(client, isolated_data_dir):
    trace_id = "voice-mediarecorder"
    for event, data in (
        ("voice_record_click", {"has_media_recorder": True}),
        ("voice_get_user_media_start", {"state": "requesting_micro"}),
        ("voice_get_user_media_ok", {"state": "micro_ready"}),
        ("voice_recorder_start", {"mime_type": "audio/webm"}),
        ("voice_audio_detected", {"state": "voice_detected"}),
        ("voice_silence_auto_stop", {"timeout_ms": 900}),
        ("voice_recorder_stop", {"audio_size": 1234, "duration_ms": 1400, "reason": "auto_silence"}),
        ("voice_upload_start", {"audio_size": 1234, "mime_type": "audio/webm"}),
    ):
        response = client.post("/api/voice/diagnostic", json={"trace_id": trace_id, "event": event, "data": data})
        assert response.status_code == 200
        assert response.json["ok"] is True

    events = _voice_events(isolated_data_dir, trace_id)
    assert [item["event"] for item in events] == [
        "voice_record_click",
        "voice_get_user_media_start",
        "voice_get_user_media_ok",
        "voice_recorder_start",
        "voice_audio_detected",
        "voice_silence_auto_stop",
        "voice_recorder_stop",
        "voice_upload_start",
    ]


def test_voice_transcribe_route_rejects_missing_audio(client, isolated_data_dir):
    response = client.post("/api/voice/transcribe", data={"trace_id": "voice-missing"})

    assert response.status_code == 400
    assert response.json["ok"] is False
    assert response.json["error_code"] == "missing_audio"
    events = _voice_events(isolated_data_dir, "voice-missing")
    assert events[0]["event"] == "voice_transcribe_error"
    assert not (isolated_data_dir / "diagnostics" / "btdigg" / "jobs" / "voice-missing").exists()


def test_voice_transcribe_route_returns_not_configured_cleanly(client, isolated_data_dir, monkeypatch):
    routes = importlib.import_module("api.btdigg_rd.routes")
    transcriber = importlib.import_module("api.btdigg_rd.voice_transcription")

    monkeypatch.setattr(routes, "selected_voice_transcription_provider", lambda: "disabled")

    def fake_transcribe(*args, **kwargs):
        raise transcriber.VoiceTranscriptionError(
            "transcriber_not_configured",
            "No hay transcriptor configurado",
            status_code=503,
            provider="disabled",
        )

    monkeypatch.setattr(routes, "transcribe_audio_file", fake_transcribe)

    response = client.post(
        "/api/voice/transcribe",
        data={
            "trace_id": "voice-no-provider",
            "lang": "es",
            "audio": (io.BytesIO(b"fake-audio"), "voice.webm", "audio/webm"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 503
    assert response.json["error_code"] == "transcriber_not_configured"
    events = _voice_events(isolated_data_dir, "voice-no-provider")
    names = [item["event"] for item in events]
    assert "voice_transcribe_request" in names
    assert "voice_transcribe_provider_start" in names
    assert "voice_transcribe_error" in names
    assert not (isolated_data_dir / "diagnostics" / "btdigg" / "jobs" / "voice-no-provider").exists()


def test_voice_transcribe_route_success_writes_voice_trace_only(client, isolated_data_dir, monkeypatch):
    routes = importlib.import_module("api.btdigg_rd.routes")
    seen = {}

    monkeypatch.setattr(routes, "selected_voice_transcription_provider", lambda: "mock")

    def fake_transcribe(path, filename="", content_type="", language="es"):
        seen["exists_during_call"] = path.exists()
        seen["filename"] = filename
        seen["content_type"] = content_type
        seen["language"] = language
        return {"text": "Gladiator II 2024", "provider": "mock"}

    monkeypatch.setattr(routes, "transcribe_audio_file", fake_transcribe)

    response = client.post(
        "/api/voice/transcribe",
        data={
            "trace_id": "voice-transcribe-ok",
            "lang": "es",
            "audio": (io.BytesIO(b"fake-audio"), "voice.webm", "audio/webm"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["text"] == "Gladiator II 2024"
    assert seen == {
        "exists_during_call": True,
        "filename": "voice.webm",
        "content_type": "audio/webm",
        "language": "es",
    }
    events = _voice_events(isolated_data_dir, "voice-transcribe-ok")
    names = [item["event"] for item in events]
    assert "voice_transcribe_request" in names
    assert "voice_transcribe_provider_start" in names
    assert "voice_transcribe_ok" in names
    assert not (isolated_data_dir / "diagnostics" / "btdigg" / "jobs" / "voice-transcribe-ok").exists()
