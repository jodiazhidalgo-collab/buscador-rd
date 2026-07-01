from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEXT_GUARDRAIL_FILES = [
    "app/api/btdigg_rd/routes.py",
    "app/api/btdigg_rd/send.py",
    "app/api/btdigg_rd/_settings_service.py",
    "app/api/btdigg_rd/_qbt_client.py",
    "app/api/btdigg_rd/_send_contracts.py",
    "app/api/btdigg_rd/_send_manual_flow.py",
    "app/api/btdigg_rd/_send_routing.py",
    "app/motor/btdigg/rd_turbo_pro.py",
    "app/motor/btdigg/_motor_exports.py",
    "app/motor/btdigg/_motor_qbt_probe.py",
    "app/motor/btdigg/_motor_rd_retry.py",
    "app/web/static/js/btdigg-rd.js",
    "tests/test_settings_contract.py",
    "tests/test_send_contract.py",
]
MOJIBAKE_MARKERS = ("\u00c3", "\u00c2")


def test_tanda3_touched_files_have_no_mojibake_markers():
    offenders: dict[str, list[str]] = {}

    for relative_path in TEXT_GUARDRAIL_FILES:
        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")
        lines = [
            f"{line_number}: {line.strip()}"
            for line_number, line in enumerate(text.splitlines(), start=1)
            if any(marker in line for marker in MOJIBAKE_MARKERS)
        ]
        if lines:
            offenders[relative_path] = lines

    assert offenders == {}


def test_public_critical_messages_keep_accents(client):
    job_response = client.post("/api/job", json={"module": "otro", "action": "search"})
    assert job_response.status_code == 400
    assert job_response.get_json()["error"] == "módulo no válido"

    results_response = client.get("/api/results/otro")
    assert results_response.status_code == 400
    assert results_response.get_json()["error"] == "módulo no válido"
