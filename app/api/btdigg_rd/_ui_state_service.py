from __future__ import annotations

from typing import Any

from .ui_state import load_ui_state, save_ui_state


def ui_state_payload() -> dict[str, Any]:
    return {"ok": True, "state": load_ui_state()}


def save_ui_state_payload(data: dict[str, Any]) -> tuple[dict[str, Any], int]:
    try:
        state = save_ui_state(data)
        return {"ok": True, "state": state}, 200
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo guardar estado UI: {exc}"}, 500
