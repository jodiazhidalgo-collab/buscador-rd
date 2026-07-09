from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ._job_artifacts import promote_successful_artifacts
from ._runtime_config_service import load_effective_runtime_config
from ._runtime_dirs import JobRuntime, RunScope, build_job_runtime, cancel_doc, write_cancel_file
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
from .config import BTDIGG_CODE_DIR, BTDIGG_CONFIG_FILE, BTDIGG_RUNTIME_DIR, BTDIGG_TOKEN_FILE, JOB_RUNS_DIR
from .history import record_qbit_no_seed_search_from_export, record_search
from .retention import cleanup_job_runs, cleanup_rd_test_runs
from .results import load_results
from .public_diagnostics import export_public_diagnostics
from .send import rd_token
from .utils import read_text


jobs: dict[str, dict[str, Any]] = {}
job_runtimes: dict[str, "JobRuntime"] = {}
lock = threading.Lock()

ACTIVE_STATUSES = {"queued", "running", "cancelling"}
TERMINAL_STATUSES = {"done", "error", "cancelled"}
CANCEL_EXIT_CODES = {0, 130, -int(getattr(signal, "SIGTERM", 15)), -int(getattr(signal, "SIGKILL", 9))}
CANCEL_GRACE_SEC = float(os.environ.get("BTDIGG_CANCEL_GRACE_SEC", "30") or 30)
CANCEL_TERMINATE_GRACE_SEC = float(os.environ.get("BTDIGG_CANCEL_TERMINATE_GRACE_SEC", "8") or 8)
CANCEL_KILL_GRACE_SEC = float(os.environ.get("BTDIGG_CANCEL_KILL_GRACE_SEC", "4") or 4)
TRUE_VALUES = {"1", "true", "yes", "on"}


SEARCH_SCOPE = RunScope(kind="job", action="search")
RD_TEST_SCOPE = RunScope(
    kind="rd_test",
    action="rd_tuning",
    load_shared_results=False,
    record_shared_history=False,
    disable_exports=True,
    disable_last_links=True,
)


def _cancel_doc(requested: bool, job_id: str, reason: str = "") -> str:
    return cancel_doc(requested, job_id, reason)


def _write_cancel_file(runtime: JobRuntime, requested: bool, reason: str = "") -> None:
    write_cancel_file(runtime, requested, reason)


def create_job_runtime(job_id: str, scope: RunScope) -> JobRuntime:
    return build_job_runtime(job_id, scope, JOB_RUNS_DIR)


def _public_runtime_flags(runtime: JobRuntime | None) -> dict[str, Any]:
    if not runtime:
        return {}
    return {
        "forced_stop": bool(runtime.forced_stop),
        "cleanup_uncertain": bool(runtime.cleanup_uncertain),
        "run_id": runtime.job_id,
    }


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
            if str(job.get("status") or "") in ACTIVE_STATUSES:
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


def _runtime_for(job_id: str) -> JobRuntime | None:
    with lock:
        return job_runtimes.get(job_id)


def _set_runtime_process(job_id: str, process: subprocess.Popen[str] | None) -> JobRuntime | None:
    with lock:
        runtime = job_runtimes.get(job_id)
        if runtime:
            runtime.process = process
        return runtime


def _mark_cancel_requested(job_id: str, runtime: JobRuntime, reason: str = "user") -> None:
    now = time.monotonic()
    with lock:
        runtime.cancel_requested_at = runtime.cancel_requested_at or now
        job = jobs.get(job_id)
        if job and str(job.get("status") or "") in {"queued", "running", "cancelling"}:
            job["status"] = "cancelling"
            job["cancel_requested"] = True
            job["forced_stop"] = bool(runtime.forced_stop)
            job["cleanup_uncertain"] = bool(runtime.cleanup_uncertain)
    _write_cancel_file(runtime, True, reason)


