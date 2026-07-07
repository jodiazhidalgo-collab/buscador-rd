from __future__ import annotations

import json
import sys
from pathlib import Path


def _load_jobs(isolated_data_dir, reload_data_dir_modules):
    reload_data_dir_modules()
    from api.btdigg_rd import jobs

    return jobs


def test_job_runtime_creates_expected_artifacts(isolated_data_dir, reload_data_dir_modules):
    jobs = _load_jobs(isolated_data_dir, reload_data_dir_modules)

    runtime = jobs.create_job_runtime("contract_job", jobs.SEARCH_SCOPE)

    assert runtime.run_dir == isolated_data_dir / "jobs" / "contract_job"
    assert runtime.exports_dir == runtime.run_dir / "exports"
    assert runtime.safeout_file == runtime.run_dir / "safeout.log"
    assert runtime.shown_file == runtime.run_dir / "shown.json"
    assert runtime.last_links_file == runtime.run_dir / "last_links.txt"
    assert runtime.ordered_links_file == runtime.run_dir / "last_links_ordenado.txt"
    assert runtime.exports_dir.is_dir()
    assert runtime.cancel_file.exists()

    cancel_payload = json.loads(runtime.cancel_file.read_text(encoding="utf-8"))
    assert cancel_payload["job_id"] == "contract_job"
    assert cancel_payload["cancel_requested"] is False


