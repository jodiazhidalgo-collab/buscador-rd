from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .blackbox import (
    finish_job as blackbox_finish_job,
    finish_rd_test as blackbox_finish_rd_test,
    job_command as blackbox_job_command,
    job_error as blackbox_job_error,
    job_event as blackbox_job_event,
    job_events_file as blackbox_job_events_file,
    rd_test_command as blackbox_rd_test_command,
    rd_test_error as blackbox_rd_test_error,
    rd_test_event as blackbox_rd_test_event,
    rd_test_events_file as blackbox_rd_test_events_file,
    start_job as blackbox_start_job,
    start_rd_test as blackbox_start_rd_test,
)
from .config import BTDIGG_DIR, SAFEOUT_FILE
from .history import record_search
from .retention import cleanup_rd_test_runs
from .results import load_results
from .send import rd_token
from .utils import read_json, read_text


jobs: dict[str, dict[str, Any]] = {}
lock = threading.Lock()


@dataclass(frozen=True)
class RunScope:
    kind: str
    action: str
    load_shared_results: bool = True
    record_shared_history: bool = True
    disable_exports: bool = False
    disable_last_links: bool = False


SEARCH_SCOPE = RunScope(kind="job", action="search")
RD_TEST_SCOPE = RunScope(
    kind="rd_test",
    action="rd_tuning",
    load_shared_results=False,
    record_shared_history=False,
    disable_exports=True,
    disable_last_links=True,
)


def append_job(job_id: str, line: str) -> None:
    line = str(line or "").rstrip()
    if not line:
        return
    with lock:
        job = jobs.get(job_id)
        if not job:
            return
        job.setdefault("log", []).append(line)
        if len(job["log"]) > 600:
            job["log"] = job["log"][-600:]


def set_job(job_id: str, **values: Any) -> None:
    with lock:
        if job_id in jobs:
            jobs[job_id].update(values)


def running_job() -> dict[str, Any] | None:
    with lock:
        for job in jobs.values():
            if str(job.get("status") or "") in ("queued", "running"):
                return dict(job)
    return None


def _bb_start(scope: RunScope, job_id: str, payload: dict[str, Any]) -> None:
    if scope.kind == "rd_test":
        blackbox_start_rd_test(job_id, scope.action, payload, {"started_by": "web", "scope": scope.kind})
    else:
        blackbox_start_job(job_id, scope.action, payload)


def _bb_command(scope: RunScope, job_id: str, cmd: list[str], cwd: Path) -> None:
    if scope.kind == "rd_test":
        blackbox_rd_test_command(job_id, cmd, cwd)
    else:
        blackbox_job_command(job_id, cmd, cwd)


def _bb_event(scope: RunScope, job_id: str, event: str, **data: Any) -> None:
    if scope.kind == "rd_test":
        blackbox_rd_test_event(job_id, event, **data)
    else:
        blackbox_job_event(job_id, event, **data)


def _bb_finish(scope: RunScope, job_id: str, status: str, **data: Any) -> None:
    if scope.kind == "rd_test":
        blackbox_finish_rd_test(job_id, status, **data)
    else:
        blackbox_finish_job(job_id, status, **data)


def _bb_error(scope: RunScope, job_id: str, event: str, error: Any, **data: Any) -> None:
    if scope.kind == "rd_test":
        blackbox_rd_test_error(job_id, event, error, **data)
    else:
        blackbox_job_error(job_id, event, error, **data)


def _bb_events_file(scope: RunScope, job_id: str) -> Path:
    if scope.kind == "rd_test":
        return blackbox_rd_test_events_file(job_id)
    return blackbox_job_events_file(job_id)


def _payload_or_config(payload: dict[str, Any], payload_key: str, cfg: dict[str, Any], cfg_key: str, default: Any = "") -> str:
    raw = payload.get(payload_key)
    if raw is None or str(raw).strip() == "":
        raw = cfg.get(cfg_key, default)
    return str(raw if raw is not None else "").strip()


def sync_rd_token_for_motor() -> None:
    token = rd_token()
    if not token:
        return
    token_file = BTDIGG_DIR / "rd_token.txt"
    try:
        current = token_file.read_text(encoding="utf-8", errors="ignore").strip() if token_file.exists() else ""
    except Exception:
        current = ""
    if current and not current.upper().startswith("PON_AQUI"):
        return
    token_file.write_text(token, encoding="utf-8")


