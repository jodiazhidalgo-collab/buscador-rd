from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Any

from .config import UI_STATE_FILE
from .utils import read_json, write_json


_LOCK = RLock()
_VIEWS = {"main", "settings", "history", "queue"}


def _safe_text(value: Any, limit: int = 220) -> str:
    return str(value or "").strip()[:limit]


def _safe_bool_map(value: Any, limit: int = 120) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, bool] = {}
    for key, raw in list(value.items())[:limit]:
        key_text = _safe_text(key, 180)
        if key_text:
            out[key_text] = bool(raw)
    return out


def _safe_state(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    state = raw.get("state") if isinstance(raw.get("state"), dict) else raw
    view = _safe_text(state.get("view"), 20)
    if view not in _VIEWS:
        view = "main"
    form = state.get("form") if isinstance(state.get("form"), dict) else {}
    history = state.get("history_open") if isinstance(state.get("history_open"), dict) else {}
    sort = state.get("result_sort") if isinstance(state.get("result_sort"), dict) else {}
    client_id = _safe_text(raw.get("client_id") or state.get("client_id"), 80)
    try:
        client_updated_at = int(float(raw.get("client_updated_at") or state.get("client_updated_at") or 0))
    except Exception:
        client_updated_at = 0
    return {
        "version": 1,
        "view": view,
        "form": {
            "query": _safe_text(form.get("query"), 220),
            "pages": _safe_text(form.get("pages"), 60),
            "mode": _safe_text(form.get("mode"), 20),
            "minGb": _safe_text(form.get("minGb"), 40),
        },
        "history_open": {
            "days": _safe_bool_map(history.get("days")),
            "searches": _safe_bool_map(history.get("searches")),
        },
        "result_sort": {
            "key": _safe_text(sort.get("key"), 40) or "index",
            "dir": "desc" if _safe_text(sort.get("dir"), 10) == "desc" else "asc",
        },
        "client_id": client_id,
        "client_updated_at": client_updated_at,
        "updated_at": _safe_text(raw.get("updated_at") or state.get("updated_at"), 80),
        "server_updated_at": int(float(raw.get("server_updated_at") or state.get("server_updated_at") or 0)),
    }


def load_ui_state() -> dict[str, Any]:
    with _LOCK:
        return _safe_state(read_json(UI_STATE_FILE) or {})


def save_ui_state(payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        state = _safe_state(payload)
        state["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        state["server_updated_at"] = int(datetime.now().timestamp() * 1000)
        write_json(UI_STATE_FILE, state)
        return state