def cancel_job(job_id: str) -> dict[str, Any]:
    message = ""
    with lock:
        job = jobs.get(job_id)
        runtime = job_runtimes.get(job_id)
        if not job:
            return {"ok": False, "error": "job no encontrado", "status": "missing"}
        status = str(job.get("status") or "queued")
        public_job = dict(job)
        if status in {"done", "error"}:
            return {"ok": True, "already_finished": True, "status": status, "job": public_job}
        if status in {"cancelled", "cancelling"}:
            if runtime:
                runtime.cancel_requested_at = runtime.cancel_requested_at or time.monotonic()
            message = "Cancelacion ya estaba pedida."
        else:
            if runtime:
                runtime.cancel_requested_at = runtime.cancel_requested_at or time.monotonic()
            job["status"] = "cancelling"
            job["cancel_requested"] = True
            public_job = dict(job)
            message = "Deteniendo busqueda..."

    if runtime:
        _write_cancel_file(runtime, True, "user")
    if message:
        append_job(job_id, message)
    _bb_event(SEARCH_SCOPE if (job or {}).get("kind") != "rd_test" else RD_TEST_SCOPE, job_id, "JOB_CANCEL_REQUESTED", status=(job or {}).get("status"))
    with lock:
        public_job = dict(jobs.get(job_id) or public_job)
    return {"ok": True, "status": public_job.get("status"), "job": public_job}


def _process_group_signal(process: subprocess.Popen[str], sig: int) -> None:
    if os.name != "nt":
        try:
            os.killpg(os.getpgid(process.pid), sig)
            return
        except Exception:
            pass
    if sig == int(getattr(signal, "SIGKILL", 9)):
        process.kill()
    else:
        process.terminate()


def _escalate_cancel_if_needed(job_id: str, runtime: JobRuntime, scope: RunScope) -> None:
    if runtime.cancel_requested_at is None or runtime.process is None:
        return
    process = runtime.process
    if process.poll() is not None:
        return
    elapsed = time.monotonic() - runtime.cancel_requested_at
    if runtime.terminate_sent_at is None and elapsed >= CANCEL_GRACE_SEC:
        runtime.forced_stop = True
        runtime.cleanup_uncertain = True
        runtime.terminate_sent_at = time.monotonic()
        append_job(job_id, "Cancelacion lenta. Envio terminate y dejo aviso de revision.")
        _bb_event(scope, job_id, "JOB_CANCEL_TERMINATE_SENT", pid=process.pid, elapsed_sec=round(elapsed, 3))
        _process_group_signal(process, int(getattr(signal, "SIGTERM", 15)))
    elif runtime.terminate_sent_at is not None and runtime.kill_sent_at is None and (time.monotonic() - runtime.terminate_sent_at) >= CANCEL_TERMINATE_GRACE_SEC:
        runtime.forced_stop = True
        runtime.cleanup_uncertain = True
        runtime.kill_sent_at = time.monotonic()
        append_job(job_id, "Cancelacion forzada. Revisa caja negra por limpieza incierta.")
        _bb_event(scope, job_id, "JOB_CANCEL_KILL_SENT", pid=process.pid, elapsed_sec=round(elapsed, 3))
        _process_group_signal(process, int(getattr(signal, "SIGKILL", 9)))


def _promote_successful_artifacts(runtime: JobRuntime) -> None:
    promote_successful_artifacts(runtime, BTDIGG_RUNTIME_DIR)


def _refresh_public_diagnostics(scope: RunScope, job_id: str) -> None:
    if os.environ.get("BTDIGG_AUTO_PUBLIC_DIAGNOSTICS", "").strip().lower() not in TRUE_VALUES:
        return
    try:
        summary = export_public_diagnostics(trigger=f"{scope.kind}:{scope.action}", current_run_id=job_id)
        append_job(
            job_id,
            "Diagnostico publico actualizado: "
            f"{summary.get('exported_files', 0)} ficheros, "
            f"{summary.get('redactions', 0)} secretos tapados.",
        )
    except Exception as exc:
        append_job(job_id, f"Aviso diagnostico publico: {type(exc).__name__}: {exc}")


def _finalize_cancelled(job_id: str, scope: RunScope, runtime: JobRuntime, exit_code: int | None, started_monotonic: float) -> None:
    results: list[dict[str, Any]] = []
    append_job(job_id, "Cancelado.")
    _bb_finish(
        scope,
        job_id,
        "cancelled",
        exit_code=exit_code,
        forced_stop=bool(runtime.forced_stop),
        cleanup_uncertain=bool(runtime.cleanup_uncertain),
        elapsed_sec=round(time.monotonic() - started_monotonic, 3),
    )
    set_job(
        job_id,
        status="cancelled",
        exit_code=exit_code,
        finished=time.strftime("%H:%M:%S"),
        results=results,
        forced_stop=bool(runtime.forced_stop),
        cleanup_uncertain=bool(runtime.cleanup_uncertain),
    )


