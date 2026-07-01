from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path


MOTOR_FILE = Path(__file__).resolve().parents[1] / "app" / "motor" / "btdigg" / "rd_turbo_pro.py"


def load_motor_module():
    module_name = f"rd_turbo_pro_exports_contract_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MOTOR_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_results_writes_json_top_qbit_and_rd_temp_files(tmp_path, monkeypatch):
    motor = load_motor_module()
    export_dir = tmp_path / "exports"
    title = "Pel\u00edcula con acento"
    rd_ok = motor.Result(
        title=title,
        magnet="magnet:?xt=urn:btih:" + "b" * 40,
        hash="b" * 40,
        size_gb=2.25,
        score=77,
        rd_status="RD_OK",
        rd_links=1,
        selected_file_ids="1,2",
        selected_file_name="video.mkv",
        selected_file_size_gb=2.25,
        reason="correcto",
    )
    qbit = motor.Result(
        title="Solo qbit",
        magnet="magnet:?xt=urn:btih:" + "c" * 40,
        hash="c" * 40,
        size_gb=1.5,
        score=55,
        rd_status="NO_CACHE",
        qbt_status="QBT_VIVO",
        qbt_reason="con vida",
        qbt_seeds=4,
        qbt_peers=2,
    )
    rd_temp = motor.Result(
        title="RD temporal",
        magnet="magnet:?xt=urn:btih:" + "d" * 40,
        hash="d" * 40,
        size_gb=3.0,
        score=44,
        rd_status="RD_ERROR_TEMPORAL",
        reason="timeout",
    )

    monkeypatch.setattr(motor, "EXPORT_DIR", export_dir)
    monkeypatch.setattr(motor, "CANCEL_FILE", None)
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "log", lambda *args, **kwargs: None)
    motor.CONFIG["write_exports"] = True
    motor.CONFIG["max_results_to_show"] = 2
    motor.LAST_QBIT_EXTRAS = [qbit]
    motor.LAST_RD_TEMP_ERRORS = [rd_temp]

    motor.export_results([rd_ok, qbit, rd_temp], shown=[rd_ok, qbit])

    all_json = export_dir / "ULTIMOS_RESULTADOS.json"
    top_txt = export_dir / "ULTIMO_TOP.txt"
    qbit_txt = export_dir / "ULTIMO_QBIT_VIVOS.txt"
    rd_temp_txt = export_dir / "ULTIMO_RD_TEMPORAL.txt"

    assert all_json.exists()
    assert top_txt.exists()
    assert qbit_txt.exists()
    assert rd_temp_txt.exists()

    rows = json.loads(all_json.read_text(encoding="utf-8"))
    assert rows[0]["title"] == title
    assert rows[0]["hash"] == "b" * 40
    assert rows[0]["rd_status"] == "RD_OK"
    assert rows[0]["selected_file_ids"] == "1,2"
    assert rows[1]["qbt_status"] == "QBT_VIVO"
    assert title.encode("utf-8") in all_json.read_bytes()
    assert "RD Turbo Pro" in top_txt.read_text(encoding="utf-8")
    assert "Solo qbit" in qbit_txt.read_text(encoding="utf-8")
    assert "RD temporal" in rd_temp_txt.read_text(encoding="utf-8")
