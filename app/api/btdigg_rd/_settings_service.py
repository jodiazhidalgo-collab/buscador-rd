from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._runtime_config_service import PUBLIC_RUNTIME_DEFAULTS, load_effective_runtime_config


SETTINGS_SCHEMA: list[dict[str, Any]] = [
    {"key": "default_mode", "label": "Modo por defecto", "help": "0 sin filtro, 1 calidad, 2 castellano preferente, 3 castellano obligatorio.", "type": "select", "options": [{"value": 0, "label": "Sin filtro"}, {"value": 1, "label": "Calidad pura"}, {"value": 2, "label": "Castellano preferente"}, {"value": 3, "label": "Castellano obligatorio"}]},
    {"key": "default_pages", "label": "Páginas BTDigg", "help": "Páginas normales a revisar. Ejemplo: 1, 1-3 o 1-5.", "type": "text"},
    {"key": "safe_max_pages_when_zero", "label": "Límite si páginas = 0", "help": "Tope de seguridad cuando se pide revisar todo.", "type": "int", "min": 1, "max": 200},
    {"key": "max_results_to_show", "label": "Resultados en pantalla", "help": "Cuántos resultados enseña como máximo.", "type": "int", "min": 1, "max": 300},
    {"key": "min_size_gb", "label": "Tamaño mínimo GB", "help": "Descarta cosas demasiado pequeñas.", "type": "float", "min": 0, "max": 500},
    {"key": "max_size_gb", "label": "Tamaño máximo GB", "help": "Descarta cosas demasiado grandes.", "type": "float", "min": 1, "max": 1000},
    {"key": "request_timeout_sec", "label": "Espera web/API", "help": "Tiempo máximo por llamadas web/RD/qBit.", "recommendation": "20-40", "type": "int", "min": 3, "max": 300},
    {"key": "delay_between_btdigg_pages_sec", "label": "Pausa entre páginas", "help": "Equilibrio para ir más rápido sin castigar BTDigg.", "recommendation": "3-7", "type": "float", "min": 0, "max": 60},
    {"key": "pack_query_match_min_ratio", "label": "Coincidencia de paquete", "help": "Elige el archivo bueno dentro de un pack.", "recommendation": "0,50-0,65", "type": "float", "min": 0, "max": 1},
    {"key": "verify_max_candidates", "label": "Candidatos RD", "help": "Real-Debrid busca más, pero tarda más.", "recommendation": "30-60", "type": "int", "min": 1, "max": 300},
    {"key": "verify_wait_sec", "label": "Espera por intento RD", "help": "Segundos de espera interna de RD. Los intentos quedan fijos por dentro en 1.", "recommendation": "0,25-1", "type": "float", "min": 0, "max": 30},
    {"key": "qbit_probe_max_candidates", "label": "Candidatos qBittorrent", "help": "Cuántos candidatos prueba qBittorrent.", "recommendation": "20-40", "type": "int", "min": 1, "max": 300},
    {"key": "qbit_probe_wait_sec", "label": "Espera qBittorrent", "help": "Segundos para que qBittorrent detecte metadatos.", "recommendation": "20-35", "type": "int", "min": 3, "max": 300},
    {"key": "qbit_same_file_min_ratio", "label": "Exigencia coincidencia", "help": "Si bajas, mete más basura. Si subes, pierde resultados buenos.", "recommendation": "0,80-0,90", "type": "float", "min": 0, "max": 1},
    {"key": "qbit_probe_parallel_workers", "label": "Tandas qBittorrent", "help": "Cuántos candidatos qBit prueba a la vez. Más alto = más rápido, pero mete más carga y puede ensuciar pruebas.", "recommendation": "3-5", "type": "int", "min": 1, "max": 12},
    {"key": "hide_non_working_results", "label": "Ocultar resultados muertos", "help": "Si está activado, no enseña enlaces que no parecen funcionar.", "type": "bool"},
    {"key": "rd_addmagnet_min_interval_sec", "label": "Meter magnet", "help": "Ritmo mínimo entre addMagnet de Real-Debrid.", "recommendation": "1,0", "type": "float", "min": 0, "max": 10, "section": "rd", "group": "Ritmo RD"},
    {"key": "rd_selectfiles_min_interval_sec", "label": "Seleccionar archivos", "help": "Ritmo mínimo entre selectFiles.", "recommendation": "0,75", "type": "float", "min": 0, "max": 10, "section": "rd", "group": "Ritmo RD"},
    {"key": "rd_delete_min_interval_sec", "label": "Borrar", "help": "Ritmo mínimo entre borrados RD.", "recommendation": "0,65", "type": "float", "min": 0, "max": 10, "section": "rd", "group": "Ritmo RD"},
    {"key": "rd_info_min_interval_sec", "label": "Mirar info", "help": "Ritmo mínimo entre lecturas de info.", "recommendation": "0,10", "type": "float", "min": 0, "max": 10, "section": "rd", "group": "Ritmo RD"},
    {"key": "rd_addmagnet_max_concurrent", "label": "Magnet a la vez", "help": "Concurrencia máxima de addMagnet.", "recommendation": "1", "type": "int", "min": 1, "max": 10, "section": "rd", "group": "RD a la vez"},
    {"key": "rd_selectfiles_max_concurrent", "label": "Selección a la vez", "help": "Concurrencia máxima de selectFiles.", "recommendation": "1", "type": "int", "min": 1, "max": 10, "section": "rd", "group": "RD a la vez"},
    {"key": "rd_delete_max_concurrent", "label": "Borrados a la vez", "help": "Concurrencia máxima de borrados.", "recommendation": "1", "type": "int", "min": 1, "max": 10, "section": "rd", "group": "RD a la vez"},
    {"key": "rd_info_max_concurrent", "label": "Info a la vez", "help": "Concurrencia máxima mirando info.", "recommendation": "4", "type": "int", "min": 1, "max": 20, "section": "rd", "group": "RD a la vez"},
    {"key": "rd_api_429_cooldown_sec", "label": "Pausa 429", "help": "Pausa global corta cuando RD responde 429 aislado.", "recommendation": "3", "type": "float", "min": 0, "max": 60, "section": "rd", "group": "Enfado RD / 429"},
    {"key": "rd_endpoint_429_cooldown_sec", "label": "Pausa endpoint", "help": "Pausa local del endpoint que recibe 429.", "recommendation": "6", "type": "float", "min": 0, "max": 60, "section": "rd", "group": "Enfado RD / 429"},
    {"key": "rd_429_retry_attempts", "label": "Reintentos 429", "help": "Reintentos para 429 sin convertirlo en error falso.", "recommendation": "6", "type": "int", "min": 1, "max": 30, "section": "rd", "group": "Enfado RD / 429"},
    {"key": "rd_api_rate_limit_per_min", "label": "Límite API RD/min", "help": "Máximo de llamadas RD por minuto.", "recommendation": "235", "type": "int", "min": 1, "max": 250, "section": "rd", "group": "RD avanzado"},
    {"key": "rd_api_rate_limit_burst", "label": "Ráfaga API RD", "help": "Máximo de llamadas RD por segundo.", "recommendation": "4", "type": "int", "min": 1, "max": 20, "section": "rd", "group": "RD avanzado"},
]