def _payload_or_config(payload: dict[str, Any], payload_key: str, cfg: dict[str, Any], cfg_key: str, default: Any = "") -> str:
    raw = payload.get(payload_key)
    if raw is None or str(raw).strip() == "":
        raw = cfg.get(cfg_key, default)
    return str(raw if raw is not None else "").strip()


def sync_rd_token_for_motor() -> None:
    token = rd_token()
    if not token:
        return
    token_file = BTDIGG_TOKEN_FILE
    try:
        current = token_file.read_text(encoding="utf-8", errors="ignore").strip() if token_file.exists() else ""
    except Exception:
        current = ""
    if current and not current.upper().startswith("PON_AQUI"):
        return
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token, encoding="utf-8")


def run_process(job_id: str, cmd: list[str], cwd: Path, safeout: Path | None = None, scope: RunScope = SEARCH_SCOPE) -> None:
    started_monotonic = time.monotonic()
    payload = jobs.get(job_id, {}).get("payload") or {}
    runtime = _runtime_for(job_id)
    if runtime is None:
        runtime = create_job_runtime(job_id, scope)
        with lock:
            job_runtimes[job_id] = runtime
    safeout = runtime.safeout_file
    _bb_start(scope, job_id, payload)
    _bb_command(scope, job_id, cmd, cwd)
    try:
        if runtime.cancel_requested_at is not None:
            _write_cancel_file(runtime, True, "before_start")
            append_job(job_id, "Cancelado antes de arrancar motor.")
            _bb_event(scope, job_id, "JOB_CANCELLED_BEFORE_PROCESS")
            _finalize_cancelled(job_id, scope, runtime, None, started_monotonic)
            return

        set_job(job_id, status="running", started=time.strftime("%H:%M:%S"), results=[])
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
        env["BTDIGG_RUNTIME_DIR"] = str(BTDIGG_RUNTIME_DIR)
        env["BTDIGG_CONFIG_FILE"] = str(BTDIGG_CONFIG_FILE)
        env["BTDIGG_TOKEN_FILE"] = str(BTDIGG_TOKEN_FILE)
        env["BTDIGG_CANCEL_FILE"] = str(runtime.cancel_file)
        env["BTDIGG_EXPORT_DIR"] = str(runtime.exports_dir)
        env["EDITOR_MAESTRO_SAFEOUT"] = str(runtime.safeout_file)
        env["EDITOR_MAESTRO_SHOWN_FILE"] = str(runtime.shown_file)
        env["BTDIGG_LAST_LINKS_FILE"] = str(runtime.last_links_file)
        env["EDITOR_MAESTRO_ORDERED_LINKS_FILE"] = str(runtime.ordered_links_file)
        if scope.kind == "rd_test":
            env["BTDIGG_RD_TEST_MODE"] = "1"
            env["BTDIGG_DISABLE_HISTORY"] = "1"
        if scope.disable_exports:
            env["BTDIGG_DISABLE_EXPORTS"] = "1"
        if scope.disable_last_links:
            env["BTDIGG_DISABLE_LAST_LINKS"] = "1"

        popen_kwargs: dict[str, Any] = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True

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
            **popen_kwargs,
        )
        _set_runtime_process(job_id, process)
        _bb_event(scope, job_id, "PROCESS_STARTED", pid=process.pid, run_dir=str(runtime.run_dir))

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
            if not safeout.exists():
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
            if runtime.cancel_requested_at is not None:
                _mark_cancel_requested(job_id, runtime, "supervisor")
                _escalate_cancel_if_needed(job_id, runtime, scope)
            time.sleep(0.25)

        reader.join(timeout=1.5)
        drain_stdout()
        drain_safeout()

        code = process.returncode
        _set_runtime_process(job_id, None)
        cancel_requested = runtime.cancel_requested_at is not None
        if cancel_requested:
            if runtime.forced_stop or code in CANCEL_EXIT_CODES:
                _finalize_cancelled(job_id, scope, runtime, code, started_monotonic)
                return
            append_job(job_id, f"Error tras pedir cancelacion. Codigo: {code}")
            _bb_finish(
                scope,
                job_id,
                "error",
                exit_code=code,
                cancel_requested=True,
                forced_stop=bool(runtime.forced_stop),
                cleanup_uncertain=bool(runtime.cleanup_uncertain),
                elapsed_sec=round(time.monotonic() - started_monotonic, 3),
            )
            set_job(
                job_id,
                status="error",
                exit_code=code,
                error="La cancelacion no termino limpia; revisar caja negra.",
                finished=time.strftime("%H:%M:%S"),
                results=[],
                forced_stop=bool(runtime.forced_stop),
                cleanup_uncertain=bool(runtime.cleanup_uncertain),
            )
            return

        results: list[dict[str, Any]] = []
        if code == 0:
            if scope.load_shared_results:
                _promote_successful_artifacts(runtime)
                results = load_results(runtime.shown_file, runtime.exports_dir)
            if scope.record_shared_history:
                try:
                    record_search(jobs.get(job_id, {}).get("payload") or {}, results)
                    record_qbit_no_seed_search_from_export(jobs.get(job_id, {}).get("payload") or {}, runtime.exports_dir)
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
            append_job(job_id, f"Error del motor. Codigo: {code}")
            _bb_finish(
                scope,
                job_id,
                "error",
                exit_code=code,
                results_count=0,
                elapsed_sec=round(time.monotonic() - started_monotonic, 3),
            )
        set_job(
            job_id,
            status="done" if code == 0 else "error",
            exit_code=code,
            finished=time.strftime("%H:%M:%S"),
            results=results,
            **_public_runtime_flags(runtime),
        )
    except Exception as exc:
        _set_runtime_process(job_id, None)
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
        _refresh_public_diagnostics(scope, job_id)


