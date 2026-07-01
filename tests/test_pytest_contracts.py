from __future__ import annotations

import json


def test_client_smoke_root_and_active_job(client):
    response = client.get("/")
    assert response.status_code == 200

    active_response = client.get("/api/job/active")
    assert active_response.status_code == 200

    payload = active_response.get_json()
    assert payload["ok"] is True
    assert payload["active"] is False


def test_cancel_missing_job_contract(client):
    response = client.post("/api/job/pytest_missing_job/cancel")
    assert response.status_code == 404

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["status"] == "missing"


def test_create_job_runtime_uses_isolated_data_dir(
    isolated_data_dir, reload_data_dir_modules
):
    reload_data_dir_modules()

    from api.btdigg_rd import jobs

    runtime = jobs.create_job_runtime("pytest_contract_runtime", jobs.SEARCH_SCOPE)

    assert runtime.run_dir == isolated_data_dir / "jobs" / "pytest_contract_runtime"
    assert runtime.cancel_file == runtime.run_dir / "cancel.json"
    assert runtime.cancel_file.exists()

    cancel_payload = json.loads(runtime.cancel_file.read_text(encoding="utf-8"))
    assert cancel_payload["job_id"] == "pytest_contract_runtime"
    assert cancel_payload["cancel_requested"] is False
