from __future__ import annotations


def _load_queue(isolated_data_dir, reload_data_dir_modules):
    reload_data_dir_modules()
    from api.btdigg_rd import search_queue

    return search_queue


class InlineThread:
    def __init__(self, target, args=(), daemon=None):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        self.target(*self.args)


def test_queue_runs_searches_sequentially_and_restores_qbit(isolated_data_dir, reload_data_dir_modules, monkeypatch):
    queue = _load_queue(isolated_data_dir, reload_data_dir_modules)
    calls: list[dict[str, object]] = []
    qbit_values: list[bool] = []

    monkeypatch.setattr(queue.threading, "Thread", InlineThread)
    monkeypatch.setattr(queue, "_read_qbit_enabled", lambda: True)
    monkeypatch.setattr(queue, "_write_qbit_enabled", lambda enabled: qbit_values.append(bool(enabled)))

    def fake_start_job(payload):
        job_id = f"job_{len(calls) + 1}"
        calls.append(dict(payload))
        with queue.job_runtime.lock:
            queue.job_runtime.jobs[job_id] = {
                "id": job_id,
                "status": "done",
                "results": [{"title": payload["query"]}],
                "payload": dict(payload),
            }
        return job_id

    monkeypatch.setattr(queue.job_runtime, "running_job", lambda: None)
    monkeypatch.setattr(queue.job_runtime, "start_job", fake_start_job)

    payload, status = queue.start_queue(
        {
            "items": [
                {"query": "Blade Runner", "pages": "1", "mode": "3", "min_gb": "8", "qbit_enabled": True},
                {"query": "Dune", "pages": "2", "mode": "1", "min_gb": "4", "qbit_enabled": False},
            ]
        }
    )

    assert status == 200
    assert payload["ok"] is True
    assert [call["query"] for call in calls] == ["Blade Runner", "Dune"]
    assert [call["pages"] for call in calls] == ["1", "2"]
    assert [call["mode"] for call in calls] == ["3", "1"]
    assert qbit_values == [True, False, True]

    state = queue.queue_status()["queue"]
    assert state["status"] == "done"
    assert [item["status"] for item in state["items"]] == ["done", "done"]
    assert [item["job_id"] for item in state["items"]] == ["job_1", "job_2"]
    assert [item["results_count"] for item in state["items"]] == [1, 1]


def test_queue_rejects_empty_or_parallel_start(isolated_data_dir, reload_data_dir_modules, monkeypatch):
    queue = _load_queue(isolated_data_dir, reload_data_dir_modules)

    payload, status = queue.start_queue({"items": []})
    assert status == 400
    assert payload["ok"] is False

    monkeypatch.setattr(queue.job_runtime, "running_job", lambda: {"id": "active", "status": "running"})
    payload, status = queue.start_queue({"items": [{"query": "Matrix"}]})
    assert status == 409
    assert payload["ok"] is False
