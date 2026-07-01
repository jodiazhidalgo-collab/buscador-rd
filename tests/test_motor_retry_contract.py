from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest


MOTOR_FILE = Path(__file__).resolve().parents[1] / "app" / "motor" / "btdigg" / "rd_turbo_pro.py"


def load_motor_module():
    module_name = f"rd_turbo_pro_retry_contract_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MOTOR_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RetryContext:
    def __init__(self):
        self.counts = {}
        self.slots = SlotTracker()

    def bump(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1


class SlotTracker:
    def __init__(self):
        self.refreshes = 0

    def refresh(self, force=False):
        self.refreshes += 1
        self.force = force


def rd_error(motor, status=503, error_code=None, error="temp"):
    payload = {"error": error}
    if error_code is not None:
        payload["error_code"] = error_code
    return motor.RDAPIError("GET", "/x", status, "body", payload)


def test_rd_call_with_retry_retries_429(monkeypatch):
    motor = load_motor_module()
    calls = []

    def fake_rd_api(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise rd_error(motor, status=429, error_code=34, error="too_many_requests")
        return {"ok": True}

    ctx = RetryContext()
    monkeypatch.setattr(motor, "rd_api", fake_rd_api)
    monkeypatch.setattr(motor, "_rd_retry_sleep", lambda *args, **kwargs: 0.01)
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)

    assert motor.rd_call_with_retry("GET", "/x", "token", attempts=2, retry_context=ctx) == {"ok": True}
    assert len(calls) == 2
    assert ctx.counts["rd_retry_429_count"] == 1


def test_rd_call_with_retry_retries_temporary_exception(monkeypatch):
    motor = load_motor_module()
    calls = []

    def fake_rd_api(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise TimeoutError("read operation timed out")
        return {"ok": True}

    ctx = RetryContext()
    monkeypatch.setattr(motor, "rd_api", fake_rd_api)
    monkeypatch.setattr(motor, "_rd_retry_sleep", lambda *args, **kwargs: 0.01)
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)

    assert motor.rd_call_with_retry("GET", "/x", "token", attempts=2, retry_context=ctx) == {"ok": True}
    assert len(calls) == 2
    assert ctx.counts["rd_retry_temp_count"] == 1


def test_rd_call_with_retry_does_not_retry_infringing(monkeypatch):
    motor = load_motor_module()
    calls = []

    def fake_rd_api(*args, **kwargs):
        calls.append(args)
        raise rd_error(motor, status=451, error_code=35, error="infringing_file")

    ctx = RetryContext()
    monkeypatch.setattr(motor, "rd_api", fake_rd_api)
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)

    with pytest.raises(motor.RDAPIError):
        motor.rd_call_with_retry("GET", "/x", "token", attempts=3, retry_context=ctx)

    assert len(calls) == 1
    assert ctx.counts["rd_error_terminal_count"] == 1


def test_rd_call_with_retry_refreshes_slots_on_limit_21(monkeypatch):
    motor = load_motor_module()
    calls = []

    def fake_rd_api(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise rd_error(motor, status=403, error_code=21, error="active_limit")
        return {"ok": True}

    ctx = RetryContext()
    monkeypatch.setattr(motor, "rd_api", fake_rd_api)
    monkeypatch.setattr(motor, "sleep_interruptible", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)

    assert motor.rd_call_with_retry("GET", "/x", "token", attempts=2, retry_context=ctx) == {"ok": True}
    assert len(calls) == 2
    assert ctx.counts["rd_retry_21_count"] == 1
    assert ctx.slots.refreshes == 1
    assert ctx.slots.force is True


def test_rd_call_with_retry_raises_last_exhausted_error(monkeypatch):
    motor = load_motor_module()
    calls = []

    def fake_rd_api(*args, **kwargs):
        calls.append(args)
        raise rd_error(motor, status=503, error="maintenance")

    monkeypatch.setattr(motor, "rd_api", fake_rd_api)
    monkeypatch.setattr(motor, "_rd_retry_sleep", lambda *args, **kwargs: 0.01)
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)

    with pytest.raises(motor.RDAPIError) as exc:
        motor.rd_call_with_retry("GET", "/x", "token", attempts=2)

    assert exc.value.status_code == 503
    assert len(calls) == 2
