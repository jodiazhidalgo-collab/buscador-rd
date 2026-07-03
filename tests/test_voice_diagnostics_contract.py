from __future__ import annotations

import importlib
import json


def test_voice_blackbox_uses_separate_collection(isolated_data_dir, reload_data_dir_modules):
    reload_data_dir_modules("api.btdigg_rd.voice_diagnostics")
    blackbox = importlib.import_module("api.btdigg_rd.blackbox")

    blackbox.voice_event("voice-contract", "voice_click", is_secure_context=True)

    folder = isolated_data_dir / "diagnostics" / "btdigg" / "voice"
    matches = list(folder.glob("*/voice-contract/events.jsonl"))
    assert len(matches) == 1
    assert not (isolated_data_dir / "diagnostics" / "btdigg" / "jobs" / "voice-contract").exists()

    record = json.loads(matches[0].read_text(encoding="utf-8").splitlines()[0])
    assert record["trace_kind"] == "voice"
    assert record["event"] == "voice_click"
    assert record["phase"] == "voice"


def test_voice_diagnostic_route_writes_compact_trace(client, isolated_data_dir):
    response = client.post(
        "/api/voice/diagnostic",
        json={
            "trace_id": "voice-route-contract",
            "event": "voice_error",
            "data": {
                "error": "not-allowed",
                "transcript_preview": "x" * 500,
                "ignored_key": "must_not_be_saved",
            },
        },
        headers={"User-Agent": "pytest-mobile"},
    )

    assert response.status_code == 200
    assert response.json["ok"] is True

    events = list((isolated_data_dir / "diagnostics" / "btdigg" / "voice").glob("*/voice-route-contract/events.jsonl"))
    assert len(events) == 1
    record = json.loads(events[0].read_text(encoding="utf-8").splitlines()[0])
    assert record["event"] == "voice_error"
    assert record["data"]["error"] == "not-allowed"
    assert "ignored_key" not in record["data"]
    assert record["data"]["user_agent"] == "pytest-mobile"
    assert len(record["data"]["transcript_preview"]) < 260


def test_voice_diagnostic_route_rejects_unknown_event(client):
    response = client.post(
        "/api/voice/diagnostic",
        json={"trace_id": "voice-bad", "event": "rd_verify_batch_end", "data": {}},
    )

    assert response.status_code == 400
    assert response.json["ok"] is False


def test_voice_diagnostic_accepts_insecure_context(client, isolated_data_dir):
    response = client.post(
        "/api/voice/diagnostic",
        json={
            "trace_id": "voice-insecure",
            "event": "voice_insecure_context",
            "data": {
                "error": "insecure-context",
                "is_secure_context": False,
                "message": "secure_context_required",
            },
        },
    )

    assert response.status_code == 200
    assert response.json["ok"] is True

    summary = list((isolated_data_dir / "diagnostics" / "btdigg" / "voice").glob("*/voice-insecure/summary.json"))
    assert len(summary) == 1
    data = json.loads(summary[0].read_text(encoding="utf-8"))
    assert data["status"] == "error"
    assert data["counts"]["warn"] == 1
    assert data["last_event"] == "voice_insecure_context"