def start_job(payload: dict[str, Any]) -> str:
    sync_rd_token_for_motor()
    try:
        cleanup_job_runs()
    except Exception:
        pass
    job_id = uuid.uuid4().hex[:12]
    runtime = create_job_runtime(job_id, SEARCH_SCOPE)
    with lock:
        job_runtimes[job_id] = runtime
        jobs[job_id] = {
            "id": job_id,
            "kind": "job",
            "module": "btdigg",
            "action": "search",
            "status": "queued",
            "payload": dict(payload),
            "log": [],
            "results": [],
            "cancel_requested": False,
            **_public_runtime_flags(runtime),
        }

    cfg = load_effective_runtime_config(BTDIGG_CONFIG_FILE)

    query = str(payload.get("query") or "").strip()
    pages = _payload_or_config(payload, "pages", cfg, "default_pages", "1")
    mode = _payload_or_config(payload, "mode", cfg, "default_mode", "0")
    mode = str(mode).strip()
    if mode not in {"0", "1", "3"}:
        mode = "0"
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

    thread = threading.Thread(target=run_process, args=(job_id, cmd, BTDIGG_CODE_DIR, runtime.safeout_file, SEARCH_SCOPE), daemon=True)
    thread.start()
    return job_id


def start_rd_test(payload: dict[str, Any]) -> str:
    sync_rd_token_for_motor()
    try:
        cleanup_rd_test_runs()
    except Exception:
        pass
    run_id = "rdt_" + uuid.uuid4().hex[:10]
    runtime = create_job_runtime(run_id, RD_TEST_SCOPE)
    test_payload = dict(payload)
    test_payload["module"] = "btdigg"
    test_payload["action"] = "rd_tuning"
    test_payload["mode"] = "0"
    test_payload["min_gb"] = "0"
    with lock:
        job_runtimes[run_id] = runtime
        jobs[run_id] = {
            "id": run_id,
            "kind": "rd_test",
            "module": "btdigg",
            "action": "rd_tuning",
            "status": "queued",
            "payload": test_payload,
            "log": [],
            "results": [],
            "cancel_requested": False,
            **_public_runtime_flags(runtime),
        }

    cfg = load_effective_runtime_config(BTDIGG_CONFIG_FILE)

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

    thread = threading.Thread(target=run_process, args=(run_id, cmd, BTDIGG_CODE_DIR, runtime.safeout_file, RD_TEST_SCOPE), daemon=True)
    thread.start()
    return run_id
