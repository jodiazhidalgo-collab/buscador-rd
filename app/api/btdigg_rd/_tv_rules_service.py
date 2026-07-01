from __future__ import annotations

from typing import Any

from .classification import classify_title, default_tv_rules, load_tv_rules, reset_tv_rules, save_tv_rules


def tv_rules_payload() -> dict[str, Any]:
    return {"ok": True, "rules": load_tv_rules(), "defaults": default_tv_rules()}


def save_tv_rules_payload(data: dict[str, Any]) -> tuple[dict[str, Any], int]:
    try:
        rules = save_tv_rules(data.get("rules") if isinstance(data.get("rules"), dict) else data)
        return {"ok": True, "rules": rules, "message": "Reglas guardadas"}, 200
    except Exception as exc:
        return {"ok": False, "error": f"No se pudieron guardar reglas: {exc}"}, 500


def reset_tv_rules_payload() -> tuple[dict[str, Any], int]:
    try:
        rules = reset_tv_rules()
        return {"ok": True, "rules": rules, "message": "Reglas restauradas"}, 200
    except Exception as exc:
        return {"ok": False, "error": f"No se pudieron restaurar reglas: {exc}"}, 500


def classify_tv_rules_payload(data: dict[str, Any]) -> dict[str, Any]:
    title = str(data.get("title") or "").strip()
    rules = data.get("rules") if isinstance(data.get("rules"), dict) else None
    result = classify_title(title, rules, fallback="movies")
    labels = {"tv": "Series / TV", "movies": "Peliculas", "manual": "Manual"}
    return {
        "ok": True,
        "title": title,
        "destination": result.get("destination"),
        "label": labels.get(str(result.get("destination")), "Peliculas"),
        "matched_type": result.get("matched_type") or "",
        "matched_rule": result.get("matched_rule") or "",
    }
