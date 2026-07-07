from __future__ import annotations

import threading
import time
import uuid
from copy import deepcopy
from typing import Any

from . import jobs as job_runtime
from ._settings_service import qbit_toggle_payload, save_qbit_toggle
from .config import BTDIGG_RUNTIME_DIR, DATA
from .utils import read_json, write_json


QUEUE_STATE_FILE = DATA / "search_queue.json"
QUEUE_ACTIVE = {"running", "stopping"}
QUEUE_TERMINAL = {"idle", "done", "error", "cancelled"}
ITEM_TERMINAL = {"done", "error", "cancelled"}
MAX_QUEUE_ITEMS = 40

_LOCK = threading.RLock()
_STATE: dict[str, Any] = {}
_THREAD: threading.Thread | None = None


def _now() -> str:
    return time.strftime("%H:%M:%S")


def _empty_state() -> dict[str, Any]:
    return {
        "id": "",
        "status": "idle",
        "items": [],
        "current_index": -1,
        "current_job_id": "",
        "stop_requested": False,
        "error": "",
        "started": "",
        "finished": "",
        "restore_qbit_enabled": None,
    }


def _clone_state() -> dict[str, Any]:
    with _LOCK:
        state = deepcopy(_STATE or _empty_state())
    return state


def _save_state() -> None:
    try:
        QUEUE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            write_json(QUEUE_STATE_FILE, _STATE)
    except Exception:
        pass


def _load_state() -> None:
    global _STATE
    raw = read_json(QUEUE_STATE_FILE)
    if not isinstance(raw, dict):
        _STATE = _empty_state()
        return
    state = _empty_state()
    state.update(raw)
    if str(state.get("status") or "") in QUEUE_ACTIVE:
        state["status"] = "error"
        state["error"] = "La cola quedo a medias tras reiniciar el servicio."
        state["finished"] = _now()
        for item in state.get("items") or []:
            if str(item.get("status") or "") not in ITEM_TERMINAL:
                item["status"] = "error"
                item["error"] = "Interrumpida por reinicio del servicio."
    _STATE = state


def _safe_text(value: Any, limit: int = 220) -> str:
    return str(value or "").strip()[:limit]


def _safe_mode(value: Any) -> str:
    mode = _safe_text(value, 20)
    return mode if mode in {"0", "1", "3"} else "0"


