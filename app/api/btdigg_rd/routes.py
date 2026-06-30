from __future__ import annotations

import json
import time
import zipfile
from typing import Any

from flask import Blueprint, Response, jsonify, request, stream_with_context

from .blackbox import trace_folder
from .classification import classify_title, default_tv_rules, load_tv_rules, reset_tv_rules, save_tv_rules
from .config import BTDIGG_DIR, RD_TEST_EXPORTS_DIR, ensure_runtime_dirs
from .history import load_history
from .jobs import jobs, lock, running_job, start_job, start_rd_test
from .retention import cleanup_rd_test_runs, list_rd_test_runs
from .results import load_results
from .rd_follow import build_rd_event_detail, build_rd_follow
from .send import api_rdt_send
from .utils import read_json


bp = Blueprint("btdigg_rd", __name__)


@bp.post("/api/job")
def api_job():
    data = request.get_json(force=True, silent=True) or {}
    module = str(data.get("module") or "btdigg")
    action = str(data.get("action") or "search")
    if module != "btdigg" or action != "search":
        return jsonify({"ok": False, "error": "módulo no válido"}), 400

    current = running_job()
    if current:
        return jsonify({
            "ok": False,
            "error": "BTDigg + RD ya está trabajando. Espera a que termine antes de repetir.",
            "running_job_id": current.get("id"),
            "running_kind": current.get("kind") or "job",
            "module": "btdigg",
        }), 409

    job_id = start_job(data)
    return jsonify({"ok": True, "job_id": job_id})


@bp.post("/api/rd-test/job")
def api_rd_test_job():
    data = request.get_json(force=True, silent=True) or {}
    query = str(data.get("query") or "").strip()
    if not query:
        return jsonify({"ok": False, "error": "falta título"}), 400

    current = running_job()
    if current:
        return jsonify({
            "ok": False,
            "error": "BTDigg + RD ya está trabajando. Espera a que termine antes de repetir.",
            "running_job_id": current.get("id"),
            "running_kind": current.get("kind") or "job",
            "module": "btdigg",
        }), 409

    run_id = start_rd_test(data)
    return jsonify({"ok": True, "job_id": run_id, "run_id": run_id, "trace_kind": "rd_test"})


@bp.get("/api/job/active")
def api_job_active():
    current = running_job()
    if current:
        return jsonify({"ok": True, "active": True, "job": current})
    return jsonify({"ok": True, "active": False})


@bp.get("/api/rd-test/job/active")
def api_rd_test_job_active():
    current = running_job()
    if current and current.get("kind") == "rd_test":
        return jsonify({"ok": True, "active": True, "job": current})
    return jsonify({"ok": True, "active": False})


@bp.get("/api/job/<job_id>")
def api_job_status(job_id: str):
    with lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "job no encontrado"}), 404
        return jsonify({"ok": True, "job": job})


@bp.get("/api/job/<job_id>/rd-follow")
def api_job_rd_follow(job_id: str):
    try:
        after = int(str(request.args.get("after") or "0").strip() or "0")
    except Exception:
        after = 0
    with lock:
        job = jobs.get(job_id)
        job_status = str((job or {}).get("status") or "")
    try:
        follow = build_rd_follow(job_id, after=after)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"No se pudo leer seguimiento RD: {exc}"}), 500
    if not job and not follow.get("has_diagnostics"):
        return jsonify({"ok": False, "error": "job no encontrado"}), 404
    follow["job_status"] = job_status or follow.get("summary", {}).get("operation_status") or ""
    return jsonify({"ok": True, "follow": follow})


@bp.get("/api/rd-test/job/<run_id>")
def api_rd_test_job_status(run_id: str):
    with lock:
        job = jobs.get(run_id)
        if job:
            return jsonify({"ok": True, "job": job})
    folder = trace_folder("rd_test", run_id)
    if not folder.exists():
        return jsonify({"ok": False, "error": "prueba RD no encontrada"}), 404
    return jsonify({"ok": True, "job": {"id": run_id, "kind": "rd_test", "status": "done"}})


@bp.get("/api/rd-test/job/<run_id>/follow")
def api_rd_test_job_follow(run_id: str):
    try:
        after = int(str(request.args.get("after") or "0").strip() or "0")
    except Exception:
        after = 0
    with lock:
        job = jobs.get(run_id)
        job_status = str((job or {}).get("status") or "")
    try:
        follow = build_rd_follow(run_id, after=after, kind="rd_test")
    except Exception as exc:
        return jsonify({"ok": False, "error": f"No se pudo leer seguimiento RD: {exc}"}), 500
    if not job and not follow.get("has_diagnostics"):
        return jsonify({"ok": False, "error": "prueba RD no encontrada"}), 404
    follow["job_status"] = job_status or follow.get("summary", {}).get("operation_status") or ""
    return jsonify({"ok": True, "follow": follow})