def force_internal_settings(cfg: dict[str, Any]) -> None:
    cfg["verify_wait_attempts"] = 1


def coerce_setting_value(raw: Any, spec: dict[str, Any]) -> Any:
    typ = spec.get("type")
    if typ == "bool":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("1", "true", "si", "sí", "yes", "on")
    if typ == "int":
        value = int(float(str(raw).replace(",", ".").strip()))
    elif typ == "float":
        value = float(str(raw).replace(",", ".").strip())
    elif typ == "select":
        value = int(float(str(raw).replace(",", ".").strip()))
    else:
        return str(raw).strip()

    if "min" in spec and value < spec["min"]:
        raise ValueError(f"{spec['label']} está por debajo del mínimo")
    if "max" in spec and value > spec["max"]:
        raise ValueError(f"{spec['label']} supera el máximo")
    if typ == "select":
        allowed = [option.get("value") for option in spec.get("options", [])]
        if value not in allowed:
            raise ValueError(f"{spec['label']} no es una opción válida")
    return value


def public_settings_payload(cfg: dict[str, Any]) -> dict[str, Any]:
    force_internal_settings(cfg)
    fields = []
    for spec in SETTINGS_SCHEMA:
        item = dict(spec)
        default = PUBLIC_RUNTIME_DEFAULTS.get(spec["key"], "")
        value = cfg.get(spec["key"], default)
        if value is None:
            value = default
        item["default"] = default
        item["value"] = value
        fields.append(item)
    return {"module": "btdigg", "title": "BTDigg + RD", "fields": fields}


def load_settings_payload(btdigg_dir: Path) -> dict[str, Any]:
    cfg = load_effective_runtime_config(btdigg_dir / "config.json")
    return {"ok": True, "settings": {"btdigg": public_settings_payload(cfg)}}


def save_settings_values(btdigg_dir: Path, data: dict[str, Any]) -> tuple[dict[str, Any], int]:
    values = data.get("values") or {}
    if str(data.get("module") or "btdigg") != "btdigg":
        return {"ok": False, "error": "módulo no válido"}, 400
    if not isinstance(values, dict):
        return {"ok": False, "error": "valores no válidos"}, 400

    path = btdigg_dir / "config.json"
    cfg = load_effective_runtime_config(path)
    force_internal_settings(cfg)

    specs = {item["key"]: item for item in SETTINGS_SCHEMA}
    changed: list[str] = []
    try:
        for key, raw in values.items():
            if key not in specs:
                continue
            new_value = coerce_setting_value(raw, specs[key])
            if cfg.get(key) != new_value:
                cfg[key] = new_value
                changed.append(key)
        force_internal_settings(cfg)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}, 400

    try:
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo guardar: {exc}"}, 500

    return {"ok": True, "changed": changed, "message": "Ajustes guardados"}, 200


def qbit_toggle_payload(btdigg_dir: Path) -> dict[str, Any]:
    cfg = load_effective_runtime_config(btdigg_dir / "config.json")
    return {"ok": True, "enabled": bool(cfg.get("qbit_probe_enabled", True))}


def save_qbit_toggle(btdigg_dir: Path, data: dict[str, Any]) -> tuple[dict[str, Any], int]:
    raw = data.get("enabled")
    if isinstance(raw, str):
        enabled = raw.strip().lower() in ("1", "true", "si", "sí", "yes", "on")
    else:
        enabled = bool(raw)

    path = btdigg_dir / "config.json"
    cfg = load_effective_runtime_config(path)
    if bool(cfg.get("qbit_probe_enabled", True)) == enabled:
        return {"ok": True, "enabled": enabled, "changed": False}, 200

    try:
        cfg["qbit_probe_enabled"] = enabled
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo guardar qBit: {exc}"}, 500

    return {"ok": True, "enabled": enabled, "changed": True}, 200
