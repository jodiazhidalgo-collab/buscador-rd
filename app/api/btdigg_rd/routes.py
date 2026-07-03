from __future__ import annotations

import json
import time
import zipfile
from typing import Any

from flask import Blueprint, Response, jsonify, request, stream_with_context

from ._settings_service import (
    SETTINGS_SCHEMA,
    coerce_setting_value as _coerce_setting_value,
    force_internal_settings as _force_internal_settings,
    load_settings_payload,
    public_settings_payload as _public_settings_payload,
    qbit_toggle_payload,
    save_qbit_toggle,
    save_settings_values,
)
from ._tv_rules_service import (
    classify_tv_rules_payload,
    reset_tv_rules_payload,
    save_tv_rules_payload,
    tv_rules_payload,
)
from ._ui_state_service import save_ui_state_payload, ui_state_payload
from .blackbox import trace_folder
from .config import BTDIGG_DIR, RD_TEST_EXPORTS_DIR, ensure_runtime_dirs
from .history import load_history
from .jobs import TERMINAL_STATUSES, cancel_job, jobs, lock, running_job, start_job, start_rd_test
from .retention import cleanup_rd_test_runs, list_rd_test_runs
from .results import load_results
from .rd_follow import build_rd_event_detail, build_rd_follow
from .send import api_rdt_send
from .title_resolver import resolve_movie_title
from .title_resolver.service import TitleResolverError
from .title_resolver.tmdb_client import TmdbUnavailable
from .voice_diagnostics import record_voice_diagnostic


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


@bp.post("/api/job/<job_id>/cancel")
def api_job_cancel(job_id: str):
    result = cancel_job(job_id)
    status = 404 if not result.get("ok") and result.get("status") == "missing" else 200
    return jsonify(result), status


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
            follow = build_rd_follow(run_id, after=0, max_lines=1000, kind="rd_test", include_magnets=False)
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
                results = list(job.get("results") or []) if status == "done" else []
                exit_code = job.get("exit_code")
                error = job.get("error")
                forced_stop = bool(job.get("forced_stop"))
                cleanup_uncertain = bool(job.get("cleanup_uncertain"))

            if last_log_index > len(logs):
                last_log_index = 0
            for line in logs[last_log_index:]:
                yield sse("log", {"ok": True, "line": line})
            last_log_index = len(logs)

            if status != last_status:
                yield sse("status", {"ok": True, "status": status, "module": "btdigg"})
                last_status = status

            if status in TERMINAL_STATUSES:
                yield sse(
                    "done",
                    {
                        "ok": status != "error",
                        "status": status,
                        "module": "btdigg",
                        "results": results,
                        "exit_code": exit_code,
                        "error": error,
                        "forced_stop": forced_stop,
                        "cleanup_uncertain": cleanup_uncertain,
                    },
                )
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


@bp.get("/api/ui-state")
def api_ui_state():
    return jsonify(ui_state_payload())


@bp.post("/api/ui-state")
def api_ui_state_save():
    data = request.get_json(force=True, silent=True) or {}
    payload, status = save_ui_state_payload(data)
    return jsonify(payload), status


@bp.post("/api/voice/diagnostic")
def api_voice_diagnostic():
    data = request.get_json(force=True, silent=True) or {}
    payload, status = record_voice_diagnostic(data, user_agent=request.headers.get("User-Agent", ""))
    return jsonify(payload), status


@bp.post("/api/title-resolver/resolve")
def api_title_resolver_resolve():
    data = request.get_json(force=True, silent=True) or {}
    title = str(data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "status": "error", "error_code": "missing_title", "message": "Falta titulo"}), 400
    evidence = data.get("evidence") if isinstance(data.get("evidence"), list) else []
    clean_evidence = [str(item or "").strip() for item in evidence if str(item or "").strip()]
    try:
        payload = resolve_movie_title(
            title=title,
            evidence=clean_evidence,
            media_hint=str(data.get("media_hint") or "movie"),
        )
        return jsonify(payload)
    except TmdbUnavailable as exc:
        return jsonify({"ok": False, "status": "error", "error_code": "tmdb_unavailable", "message": str(exc)}), 503
    except TitleResolverError as exc:
        return jsonify({"ok": False, "status": "error", "error_code": exc.error_code, "message": str(exc)}), exc.status_code
    except Exception as exc:
        return jsonify({"ok": False, "status": "error", "error_code": "title_resolver_error", "message": str(exc)}), 500


bp.add_url_rule("/api/rdt/send", view_func=api_rdt_send, methods=["POST"])
@bp.get("/api/qbit-toggle")
def api_qbit_toggle():
    return jsonify(qbit_toggle_payload(BTDIGG_DIR))


@bp.post("/api/qbit-toggle")
def api_qbit_toggle_save():
    data = request.get_json(force=True, silent=True) or {}
    payload, status = save_qbit_toggle(BTDIGG_DIR, data)
    return jsonify(payload), status


@bp.get("/api/tv-rules")
def api_tv_rules():
    return jsonify(tv_rules_payload())


@bp.post("/api/tv-rules")
def api_tv_rules_save():
    data = request.get_json(force=True, silent=True) or {}
    payload, status = save_tv_rules_payload(data)
    return jsonify(payload), status


@bp.post("/api/tv-rules/reset")
def api_tv_rules_reset():
    payload, status = reset_tv_rules_payload()
    return jsonify(payload), status


@bp.post("/api/tv-rules/classify")
def api_tv_rules_classify():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(classify_tv_rules_payload(data))


@bp.get("/api/settings")
def api_settings():
    return jsonify(load_settings_payload(BTDIGG_DIR))


@bp.post("/api/settings")
def api_settings_save():
    data = request.get_json(force=True, silent=True) or {}
    payload, status = save_settings_values(BTDIGG_DIR, data)
    return jsonify(payload), status
