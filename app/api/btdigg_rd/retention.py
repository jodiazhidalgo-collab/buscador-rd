from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import RD_TEST_DIAGNOSTICS_DIR, RD_TEST_KEEP_LAST_RUNS, RD_TEST_RETENTION_DAYS
from .utils import read_json


def _iter_rd_test_runs() -> list[Path]:
    runs: list[Path] = []
    if not RD_TEST_DIAGNOSTICS_DIR.exists():
        return runs
    for day_dir in RD_TEST_DIAGNOSTICS_DIR.iterdir():
        if not day_dir.is_dir():
            continue
        for run_dir in day_dir.iterdir():
            if run_dir.is_dir():
                runs.append(run_dir)
    return sorted(runs, key=lambda path: path.stat().st_mtime, reverse=True)


def _is_pinned(run_dir: Path) -> bool:
    for name in ("meta.json", "summary.json"):
        data = read_json(run_dir / name) or {}
        if isinstance(data, dict) and bool(data.get("pinned")):
            return True
    return False


def list_rd_test_runs(limit: int = 50) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for run_dir in _iter_rd_test_runs()[: max(1, int(limit or 50))]:
        summary = read_json(run_dir / "summary.json") or {}
        out.append(
            {
                "id": run_dir.name,
                "day": run_dir.parent.name,
                "path": str(run_dir),
                "status": summary.get("status"),
                "operation_status": summary.get("operation_status"),
                "diagnostic_status": summary.get("diagnostic_status"),
                "started_at": summary.get("started_at"),
                "updated_at": summary.get("updated_at"),
                "query": (summary.get("payload") or {}).get("query") if isinstance(summary.get("payload"), dict) else None,
                "pages": (summary.get("payload") or {}).get("pages") if isinstance(summary.get("payload"), dict) else None,
                "event_count": summary.get("event_count"),
                "pinned": bool(summary.get("pinned")),
            }
        )
    return out


def cleanup_rd_test_runs(dry_run: bool = False) -> dict[str, Any]:
    runs = _iter_rd_test_runs()
    cutoff = datetime.now() - timedelta(days=max(1, int(RD_TEST_RETENTION_DAYS or 14)))
    keep_last = max(1, int(RD_TEST_KEEP_LAST_RUNS or 200))
    keep_ids = {path.name for path in runs[:keep_last]}
    deleted: list[str] = []
    kept: list[str] = []

    for run_dir in runs:
        if run_dir.name in keep_ids or _is_pinned(run_dir):
            kept.append(run_dir.name)
            continue
        try:
            mtime = datetime.fromtimestamp(run_dir.stat().st_mtime)
        except Exception:
            mtime = datetime.now()
        if mtime >= cutoff:
            kept.append(run_dir.name)
            continue
        deleted.append(run_dir.name)
        if not dry_run:
            shutil.rmtree(run_dir, ignore_errors=True)

    return {
        "dry_run": bool(dry_run),
        "total": len(runs),
        "deleted": deleted,
        "deleted_count": len(deleted),
        "kept_count": len(kept),
        "retention_days": RD_TEST_RETENTION_DAYS,
        "keep_last_runs": RD_TEST_KEEP_LAST_RUNS,
    }