def _safe_items(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    items: list[dict[str, Any]] = []
    for raw in raw_items[:MAX_QUEUE_ITEMS]:
        if not isinstance(raw, dict):
            continue
        query = _safe_text(raw.get("query") or raw.get("title"), 220)
        if not query:
            continue
        item_id = _safe_text(raw.get("id"), 80) or uuid.uuid4().hex[:10]
        items.append(
            {
                "id": item_id,
                "query": query,
                "pages": _safe_text(raw.get("pages"), 60) or "1",
                "mode": _safe_mode(raw.get("mode")),
                "min_gb": _safe_text(raw.get("min_gb") if "min_gb" in raw else raw.get("minGb"), 40),
                "qbit_enabled": bool(raw.get("qbit_enabled", True)),
                "status": "pending",
                "job_id": "",
                "results_count": 0,
                "error": "",
                "started": "",
                "finished": "",
            }
        )
    return items


def queue_is_active() -> bool:
    with _LOCK:
        return str((_STATE or {}).get("status") or "idle") in QUEUE_ACTIVE


def queue_status() -> dict[str, Any]:
    return {"ok": True, "queue": _clone_state()}


def _read_qbit_enabled() -> bool:
    try:
        payload = qbit_toggle_payload(BTDIGG_RUNTIME_DIR)
        return bool(payload.get("enabled", True))
    except Exception:
        return True


def _write_qbit_enabled(enabled: bool) -> None:
    save_qbit_toggle(BTDIGG_RUNTIME_DIR, {"enabled": bool(enabled)})


def _mark_remaining_cancelled(start_index: int) -> None:
    with _LOCK:
        for item in (_STATE.get("items") or [])[start_index:]:
            if str(item.get("status") or "") not in ITEM_TERMINAL:
                item["status"] = "cancelled"
                item["finished"] = _now()


def _job_snapshot(job_id: str) -> dict[str, Any]:
    with job_runtime.lock:
        return deepcopy(job_runtime.jobs.get(job_id) or {})


def _run_queue(queue_id: str) -> None:
    had_errors = False
    try:
        with _LOCK:
            items = list(_STATE.get("items") or [])
        for index, item in enumerate(items):
            with _LOCK:
                if _STATE.get("id") != queue_id:
                    return
                if _STATE.get("stop_requested"):
                    _STATE["status"] = "cancelled"
                    _STATE["finished"] = _now()
                    _mark_remaining_cancelled(index)
                    _save_state()
                    return
                _STATE["current_index"] = index
                _STATE["current_job_id"] = ""
                _STATE["items"][index]["status"] = "running"
                _STATE["items"][index]["started"] = _now()
                _save_state()

            try:
                _write_qbit_enabled(bool(item.get("qbit_enabled", True)))
                payload = {
                    "module": "btdigg",
                    "action": "search",
                    "query": item.get("query") or "",
                    "pages": item.get("pages") or "1",
                    "mode": item.get("mode") or "0",
                    "min_gb": item.get("min_gb") or "",
                }
                job_id = job_runtime.start_job(payload)
                with _LOCK:
                    if _STATE.get("id") != queue_id:
                        return
                    _STATE["current_job_id"] = job_id
                    _STATE["items"][index]["job_id"] = job_id
                    _save_state()
            except Exception as exc:
                had_errors = True
                with _LOCK:
                    _STATE["items"][index]["status"] = "error"
                    _STATE["items"][index]["error"] = f"{type(exc).__name__}: {exc}"
                    _STATE["items"][index]["finished"] = _now()
                    _save_state()
                continue

            while True:
                with _LOCK:
                    stop_requested = bool(_STATE.get("stop_requested"))
                if stop_requested:
                    try:
                        job_runtime.cancel_job(job_id)
                    except Exception:
                        pass

                job = _job_snapshot(job_id)
                status = str(job.get("status") or "queued")
                if status in job_runtime.TERMINAL_STATUSES:
                    with _LOCK:
                        current_item = _STATE["items"][index]
                        current_item["status"] = status
                        current_item["finished"] = _now()
                        current_item["results_count"] = len(job.get("results") or [])
                        current_item["error"] = str(job.get("error") or "")
                        _save_state()
                    if status != "done":
                        had_errors = True
                    if stop_requested or status == "cancelled":
                        with _LOCK:
                            _STATE["status"] = "cancelled"
                            _STATE["finished"] = _now()
                            _STATE["current_job_id"] = ""
                            _mark_remaining_cancelled(index + 1)
                            _save_state()
                        return
                    break
                time.sleep(0.5)

        with _LOCK:
            if _STATE.get("id") == queue_id:
                _STATE["status"] = "error" if had_errors else "done"
                _STATE["error"] = "Una o mas busquedas terminaron con error." if had_errors else ""
                _STATE["finished"] = _now()
                _STATE["current_job_id"] = ""
                _save_state()
    finally:
        restore = None
        with _LOCK:
            if _STATE.get("id") == queue_id:
                restore = _STATE.get("restore_qbit_enabled")
        if restore is not None:
            try:
                _write_qbit_enabled(bool(restore))
            except Exception:
                pass


def start_queue(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    global _THREAD
    items = _safe_items((payload or {}).get("items"))
    if not items:
        return {"ok": False, "error": "Anade al menos una busqueda a la lista."}, 400
    if queue_is_active():
        return {"ok": False, "error": "La lista ya esta trabajando.", "queue": _clone_state()}, 409
    if job_runtime.running_job():
        return {"ok": False, "error": "BTDigg + RD ya esta trabajando.", "queue": _clone_state()}, 409

    queue_id = "queue_" + uuid.uuid4().hex[:10]
    with _LOCK:
        _STATE.clear()
        _STATE.update(
            {
                "id": queue_id,
                "status": "running",
                "items": items,
                "current_index": -1,
                "current_job_id": "",
                "stop_requested": False,
                "error": "",
                "started": _now(),
                "finished": "",
                "restore_qbit_enabled": _read_qbit_enabled(),
            }
        )
        _save_state()

    _THREAD = threading.Thread(target=_run_queue, args=(queue_id,), daemon=True)
    _THREAD.start()
    return {"ok": True, "queue": _clone_state()}, 200


def stop_queue() -> tuple[dict[str, Any], int]:
    with _LOCK:
        if str((_STATE or {}).get("status") or "idle") not in QUEUE_ACTIVE:
            return {"ok": True, "queue": _clone_state(), "already_finished": True}, 200
        _STATE["status"] = "stopping"
        _STATE["stop_requested"] = True
        current_job_id = str(_STATE.get("current_job_id") or "")
        _save_state()
    if current_job_id:
        try:
            job_runtime.cancel_job(current_job_id)
        except Exception:
            pass
    return {"ok": True, "queue": _clone_state()}, 200


def clear_queue() -> tuple[dict[str, Any], int]:
    with _LOCK:
        if str((_STATE or {}).get("status") or "idle") in QUEUE_ACTIVE:
            return {"ok": False, "error": "Deten la lista antes de limpiarla.", "queue": _clone_state()}, 409
        _STATE.clear()
        _STATE.update(_empty_state())
        _save_state()
    return {"ok": True, "queue": _clone_state()}, 200


_load_state()
