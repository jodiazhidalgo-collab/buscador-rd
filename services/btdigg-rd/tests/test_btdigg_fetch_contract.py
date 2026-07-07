from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_motor_module():
    module_path = Path(__file__).resolve().parents[1] / "app" / "motor" / "btdigg" / "rd_turbo_pro.py"
    spec = importlib.util.spec_from_file_location("_btdigg_motor_contract", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("No se pudo cargar rd_turbo_pro.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_btdigg_block_reason_detects_real_failures(isolated_data_dir, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(isolated_data_dir))
    motor = _load_motor_module()

    assert "429" in motor._btdigg_block_reason("Too Many Requests", status_code=429)
    assert "Chromium" in motor._btdigg_block_reason(stderr="Trace/breakpoint trap")
    assert "DNS" in motor._btdigg_block_reason("Pagina prohibida bloqueadaseccionsegunda.cultura.gob.es")
    assert "CAPTCHA" in motor._btdigg_block_reason("One more step Please complete the security check captcha")
