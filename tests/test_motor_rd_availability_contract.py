from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path


MOTOR_FILE = Path(__file__).resolve().parents[1] / "app" / "motor" / "btdigg" / "rd_turbo_pro.py"


def load_motor_module():
    module_name = f"rd_turbo_pro_availability_contract_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MOTOR_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_result(motor, h="e" * 40):
    return motor.Result(
        title="RD candidate",
        magnet=f"magnet:?xt=urn:btih:{h}",
        hash=h,
        size_gb=2.0,
    )


def test_rd_check_availability_without_token_marks_candidates(monkeypatch):
    motor = load_motor_module()
    result = make_result(motor)
    events = []

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "validate_direct_links", lambda rows: None)
    monkeypatch.setattr(motor, "materialize_torrent_candidates", lambda rows: None)
    monkeypatch.setattr(motor, "diag", lambda event, **kwargs: events.append((event, kwargs)))

    checked = motor.rd_check_availability([result], token="")

    assert checked == [result]
    assert result.rd_status == "SIN_TOKEN"
    assert result.reason == "No hay token en rd_token.txt"
    assert ("rd_check_skipped", {"reason": "sin_token", "total": 1}) in events


def test_rd_check_availability_uses_addmagnet_when_instant_cached_disabled(monkeypatch):
    motor = load_motor_module()
    result = make_result(motor)
    events = []
    batches = []

    def fake_batch(rows, token, maxv):
        batches.append(([r.hash for r in rows], token, maxv))
        rows[0].rd_status = "RD_OK"
        rows[0].reason = "verified"
        return {"RD_OK": 1}

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "validate_direct_links", lambda rows: None)
    monkeypatch.setattr(motor, "materialize_torrent_candidates", lambda rows: None)
    monkeypatch.setattr(motor, "rd_token_healthcheck", lambda token: (True, ""))
    monkeypatch.setattr(motor, "rd_instant_disabled_cached", lambda: True)
    monkeypatch.setattr(motor, "rd_verify_addmagnet_batch", fake_batch)
    monkeypatch.setattr(motor, "sleep_interruptible", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "diag", lambda event, **kwargs: events.append((event, kwargs)))
    motor.CONFIG["verify_candidates_when_api_off"] = True
    motor.CONFIG["verify_max_candidates"] = 30

    checked = motor.rd_check_availability([result], token="token")

    assert checked[0].rd_status == "RD_OK"
    assert batches == [([result.hash], "token", 1)]
    summary = [payload for event, payload in events if event == "rd_check_summary"][-1]
    assert summary["RD_OK"] == 1
    assert summary["total"] == 1


def test_rd_check_availability_uses_addmagnet_when_instant_endpoint_disabled(monkeypatch):
    motor = load_motor_module()
    result = make_result(motor)
    batches = []
    disabled_errors = []

    def fake_batch(rows, token, maxv):
        batches.append(maxv)
        rows[0].rd_status = "RD_OK"
        return {"RD_OK": 1}

    def fake_rd_call(*args, **kwargs):
        raise motor.RDAPIError("GET", "/torrents/instantAvailability/hash", 403, "disabled", {"error_code": 37, "error": "disabled_endpoint"})

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "validate_direct_links", lambda rows: None)
    monkeypatch.setattr(motor, "materialize_torrent_candidates", lambda rows: None)
    monkeypatch.setattr(motor, "rd_token_healthcheck", lambda token: (True, ""))
    monkeypatch.setattr(motor, "rd_instant_disabled_cached", lambda: False)
    monkeypatch.setattr(motor, "rd_call_with_retry", fake_rd_call)
    monkeypatch.setattr(motor, "rd_mark_instant_disabled", lambda error_text: disabled_errors.append(error_text))
    monkeypatch.setattr(motor, "rd_verify_addmagnet_batch", fake_batch)
    monkeypatch.setattr(motor, "sleep_interruptible", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)
    motor.CONFIG["verify_candidates_when_api_off"] = True
    motor.CONFIG["verify_max_candidates"] = 30

    checked = motor.rd_check_availability([result], token="token")

    assert checked[0].rd_status == "RD_OK"
    assert batches == [1]
    assert disabled_errors