@bp.get("/api/rd-test/job/<run_id>/event/<event_id>")
def api_rd_test_event_detail(run_id: str, event_id: str):
    detail = build_rd_event_detail(run_id, event_id, kind="rd_test")
    if not detail:
        return jsonify({"ok": False, "error": "evento no encontrado"}), 404
    return jsonify({"ok": True, "detail": detail})


@bp.get("/api/rd-test/runs")
def api_rd_test_runs():
    try:
        limit = int(str(request.args.get("limit") or "50").strip() or "50")
    except Exception:
        limit = 50
    return jsonify({"ok": True, "runs": list_rd_test_runs(limit=limit)})


@bp.post("/api/rd-test/cleanup")
def api_rd_test_cleanup():
    data = request.get_json(force=True, silent=True) or {}
    result = cleanup_rd_test_runs(dry_run=bool(data.get("dry_run")))
    return jsonify({"ok": True, "cleanup": result})


@bp.post("/api/rd-test/job/<run_id>/export")
def api_rd_test_export(run_id: str):
    folder = trace_folder("rd_test", run_id)
    if not folder.exists():
        return jsonify({"ok": False, "error": "prueba RD no encontrada"}), 404
    RD_TEST_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = RD_TEST_EXPORTS_DIR / f"{run_id}.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in ("summary.json", "meta.json", "events.jsonl", "warnings.jsonl", "errors.jsonl", "timeline.md"):
                path = folder / name
                if path.exists():
                    zf.write(path, arcname=name)
            follow = build_rd_follow(run_id, after=0, max_lines=1000, kind="rd_test")
            zf.writestr("human_follow.json", json.dumps(follow, ensure_ascii=False, indent=2, default=str))
            zf.writestr("advice.json", json.dumps((follow.get("summary") or {}).get("advice") or [], ensure_ascii=False, indent=2, default=str))
            zf.writestr("README.txt", "Export de prueba RD. Datos saneados por la caja negra de BTDigg + RD.\n")
    except Exception as exc:
        return jsonify({"ok": False, "error": f"No se pudo crear export: {exc}"}), 500
    return jsonify({"ok": True, "zip": str(zip_path), "file": zip_path.name})


@bp.get("/api/job/<job_id>/stream")
def api_job_stream(job_id: str):
    def sse(event: str, data: dict[str, Any]) -> str:
        payload = json.dumps(data, ensure_ascii=False, default=str)
        return f"event: {event}\ndata: {payload}\n\n"

    @stream_with_context
    def generate():
        last_log_index = 0
        last_status = None
        last_ping = time.time()
        while True:
            with lock:
                job = jobs.get(job_id)
                if not job:
                    yield sse("error", {"ok": False, "error": "job no encontrado"})
                    return
                logs = list(job.get("log") or [])
                status = str(job.get("status") or "queued")
                results = list(job.get("results") or []) if status in ("done", "error") else []
                exit_code = job.get("exit_code")
                error = job.get("error")

            if last_log_index > len(logs):
                last_log_index = 0
            for line in logs[last_log_index:]:
                yield sse("log", {"ok": True, "line": line})
            last_log_index = len(logs)

            if status != last_status:
                yield sse("status", {"ok": True, "status": status, "module": "btdigg"})
                last_status = status

            if status in ("done", "error"):
                yield sse("done", {"ok": status == "done", "status": status, "module": "btdigg", "results": results, "exit_code": exit_code, "error": error})
                return

            now = time.time()
            if now - last_ping >= 15:
                yield ": ping\n\n"
                last_ping = now
            time.sleep(0.25)

    return Response(generate(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@bp.get("/api/results/btdigg")
def api_results_btdigg():
    return jsonify({"ok": True, "results": load_results()})


@bp.get("/api/results/<module>")
def api_results(module: str):
    if module != "btdigg":
        return jsonify({"ok": False, "error": "módulo no válido"}), 400
    return jsonify({"ok": True, "results": load_results()})


@bp.get("/api/history/btdigg")
def api_history_btdigg():
    return jsonify({"ok": True, "history": load_history()})


bp.add_url_rule("/api/rdt/send", view_func=api_rdt_send, methods=["POST"])
@bp.get("/api/qbit-toggle")
def api_qbit_toggle():
    cfg = read_json(BTDIGG_DIR / "config.json") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return jsonify({"ok": True, "enabled": bool(cfg.get("qbit_probe_enabled", True))})


@bp.post("/api/qbit-toggle")
def api_qbit_toggle_save():
    data = request.get_json(force=True, silent=True) or {}
    raw = data.get("enabled")
    if isinstance(raw, str):
        enabled = raw.strip().lower() in ("1", "true", "si", "sí", "yes", "on")
    else:
        enabled = bool(raw)

    path = BTDIGG_DIR / "config.json"
    cfg = read_json(path) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    if bool(cfg.get("qbit_probe_enabled", True)) == enabled:
        return jsonify({"ok": True, "enabled": enabled, "changed": False})

    try:
        cfg["qbit_probe_enabled"] = enabled
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        return jsonify({"ok": False, "error": f"No se pudo guardar qBit: {exc}"}), 500

    return jsonify({"ok": True, "enabled": enabled, "changed": True})


@bp.get("/api/tv-rules")
def api_tv_rules():
    return jsonify({"ok": True, "rules": load_tv_rules(), "defaults": default_tv_rules()})


@bp.post("/api/tv-rules")
def api_tv_rules_save():
    data = request.get_json(force=True, silent=True) or {}
    try:
        rules = save_tv_rules(data.get("rules") if isinstance(data.get("rules"), dict) else data)
        return jsonify({"ok": True, "rules": rules, "message": "Reglas guardadas"})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"No se pudieron guardar reglas: {exc}"}), 500