def test_start_job_public_flow_creates_queued_runtime(
    isolated_data_dir, reload_data_dir_modules, tmp_path, monkeypatch
):
    jobs = _load_jobs(isolated_data_dir, reload_data_dir_modules)
    motor_code_dir = tmp_path / "code" / "motor" / "btdigg"
    motor_runtime_dir = tmp_path / "runtime" / "motor"
    motor_code_dir.mkdir(parents=True)
    motor_runtime_dir.mkdir(parents=True)
    config_file = motor_runtime_dir / "config.json"
    config_file.write_text(
        json.dumps({"default_pages": "2", "default_mode": "0", "min_size_gb": "1"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(jobs, "BTDIGG_CODE_DIR", motor_code_dir)
    monkeypatch.setattr(jobs, "BTDIGG_RUNTIME_DIR", motor_runtime_dir)
    monkeypatch.setattr(jobs, "BTDIGG_CONFIG_FILE", config_file)
    monkeypatch.setattr(jobs, "BTDIGG_TOKEN_FILE", motor_runtime_dir / "rd_token.txt")
    monkeypatch.setattr(jobs, "sync_rd_token_for_motor", lambda: None)
    monkeypatch.setattr(jobs, "cleanup_job_runs", lambda: None)
    monkeypatch.setattr(jobs.uuid, "uuid4", lambda: type("Uuid", (), {"hex": "abcdef1234567890"})())

    thread_calls: list[tuple[object, tuple[object, ...], bool | None]] = []

    class InlineThread:
        def __init__(self, target, args=(), daemon=None):
            self.target = target
            self.args = args
            self.daemon = daemon
            thread_calls.append((target, args, daemon))

        def start(self):
            return None

    monkeypatch.setattr(jobs.threading, "Thread", InlineThread)

    job_id = jobs.start_job({"query": "matrix"})

    assert job_id == "abcdef123456"
    assert len(thread_calls) == 1
    target, args, daemon = thread_calls[0]
    assert target is jobs.run_process
    assert daemon is True
    assert args[0] == job_id
    assert args[2] == motor_code_dir
    cmd = args[1]
    assert cmd[cmd.index("--pages") + 1] == "2"
    assert cmd[cmd.index("--mode") + 1] == "0"
    assert cmd[cmd.index("--min-gb") + 1] == "1"

    with jobs.lock:
        public_job = dict(jobs.jobs[job_id])
        runtime = jobs.job_runtimes[job_id]

    assert public_job["status"] == "queued"
    assert public_job["module"] == "btdigg"
    assert public_job["action"] == "search"
    assert public_job["payload"]["query"] == "matrix"
    assert public_job["cancel_requested"] is False
    assert public_job["run_id"] == job_id
    assert runtime.run_dir == isolated_data_dir / "jobs" / job_id
    assert runtime.cancel_file.exists()


def test_start_job_uses_effective_config_when_runtime_config_is_trimmed(
    isolated_data_dir, reload_data_dir_modules, tmp_path, monkeypatch
):
    jobs = _load_jobs(isolated_data_dir, reload_data_dir_modules)
    motor_code_dir = tmp_path / "code" / "motor" / "btdigg"
    motor_runtime_dir = tmp_path / "runtime" / "motor"
    motor_code_dir.mkdir(parents=True)
    motor_runtime_dir.mkdir(parents=True)
    config_file = motor_runtime_dir / "config.json"
    config_file.write_text(
        json.dumps({"tmdb_api_token": "secret", "qbit_probe_enabled": True, "verify_wait_attempts": 1}),
        encoding="utf-8",
    )
    monkeypatch.setattr(jobs, "BTDIGG_CODE_DIR", motor_code_dir)
    monkeypatch.setattr(jobs, "BTDIGG_RUNTIME_DIR", motor_runtime_dir)
    monkeypatch.setattr(jobs, "BTDIGG_CONFIG_FILE", config_file)
    monkeypatch.setattr(jobs, "BTDIGG_TOKEN_FILE", motor_runtime_dir / "rd_token.txt")
    monkeypatch.setattr(jobs, "sync_rd_token_for_motor", lambda: None)
    monkeypatch.setattr(jobs, "cleanup_job_runs", lambda: None)
    monkeypatch.setattr(jobs.uuid, "uuid4", lambda: type("Uuid", (), {"hex": "fedcba9876543210"})())

    thread_calls: list[tuple[object, tuple[object, ...], bool | None]] = []

    class InlineThread:
        def __init__(self, target, args=(), daemon=None):
            self.target = target
            self.args = args
            self.daemon = daemon
            thread_calls.append((target, args, daemon))

        def start(self):
            return None

    monkeypatch.setattr(jobs.threading, "Thread", InlineThread)

    job_id = jobs.start_job({"query": "matrix"})

    assert job_id == "fedcba987654"
    cmd = thread_calls[0][1][1]
    assert cmd[cmd.index("--pages") + 1] == "1-3"
    assert cmd[cmd.index("--mode") + 1] == "0"
    assert cmd[cmd.index("--min-gb") + 1] == "0.0"


def test_start_rd_test_uses_effective_pages_when_runtime_config_is_trimmed(
    isolated_data_dir, reload_data_dir_modules, tmp_path, monkeypatch
):
    jobs = _load_jobs(isolated_data_dir, reload_data_dir_modules)
    motor_code_dir = tmp_path / "code" / "motor" / "btdigg"
    motor_runtime_dir = tmp_path / "runtime" / "motor"
    motor_code_dir.mkdir(parents=True)
    motor_runtime_dir.mkdir(parents=True)
    config_file = motor_runtime_dir / "config.json"
    config_file.write_text(
        json.dumps({"tmdb_api_token": "secret", "qbit_probe_enabled": True, "verify_wait_attempts": 1}),
        encoding="utf-8",
    )
    monkeypatch.setattr(jobs, "BTDIGG_CODE_DIR", motor_code_dir)
    monkeypatch.setattr(jobs, "BTDIGG_RUNTIME_DIR", motor_runtime_dir)
    monkeypatch.setattr(jobs, "BTDIGG_CONFIG_FILE", config_file)
    monkeypatch.setattr(jobs, "BTDIGG_TOKEN_FILE", motor_runtime_dir / "rd_token.txt")
    monkeypatch.setattr(jobs, "sync_rd_token_for_motor", lambda: None)
    monkeypatch.setattr(jobs, "cleanup_rd_test_runs", lambda: None)
    monkeypatch.setattr(jobs.uuid, "uuid4", lambda: type("Uuid", (), {"hex": "0123456789abcdef"})())

    thread_calls: list[tuple[object, tuple[object, ...], bool | None]] = []

    class InlineThread:
        def __init__(self, target, args=(), daemon=None):
            self.target = target
            self.args = args
            self.daemon = daemon
            thread_calls.append((target, args, daemon))

        def start(self):
            return None

    monkeypatch.setattr(jobs.threading, "Thread", InlineThread)

    run_id = jobs.start_rd_test({"query": "matrix"})

    assert run_id == "rdt_0123456789"
    cmd = thread_calls[0][1][1]
    assert cmd[cmd.index("--pages") + 1] == "1-3"


def test_successful_artifact_promotion_uses_motor_runtime_targets(
    isolated_data_dir, reload_data_dir_modules, tmp_path, monkeypatch
):
    jobs = _load_jobs(isolated_data_dir, reload_data_dir_modules)
    motor_runtime_dir = tmp_path / "runtime" / "motor"
    motor_runtime_dir.mkdir(parents=True)
    monkeypatch.setattr(jobs, "BTDIGG_RUNTIME_DIR", motor_runtime_dir)

    runtime = jobs.create_job_runtime("contract_promotion", jobs.SEARCH_SCOPE)
    runtime.shown_file.write_text('{"ok": true}', encoding="utf-8")
    (runtime.exports_dir / "one.txt").write_text("exported", encoding="utf-8")
    runtime.last_links_file.write_text("magnet:?xt=urn:btih:" + "a" * 40, encoding="utf-8")
    runtime.ordered_links_file.write_text("ordered", encoding="utf-8")

    jobs._promote_successful_artifacts(runtime)

    assert (motor_runtime_dir / "exports" / "EDITOR_MAESTRO_SHOWN.json").read_text(encoding="utf-8") == '{"ok": true}'
    assert (motor_runtime_dir / "exports" / "one.txt").read_text(encoding="utf-8") == "exported"
    assert (motor_runtime_dir / "last_links.txt").exists()
    assert (motor_runtime_dir / "last_links_ordenado.txt").read_text(encoding="utf-8") == "ordered"


def test_job_refreshes_public_diagnostics_after_terminal_state(
    isolated_data_dir, reload_data_dir_modules, monkeypatch
):
    jobs = _load_jobs(isolated_data_dir, reload_data_dir_modules)
    calls: list[dict[str, object]] = []

    def fake_export(**kwargs):
        calls.append(kwargs)
        return {"exported_files": 7, "redactions": 2}

    monkeypatch.setattr(jobs, "export_public_diagnostics", fake_export)
    jobs.jobs["job_public"] = {"id": "job_public", "log": []}

    jobs._refresh_public_diagnostics(jobs.SEARCH_SCOPE, "job_public")

    assert calls == [{"trigger": "job:search", "current_run_id": "job_public"}]
    assert "7 ficheros" in jobs.jobs["job_public"]["log"][-1]
    assert "2 secretos tapados" in jobs.jobs["job_public"]["log"][-1]
