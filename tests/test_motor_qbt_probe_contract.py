from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest


MOTOR_FILE = Path(__file__).resolve().parents[1] / "app" / "motor" / "btdigg" / "rd_turbo_pro.py"


def load_motor_module():
    module_name = f"rd_turbo_pro_qbt_contract_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MOTOR_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_result(motor, h="a" * 40):
    return motor.Result(
        title="Probe candidate",
        magnet=f"magnet:?xt=urn:btih:{h}",
        hash=h,
        size_gb=1.0,
    )


def test_qbt_probe_one_without_hash_or_magnet_sets_contract_status(monkeypatch):
    motor = load_motor_module()
    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)

    result = motor.qbt_probe_one(object(), motor.Result(title="sin magnet"))

    assert result.qbt_status == "QBT_SIN_HASH"
    assert result.qbt_reason == "Sin hash/magnet para probar en qBittorrent"


def test_qbt_probe_one_keeps_existing_torrent_status(monkeypatch):
    motor = load_motor_module()
    result = make_result(motor)
    info = {
        "progress": 1,
        "size": 2 * 1024**3,
        "amount_left": 0,
        "num_seeds": 5,
        "num_leechs": 1,
        "dlspeed": 0,
        "state": "uploading",
    }
    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "qbt_info_by_hash", lambda opener, h: info)
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)

    checked = motor.qbt_probe_one(object(), result, idx=1, total=1)

    assert checked.qbt_was_existing is True
    assert checked.qbt_status == "QBT_OK"
    assert checked.qbt_seeds == 5
    assert checked.qbt_size_gb == 2.0
    assert checked.qbt_reason.startswith("Ya estaba en qBittorrent.")


def test_qbt_probe_one_add_ok_and_poll_ok(monkeypatch):
    motor = load_motor_module()
    result = make_result(motor)
    info_calls = []
    requests = []

    def fake_info(opener, h):
        info_calls.append(h)
        if len(info_calls) == 1:
            return None
        return {
            "progress": 0.25,
            "size": 3 * 1024**3,
            "amount_left": 2 * 1024**3,
            "num_seeds": 2,
            "num_leechs": 3,
            "dlspeed": 1024 * 1024,
            "state": "downloading",
        }

    def fake_request(opener, method, path, data=None, timeout=None):
        requests.append((method, path, data))
        return "Ok."

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "sleep_interruptible", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "qbt_info_by_hash", fake_info)
    monkeypatch.setattr(motor, "qbt_request", fake_request)
    monkeypatch.setattr(motor, "qbt_delete_hash", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)
    motor.CONFIG["qbit_delete_probe_after"] = False

    checked = motor.qbt_probe_one(object(), result, idx=1, total=1)

    assert requests[0][0] == "POST"
    assert requests[0][1] == "/api/v2/torrents/add"
    assert checked.qbt_status == "QBT_VIVO"
    assert checked.qbt_speed_bps == 1024 * 1024


def test_qbt_probe_one_add_error_sets_contract_status(monkeypatch):
    motor = load_motor_module()
    result = make_result(motor)

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "qbt_info_by_hash", lambda opener, h: None)
    monkeypatch.setattr(motor, "qbt_request", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("add failed")))
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)

    checked = motor.qbt_probe_one(object(), result, idx=1, total=1)

    assert checked.qbt_status == "QBT_ADD_ERROR"
    assert "add failed" in checked.qbt_reason


def test_qbt_probe_one_cancellation_deletes_added_probe(monkeypatch):
    motor = load_motor_module()
    result = make_result(motor)
    deleted = []

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "qbt_info_by_hash", lambda opener, h: None)
    monkeypatch.setattr(motor, "qbt_request", lambda *args, **kwargs: "Ok.")
    monkeypatch.setattr(motor, "sleep_interruptible", lambda *args, **kwargs: (_ for _ in ()).throw(motor.UserCancelled("stop")))
    monkeypatch.setattr(motor, "qbt_delete_hash", lambda opener, h, why: deleted.append((h, why)))
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)
    motor.CONFIG["qbit_delete_probe_after"] = True

    with pytest.raises(motor.UserCancelled):
        motor.qbt_probe_one(object(), result, idx=1, total=1)

    assert deleted == [(result.hash, "cancel_probe")]
