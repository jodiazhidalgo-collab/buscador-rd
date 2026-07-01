from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path


MOTOR_FILE = Path(__file__).resolve().parents[1] / "app" / "motor" / "btdigg" / "rd_turbo_pro.py"


def load_motor_module():
    module_name = f"rd_turbo_pro_characterization_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MOTOR_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_motor_tanda4_candidate_functions_are_present():
    motor = load_motor_module()

    for name in (
        "export_results",
        "prepare_results",
        "rd_call_with_retry",
        "rd_check_availability",
        "qbt_probe_one",
    ):
        assert callable(getattr(motor, name))


def test_motor_pure_parsers_keep_observed_contract():
    motor = load_motor_module()
    original_config = dict(motor.CONFIG)
    try:
        motor.CONFIG["safe_max_pages_when_zero"] = 3
        motor.CONFIG["default_pages"] = "2"

        assert motor.parse_pages("1") == [1]
        assert motor.parse_pages("1-3") == [1, 2, 3]
        assert motor.parse_pages("3-1") == [1, 2, 3]
        assert motor.parse_pages("0") == [1, 2, 3]
        assert motor.parse_pages("no-valido") == [1, 2]
        assert motor.parse_size_gb("1.5 GB") == 1.5
        assert motor.parse_size_gb("700 MB") == 700 / 1024
        assert motor.parse_size_gb("2 TB") == 2048
        assert motor.magnet_hash("magnet:?xt=urn:btih:" + "A" * 40 + "&dn=x") == "a" * 40
    finally:
        motor.CONFIG.clear()
        motor.CONFIG.update(original_config)


def test_export_results_writes_expected_artifacts_in_isolated_dir(tmp_path):
    motor = load_motor_module()
    original_config = dict(motor.CONFIG)
    original_export_dir = motor.EXPORT_DIR
    original_cancel_file = motor.CANCEL_FILE
    original_diag = motor.diag
    original_last_qbit_extras = getattr(motor, "LAST_QBIT_EXTRAS", None)
    original_last_rd_temp_errors = getattr(motor, "LAST_RD_TEMP_ERRORS", None)
    try:
        motor.CONFIG["write_exports"] = True
        motor.CONFIG["max_results_to_show"] = 1
        motor.EXPORT_DIR = tmp_path / "exports"
        motor.CANCEL_FILE = None
        motor.diag = lambda *args, **kwargs: None
        motor.LAST_QBIT_EXTRAS = []
        motor.LAST_RD_TEMP_ERRORS = []

        result = motor.Result(
            title="Pelicula aislada",
            magnet="magnet:?xt=urn:btih:" + "d" * 40,
            hash="d" * 40,
            size_gb=1.25,
            score=42,
            rd_status="RD_OK",
            rd_links=1,
            reason="ok",
        )

        motor.export_results([result], shown=[result])

        all_json = motor.EXPORT_DIR / "ULTIMOS_RESULTADOS.json"
        top_txt = motor.EXPORT_DIR / "ULTIMO_TOP.txt"
        assert all_json.exists()
        assert top_txt.exists()

        rows = json.loads(all_json.read_text(encoding="utf-8"))
        assert rows[0]["title"] == "Pelicula aislada"
        assert rows[0]["hash"] == "d" * 40
        assert rows[0]["rd_status"] == "RD_OK"
        assert "RD Turbo Pro" in top_txt.read_text(encoding="utf-8")
    finally:
        motor.CONFIG.clear()
        motor.CONFIG.update(original_config)
        motor.EXPORT_DIR = original_export_dir
        motor.CANCEL_FILE = original_cancel_file
        motor.diag = original_diag
        motor.LAST_QBIT_EXTRAS = original_last_qbit_extras
        motor.LAST_RD_TEMP_ERRORS = original_last_rd_temp_errors
