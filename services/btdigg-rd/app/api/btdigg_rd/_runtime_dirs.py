from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunScope:
    kind: str
    action: str
    load_shared_results: bool = True
    record_shared_history: bool = True
    disable_exports: bool = False
    disable_last_links: bool = False


@dataclass
class JobRuntime:
    job_id: str
    scope_kind: str
    run_dir: Path
    cancel_file: Path
    safeout_file: Path
    shown_file: Path
    exports_dir: Path
    last_links_file: Path
    ordered_links_file: Path
    process: subprocess.Popen[str] | None = None
    cancel_requested_at: float | None = None
    forced_stop: bool = False
    cleanup_uncertain: bool = False
    terminate_sent_at: float | None = None
    kill_sent_at: float | None = None


def cancel_doc(requested: bool, job_id: str, reason: str = "") -> str:
    return (
        "{\n"
        f'  "job_id": "{job_id}",\n'
        f'  "cancel_requested": {"true" if requested else "false"},\n'
        f'  "reason": "{str(reason or "").replace(chr(34), chr(39))}",\n'
        f'  "updated_at": {time.time():.3f}\n'
        "}\n"
    )


def write_cancel_file(runtime: JobRuntime, requested: bool, reason: str = "") -> None:
    runtime.cancel_file.parent.mkdir(parents=True, exist_ok=True)
    runtime.cancel_file.write_text(cancel_doc(requested, runtime.job_id, reason), encoding="utf-8")


def build_job_runtime(job_id: str, scope: RunScope, job_runs_dir: Path) -> JobRuntime:
    run_dir = job_runs_dir / job_id
    exports_dir = run_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    runtime = JobRuntime(
        job_id=job_id,
        scope_kind=scope.kind,
        run_dir=run_dir,
        cancel_file=run_dir / "cancel.json",
        safeout_file=run_dir / "safeout.log",
        shown_file=run_dir / "shown.json",
        exports_dir=exports_dir,
        last_links_file=run_dir / "last_links.txt",
        ordered_links_file=run_dir / "last_links_ordenado.txt",
    )
    write_cancel_file(runtime, False, "created")
    return runtime