def run_process(job_id: str, cmd: list[str], cwd: Path, safeout: Path | None = None, scope: RunScope = SEARCH_SCOPE) -> None:
    started_monotonic = time.monotonic()
    payload = jobs.get(job_id, {}).get("payload") or {}
    _bb_start(scope, job_id, payload)
    _bb_command(scope, job_id, cmd, cwd)
    set_job(job_id, status="running", started=time.strftime("%H:%M:%S"), results=[])
    try:
        if safeout:
            try:
                safeout.write_text("", encoding="utf-8")
            except Exception:
                pass

        append_job(job_id, "Arrancando motor...")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["BTDIGG_BLACKBOX_KIND"] = scope.kind
        env["BTDIGG_BLACKBOX_TRACE_ID"] = job_id
        env["BTDIGG_BLACKBOX_JOB_ID"] = job_id
        env["BTDIGG_BLACKBOX_EVENTS"] = str(_bb_events_file(scope, job_id))
        if scope.kind == "rd_test":
            env["BTDIGG_RD_TEST_MODE"] = "1"
            env["BTDIGG_DISABLE_HISTORY"] = "1"
        if scope.disable_exports:
            env["BTDIGG_DISABLE_EXPORTS"] = "1"
        if scope.disable_last_links:
            env["BTDIGG_DISABLE_LAST_LINKS"] = "1"
        if safeout:
            env["EDITOR_MAESTRO_SAFEOUT"] = str(safeout)

        process = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        _bb_event(scope, job_id, "PROCESS_STARTED", pid=process.pid)

        stdout_q: queue.Queue[str] = queue.Queue()

        def stdout_reader() -> None:
            try:
                if not process.stdout:
                    return
                for line in process.stdout:
                    stdout_q.put(line)
            except Exception as exc:
                stdout_q.put(f"ERROR leyendo salida del motor: {exc}\n")

        reader = threading.Thread(target=stdout_reader, daemon=True)
        reader.start()
        last_safe_len = 0

        def drain_stdout() -> None:
            while True:
                try:
                    line = stdout_q.get_nowait()
                except queue.Empty:
                    break
                append_job(job_id, line)

        def drain_safeout() -> None:
            nonlocal last_safe_len
            if not safeout or not safeout.exists():
                return
            text = read_text(safeout)
            if len(text) <= last_safe_len:
                return
            new_text = text[last_safe_len:]
            last_safe_len = len(text)
            for line in new_text.splitlines():
                append_job(job_id, line)

        while process.poll() is None:
            drain_stdout()
            drain_safeout()
            time.sleep(0.25)

        reader.join(timeout=1.5)
        drain_stdout()
        drain_safeout()

        code = process.returncode
        results = load_results() if scope.load_shared_results else []
        if code == 0:
            if scope.record_shared_history:
                try:
                    record_search(jobs.get(job_id, {}).get("payload") or {}, results)
                except Exception as exc:
                    append_job(job_id, f"Aviso historial: {type(exc).__name__}: {exc}")
                    _bb_error(scope, job_id, "HISTORY_RECORD_ERROR", exc)
            if scope.load_shared_results:
                append_job(job_id, f"Listo. Resultados cargados: {len(results)}")
            else:
                append_job(job_id, "Listo. Prueba RD guardada sin tocar resultados ni historial.")
            _bb_finish(
                scope,
                job_id,
                "ok",
                exit_code=code,
                results_count=len(results),
                elapsed_sec=round(time.monotonic() - started_monotonic, 3),
            )
        else:
            append_job(job_id, f"Error del motor. Código: {code}")
        if code != 0:
            _bb_finish(
                scope,
                job_id,
                "error",
                exit_code=code,
                results_count=len(results),
                elapsed_sec=round(time.monotonic() - started_monotonic, 3),
            )
        set_job(
            job_id,
            status="done" if code == 0 else "error",
            exit_code=code,
            finished=time.strftime("%H:%M:%S"),
            results=results,
        )
    except Exception as exc:
        append_job(job_id, f"ERROR WEB: {type(exc).__name__}: {exc}")
        _bb_error(
            scope,
            job_id,
            "WEB_JOB_EXCEPTION",
            exc,
            elapsed_sec=round(time.monotonic() - started_monotonic, 3),
        )
        set_job(job_id, status="error", error=f"{type(exc).__name__}: {exc}", finished=time.strftime("%H:%M:%S"), results=[])
    finally:
        if safeout:
            try:
                safeout.unlink(missing_ok=True)
            except Exception:
                pass


def start_job(payload: dict[str, Any]) -> str:
    sync_rd_token_for_motor()
    job_id = uuid.uuid4().hex[:12]
    with lock:
        jobs[job_id] = {"id": job_id, "kind": "job", "module": "btdigg", "action": "search", "status": "queued", "payload": dict(payload), "log": [], "results": []}

    cfg = read_json(BTDIGG_DIR / "config.json") or {}
    if not isinstance(cfg, dict):
        cfg = {}

    query = str(payload.get("query") or "").strip()
    pages = _payload_or_config(payload, "pages", cfg, "default_pages", "1")
    mode = _payload_or_config(payload, "mode", cfg, "default_mode", "0")
    min_gb = _payload_or_config(payload, "min_gb", cfg, "min_size_gb", "")
    cmd = [
        sys.executable,
        "-u",
        "rd_turbo_editor_maestro.py",
        "--search",
        "--query",
        query,
        "--pages",
        pages,
        "--mode",
        mode,
        "--min-gb",
        min_gb,
    ]

    thread = threading.Thread(target=run_process, args=(job_id, cmd, BTDIGG_DIR, SAFEOUT_FILE, SEARCH_SCOPE), daemon=True)
    thread.start()
    return job_id


def start_rd_test(payload: dict[str, Any]) -> str:
    sync_rd_token_for_motor()
    try:
        cleanup_rd_test_runs()
    except Exception:
        pass
    run_id = "rdt_" + uuid.uuid4().hex[:10]
    test_payload = dict(payload)
    test_payload["module"] = "btdigg"
    test_payload["action"] = "rd_tuning"
    test_payload["mode"] = "0"
    test_payload["min_gb"] = "0"
    with lock:
        jobs[run_id] = {"id": run_id, "kind": "rd_test", "module": "btdigg", "action": "rd_tuning", "status": "queued", "payload": test_payload, "log": [], "results": []}

    cfg = read_json(BTDIGG_DIR / "config.json") or {}
    if not isinstance(cfg, dict):
        cfg = {}

    query = str(test_payload.get("query") or "").strip()
    pages = _payload_or_config(test_payload, "pages", cfg, "default_pages", "1")
    cmd = [
        sys.executable,
        "-u",
        "rd_turbo_editor_maestro.py",
        "--search",
        "--query",
        query,
        "--pages",
        pages,
        "--mode",
        "0",
        "--min-gb",
        "0",
    ]

    thread = threading.Thread(target=run_process, args=(run_id, cmd, BTDIGG_DIR, SAFEOUT_FILE, RD_TEST_SCOPE), daemon=True)
    thread.start()
    return run_id