@bp.post("/api/tv-rules/reset")
def api_tv_rules_reset():
    try:
        rules = reset_tv_rules()
        return jsonify({"ok": True, "rules": rules, "message": "Reglas restauradas"})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"No se pudieron restaurar reglas: {exc}"}), 500


@bp.post("/api/tv-rules/classify")
def api_tv_rules_classify():
    data = request.get_json(force=True, silent=True) or {}
    title = str(data.get("title") or "").strip()
    rules = data.get("rules") if isinstance(data.get("rules"), dict) else None
    result = classify_title(title, rules, fallback="movies")
    labels = {"tv": "Series / TV", "movies": "Peliculas", "manual": "Manual"}
    return jsonify({
        "ok": True,
        "title": title,
        "destination": result.get("destination"),
        "label": labels.get(str(result.get("destination")), "Peliculas"),
        "matched_type": result.get("matched_type") or "",
        "matched_rule": result.get("matched_rule") or "",
    })


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


def _force_internal_settings(cfg: dict[str, Any]) -> None:
    cfg["verify_wait_attempts"] = 1


def _coerce_setting_value(raw: Any, spec: dict[str, Any]) -> Any:
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


def _public_settings_payload(cfg: dict[str, Any]) -> dict[str, Any]:
    _force_internal_settings(cfg)
    fields = []
    for spec in SETTINGS_SCHEMA:
        item = dict(spec)
        item["value"] = cfg.get(spec["key"])
        fields.append(item)
    return {"module": "btdigg", "title": "BTDigg + RD", "fields": fields}


@bp.get("/api/settings")
def api_settings():
    cfg = read_json(BTDIGG_DIR / "config.json") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return jsonify({"ok": True, "settings": {"btdigg": _public_settings_payload(cfg)}})


@bp.post("/api/settings")
def api_settings_save():
    data = request.get_json(force=True, silent=True) or {}
    values = data.get("values") or {}
    if str(data.get("module") or "btdigg") != "btdigg":
        return jsonify({"ok": False, "error": "módulo no válido"}), 400
    if not isinstance(values, dict):
        return jsonify({"ok": False, "error": "valores no válidos"}), 400

    path = BTDIGG_DIR / "config.json"
    cfg = read_json(path) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    _force_internal_settings(cfg)

    specs = {item["key"]: item for item in SETTINGS_SCHEMA}
    changed: list[str] = []
    try:
        for key, raw in values.items():
            if key not in specs:
                continue
            new_value = _coerce_setting_value(raw, specs[key])
            if cfg.get(key) != new_value:
                cfg[key] = new_value
                changed.append(key)
        _force_internal_settings(cfg)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    try:
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        return jsonify({"ok": False, "error": f"No se pudo guardar: {exc}"}), 500

    return jsonify({"ok": True, "changed": changed, "message": "Ajustes guardados"})
