from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib import request
from urllib.error import HTTPError

import pytest


pytestmark = pytest.mark.live

BASE_URL = os.environ.get("BTDIGG_LIVE_BASE_URL", "http://localhost:9007").rstrip("/")
DEFAULT_QUERY = os.environ.get("BTDIGG_LIVE_QUERY", "John Wick 2014")
DEFAULT_PAGES = os.environ.get("BTDIGG_LIVE_PAGES", "1")
DEFAULT_MODE = os.environ.get("BTDIGG_LIVE_MODE", "0")
DEFAULT_MIN_GB = os.environ.get("BTDIGG_LIVE_MIN_GB", "0")
JOB_TIMEOUT_SEC = int(os.environ.get("BTDIGG_LIVE_JOB_TIMEOUT_SEC", "700") or 700)
QUEUE_TIMEOUT_SEC = int(os.environ.get("BTDIGG_LIVE_QUEUE_TIMEOUT_SEC", "1200") or 1200)

REPO_ROOT = Path(__file__).resolve().parents[3]
DIAGNOSTICS_ROOT = Path(
    os.environ.get(
        "BTDIGG_LIVE_DIAGNOSTICS_ROOT",
        str(REPO_ROOT / "config" / "btdigg-rd" / "data" / "diagnostics" / "btdigg" / "jobs"),
    )
)


def _live_enabled() -> bool:
    return str(os.environ.get("BTDIGG_LIVE", "")).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _json_request(method: str, path: str, payload: dict | None = None, timeout: int = 30) -> dict:
    data = None
    headers = {"accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    req = request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"body": body}
        raise AssertionError(f"{method} {path} devolvio HTTP {exc.code}: {payload}") from exc


def _wait_job(job_id: str, timeout_sec: int = JOB_TIMEOUT_SEC) -> dict:
    deadline = time.monotonic() + timeout_sec
    last = {}
    while time.monotonic() < deadline:
        last = _json_request("GET", f"/api/job/{job_id}", timeout=20)
        job = last.get("job") or {}
        if str(job.get("status") or "") in {"done", "error", "cancelled"}:
            return job
        time.sleep(2)
    raise AssertionError(f"job {job_id} no termino a tiempo: {last}")


def _wait_queue(timeout_sec: int = QUEUE_TIMEOUT_SEC) -> dict:
    deadline = time.monotonic() + timeout_sec
    last = {}
    while time.monotonic() < deadline:
        last = _json_request("GET", "/api/search-queue", timeout=20)
        queue = last.get("queue") or {}
        if str(queue.get("status") or "") in {"idle", "done", "error", "cancelled"}:
            return queue
        time.sleep(2)
    raise AssertionError(f"la lista no termino a tiempo: {last}")


def _summary_for_job(job_id: str) -> dict:
    hits = list(DIAGNOSTICS_ROOT.glob(f"*/{job_id}/summary.json"))
    assert hits, f"no encuentro summary.json de caja negra para job {job_id} en {DIAGNOSTICS_ROOT}"
    return json.loads(hits[0].read_text(encoding="utf-8"))


def _assert_blackbox_search_ok(job_id: str, *, visible_results: int) -> dict:
    summary = _summary_for_job(job_id)
    assert summary.get("operation_status") == "ok", summary
    assert int(summary.get("btdigg_found") or 0) > 0, summary
    assert int((summary.get("working_filter") or {}).get("after") or 0) == visible_results, summary
    return summary


def _qbit_enabled() -> bool:
    return bool((_json_request("GET", "/api/qbit-toggle", timeout=20)).get("enabled", True))


def _set_qbit_enabled(enabled: bool) -> None:
    payload = _json_request("POST", "/api/qbit-toggle", {"enabled": bool(enabled)}, timeout=20)
    assert payload.get("ok") is True, payload


def _assert_no_active_job_or_skip() -> None:
    active = _json_request("GET", "/api/job/active", timeout=20)
    if active.get("active"):
        pytest.skip(f"hay un job activo en el servicio real: {active}")
    queue = _json_request("GET", "/api/search-queue", timeout=20).get("queue") or {}
    if str(queue.get("status") or "") in {"running", "stopping"}:
        pytest.skip(f"hay una lista activa en el servicio real: {queue}")


def _clear_idle_queue() -> None:
    payload = _json_request("POST", "/api/search-queue/clear", timeout=20)
    assert payload.get("ok") is True, payload


def _start_real_search(query: str, *, pages: str = DEFAULT_PAGES, mode: str = DEFAULT_MODE, min_gb: str = DEFAULT_MIN_GB) -> dict:
    started = _json_request(
        "POST",
        "/api/job",
        {
            "module": "btdigg",
            "action": "search",
            "query": query,
            "pages": pages,
            "mode": mode,
            "min_gb": min_gb,
        },
    )
    assert started["ok"] is True
    job = _wait_job(started["job_id"])
    assert job["status"] == "done", job
    visible_results = len(job.get("results") or [])
    assert visible_results > 0, job
    _assert_blackbox_search_ok(started["job_id"], visible_results=visible_results)
    return job


def test_live_web_search_returns_real_results_with_qbit_off_and_on():
    if not _live_enabled():
        pytest.skip("activa BTDIGG_LIVE=1 para prueba real")

    _assert_no_active_job_or_skip()
    old_qbit = _qbit_enabled()
    try:
        for enabled in (False, True):
            _set_qbit_enabled(enabled)
            job = _start_real_search(DEFAULT_QUERY)
            assert job["payload"]["query"] == DEFAULT_QUERY
    finally:
        _set_qbit_enabled(old_qbit)


def test_live_search_queue_runs_real_web_jobs_sequentially_and_restores_qbit():
    if not _live_enabled():
        pytest.skip("activa BTDIGG_LIVE=1 para prueba real")

    _assert_no_active_job_or_skip()
    old_qbit = _qbit_enabled()
    _clear_idle_queue()
    try:
        started = _json_request(
            "POST",
            "/api/search-queue",
            {
                "items": [
                    {
                        "id": "live-qbit-off",
                        "query": DEFAULT_QUERY,
                        "pages": DEFAULT_PAGES,
                        "mode": DEFAULT_MODE,
                        "min_gb": DEFAULT_MIN_GB,
                        "qbit_enabled": False,
                    },
                    {
                        "id": "live-qbit-on",
                        "query": DEFAULT_QUERY,
                        "pages": DEFAULT_PAGES,
                        "mode": DEFAULT_MODE,
                        "min_gb": DEFAULT_MIN_GB,
                        "qbit_enabled": True,
                    },
                ]
            },
        )
        assert started.get("ok") is True, started
        queue = _wait_queue()
        assert queue["status"] == "done", queue
        items = queue.get("items") or []
        assert [item.get("status") for item in items] == ["done", "done"], queue
        assert all((item.get("job_id") or "") for item in items), queue
        assert all(int(item.get("results_count") or 0) > 0 for item in items), queue

        for item in items:
            _assert_blackbox_search_ok(str(item["job_id"]), visible_results=int(item.get("results_count") or 0))
    finally:
        _set_qbit_enabled(old_qbit)
        _clear_idle_queue()
