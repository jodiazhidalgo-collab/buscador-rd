from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .blackbox import job_folder


IMPORTANT_STATUS = {"RD_OK", "RD_FAIL", "RD_ERROR", "RD_ERROR_TEMPORAL", "PACK_SIN_COINCIDENCIA", "NO_INSTANT"}
USEFUL_EVENTS = {
    "JOB_STARTED",
    "PROCESS_STARTED",
    "JOB_FINISHED_OK",
    "JOB_FINISHED_ERROR",
    "btdigg_search_end",
    "rd_verify_queue_start",
    "rd_verify_queue_done_item",
    "rd_verify_select_files",
    "rd_verify_post_select_poll",
    "rd_verify_ok",
    "rd_verify_not_instant",
    "rd_call_retry_429",
    "rd_endpoint_429_backoff",
    "rd_rate_429_cooldown",
    "rd_api_http_error",
    "rd_call_terminal_error",
    "rd_fast_discard",
    "rd_cleanup_final_start",
    "rd_cleanup_final_end",
    "rd_rate_summary",
    "rd_endpoint_pacer_summary",
    "rd_verify_batch_end",
    "rd_check_summary",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_events(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                out.append(item)
    except Exception:
        return out
    return out


def _last(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for record in reversed(events):
        if record.get("event") == name:
            return record
    return None


def _data(record: dict[str, Any] | None) -> dict[str, Any]:
    data = (record or {}).get("data") or {}
    return data if isinstance(data, dict) else {}


def _fmt_num(value: Any, default: str = "0") -> str:
    if value is None or value == "":
        return default
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def _fmt_sec(value: Any) -> str:
    try:
        num = float(value)
    except Exception:
        return "0s"
    if num < 1:
        return f"{num:.2f}s"
    text = f"{num:.1f}".rstrip("0").rstrip(".")
    return text + "s"


def _short_title(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) > 82:
        return text[:79] + "..."
    return text


def _human_reason(value: Any) -> str:
    text = str(value or "").strip()
    labels = {
        "waiting_files_no_match": "pack sin coincidencia",
        "zero_progress_post_select": "sin progreso tras seleccionar",
        "magnet_error": "magnet con error",
        "invalid_magnet": "magnet inválido",
        "no_seeders": "sin seeders",
        "corrupted": "corrupto",
        "dead": "muerto",
        "infringing_file": "bloqueado por RD",
    }
    return labels.get(text, text.replace("_", " ") or "descarte")


def _line(ts: str, level: str, kind: str, text: str) -> dict[str, Any]:
    return {"ts": ts, "level": level, "kind": kind, "text": text}


def _event_to_line(record: dict[str, Any]) -> dict[str, Any] | None:
    event = str(record.get("event") or "")
    ts = str(record.get("ts") or "")[11:19] or "--:--:--"
    data = _data(record)

    if event == "JOB_STARTED":
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        query = payload.get("query") or "sin título"
        pages = payload.get("pages") or "1"
        return _line(ts, "info", "start", f"Prueba/búsqueda iniciada: {query} | páginas {pages}.")

    if event == "PROCESS_STARTED":
        return _line(ts, "info", "start", "Motor arrancado. Esperando señales RD.")

    if event == "btdigg_search_end":
        return _line(ts, "info", "btdigg", f"BTDigg entrega {_fmt_num(data.get('total'))} candidatos para cribar.")

    if event == "rd_verify_queue_start":
        cfg = data.get("config") if isinstance(data.get("config"), dict) else {}
        verifying = data.get("verifying")
        workers = data.get("workers")
        per_min = cfg.get("rd_api_rate_limit_per_min")
        burst = cfg.get("rd_api_rate_limit_burst")
        return _line(ts, "info", "rd", f"RD empieza: {verifying} candidatos, {workers} workers, límite {per_min}/min, ráfaga {burst}.")

    if event == "rd_verify_queue_done_item":
        done = int(data.get("done") or 0)
        total = int(data.get("total") or 0)
        status = str(data.get("status") or "")
        if status not in IMPORTANT_STATUS and total and done % 5 and done != total:
            return None
        title = _short_title(data.get("title"))
        return _line(ts, "ok" if status == "RD_OK" else "warn" if status in IMPORTANT_STATUS else "info", "progress", f"RD {done}/{total}: {status or 'procesado'} | {title}")

    if event == "rd_verify_select_files":
        title = _short_title(data.get("title"))
        files = data.get("files") or data.get("selected_file") or ""
        return _line(ts, "info", "select", f"Seleccionando archivo interno: {title} | {files}")

    if event == "rd_verify_post_select_poll":
        progress = _fmt_num(data.get("progress"))
        links = _fmt_num(data.get("links"))
        return _line(ts, "info", "select", f"Post-selección: progreso {progress}% | links {links}.")

    if event == "rd_verify_ok":
        title = _short_title(data.get("title"))
        links = _fmt_num(data.get("links"))
        size = _fmt_num(data.get("size_gb"))
        return _line(ts, "ok", "ok", f"RD_OK: {links} link real | {size} GB | {title}")

    if event == "rd_verify_not_instant":
        title = _short_title(data.get("title"))
        status = data.get("status") or "no instantáneo"
        return _line(ts, "warn", "discard", f"NO_INSTANT: {status} | {title}")

    if event == "rd_fast_discard":
        reason = _human_reason(data.get("reason"))
        status = data.get("status") or "descartado"
        title = _short_title(data.get("title"))
        return _line(ts, "warn", "discard", f"Descarte rápido: {status} | {reason} | {title}")

    if event == "rd_call_retry_429":
        op = data.get("op") or data.get("path") or "RD"
        attempt = data.get("attempt")
        max_attempts = data.get("max_attempts")
        wait = _fmt_sec(data.get("wait_sec"))
        return _line(ts, "warn", "429", f"429 en {op}: intento {attempt}/{max_attempts}, espera {wait}.")

    if event == "rd_endpoint_429_backoff":
        group = data.get("group") or "endpoint"
        cooldown = _fmt_sec(data.get("cooldown_sec"))
        interval = _fmt_sec(data.get("min_interval"))
        massive = " masivo" if data.get("massive") else ""
        return _line(ts, "warn", "429", f"Freno{massive} en {group}: pausa {cooldown}, intervalo {interval}.")

    if event == "rd_rate_429_cooldown":
        path = data.get("path") or "RD"
        return _line(ts, "warn", "429", f"Pausa general 429: {_fmt_sec(data.get('cooldown_sec'))} en {path}.")

    if event == "rd_api_http_error":
        code = data.get("code")
        path = data.get("path") or "RD"
        err = data.get("error") or ""
        if int(code or 0) == 429:
            return _line(ts, "warn", "429", f"RD protesta 429 en {path}: {err}.")
        return _line(ts, "warn", "http", f"RD HTTP {code} en {path}: {err}.")

    if event == "rd_call_terminal_error":
        code = data.get("code")
        err = data.get("error") or ""
        op = data.get("op") or data.get("path") or "RD"
        return _line(ts, "warn", "terminal", f"Terminal RD {code} en {op}: {err}.")

    if event == "rd_cleanup_final_start":
        ctx = data.get("context") if isinstance(data.get("context"), dict) else {}
        total = data.get("total")
        pending = ctx.get("cleanup_pending", 0)
        return _line(ts, "info", "cleanup", f"Limpieza final: {total} candidatos pendientes | cola previa {pending}.")

    if event == "rd_cleanup_final_end":
        deleted = data.get("cleanup_deleted", 0)
        missing = data.get("cleanup_missing", 0)
        pending = data.get("cleanup_pending", 0)
        leftover = data.get("cleanup_leftover", 0)
        level = "ok" if not pending and not leftover else "warn"
        return _line(ts, level, "cleanup", f"Limpieza RD: borrados {deleted}, ausentes {missing}, pendientes {pending}, sobrantes {leftover}.")

    if event == "rd_rate_summary":
        label = data.get("label") or "resumen"
        calls = data.get("api_calls_total", 0)
        max_window = data.get("max_window_count", 0)
        cooldowns = data.get("cooldowns_429", 0)
        waits = data.get("waits_total", 0)
        return _line(ts, "info", "summary", f"Ritmo RD {label}: {calls} llamadas, ventana máx {max_window}, esperas {waits}, 429 {cooldowns}.")

    if event == "rd_endpoint_pacer_summary":
        label = data.get("label") or "resumen"
        by_group = data.get("429_by_group") if isinstance(data.get("429_by_group"), dict) else {}
        text_429 = ", ".join(f"{k}={v}" for k, v in by_group.items()) or "0"
        return _line(ts, "warn" if by_group else "ok", "summary", f"Pacer RD {label}: 429 por endpoint {text_429}.")

    if event in {"rd_verify_batch_end", "rd_check_summary"}:
        ok = data.get("RD_OK", 0)
        no_inst = data.get("NO_INSTANT", 0)
        pack = data.get("PACK_SIN_COINCIDENCIA", 0)
        fail = data.get("RD_FAIL", 0)
        err = int(data.get("RD_ERROR", 0) or 0) + int(data.get("RD_ERROR_TEMPORAL", 0) or 0)
        level = "ok" if not err else "warn"
        return _line(ts, level, "summary", f"Resumen RD: OK={ok} | NO_INSTANT={no_inst} | PACK={pack} | FAIL={fail} | ERROR={err}.")

    if event == "JOB_FINISHED_OK":
        elapsed = _fmt_sec(data.get("elapsed_sec"))
        results = data.get("results_count", 0)
        return _line(ts, "ok", "finish", f"Trabajo terminado: {results} resultados, {elapsed}.")

    if event == "JOB_FINISHED_ERROR":
        return _line(ts, "error", "finish", "Trabajo terminado con error. Revisa caja negra.")

    return None


def _count_fast_discard(events: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for record in events:
        if record.get("event") != "rd_fast_discard":
            continue
        reason = str(_data(record).get("reason") or "otro")
        counter[reason] += 1
    return dict(counter)


def _summary(events: list[dict[str, Any]], summary_file: dict[str, Any]) -> dict[str, Any]:
    rate = _data(_last(events, "rd_rate_summary"))
    pacer = _data(_last(events, "rd_endpoint_pacer_summary"))
    cleanup = _data(_last(events, "rd_cleanup_final_end"))
    rd_counts = _data(_last(events, "rd_verify_batch_end") or _last(events, "rd_check_summary"))
    queue_item = _data(_last(events, "rd_verify_queue_done_item"))
    queue_start = _data(_last(events, "rd_verify_queue_start"))

    total = int(queue_item.get("total") or queue_start.get("verifying") or rd_counts.get("total") or 0)
    done = int(queue_item.get("done") or 0)
    status_counts = {key: int(rd_counts.get(key, 0) or 0) for key in ("RD_OK", "NO_INSTANT", "PACK_SIN_COINCIDENCIA", "RD_FAIL", "RD_ERROR", "RD_ERROR_TEMPORAL") if key in rd_counts}
    http_429 = pacer.get("429_by_group") if isinstance(pacer.get("429_by_group"), dict) else {}
    calls_by_group = pacer.get("calls_by_group") if isinstance(pacer.get("calls_by_group"), dict) else {}
    waits_by_group = pacer.get("waits_by_group") if isinstance(pacer.get("waits_by_group"), dict) else {}

    return {
        "progress": {"done": done, "total": total, "active": queue_item.get("active")},
        "rd_counts": status_counts,
        "rate": {
            "api_calls_total": rate.get("api_calls_total", 0),
            "max_window_count": rate.get("max_window_count", 0),
            "max_burst_count": rate.get("max_burst_count", 0),
            "cooldowns_429": rate.get("cooldowns_429", 0),
            "per_min": rate.get("per_min"),
            "burst": rate.get("burst"),
            "waits_total": rate.get("waits_total", 0),
            "wait_seconds_total": rate.get("wait_seconds_total", 0),
        },
        "pacer": {
            "429_by_group": http_429,
            "calls_by_group": calls_by_group,
            "waits_by_group": waits_by_group,
            "interval_final_by_group": pacer.get("interval_final_by_group") if isinstance(pacer.get("interval_final_by_group"), dict) else {},
        },
        "fast_discard": _count_fast_discard(events),
        "cleanup": {
            "deleted": cleanup.get("cleanup_deleted", 0),
            "missing": cleanup.get("cleanup_missing", 0),
            "pending": cleanup.get("cleanup_pending", 0),
            "leftover": cleanup.get("cleanup_leftover", 0),
            "temp_ids": cleanup.get("temp_ids", 0),
        },
        "diagnostic_status": summary_file.get("diagnostic_status"),
        "operation_status": summary_file.get("operation_status"),
        "elapsed_sec": summary_file.get("elapsed_sec"),
        "updated_at": summary_file.get("updated_at"),
    }


def build_rd_follow(job_id: str, after: int = 0, max_lines: int = 90) -> dict[str, Any]:
    folder = job_folder(job_id)
    events = _read_events(folder / "events.jsonl")
    summary_file = _read_json(folder / "summary.json")
    cursor = len(events)
    after = max(0, min(int(after or 0), cursor))

    if after == 0:
        scan = events
    else:
        scan = events[after:]

    lines: list[dict[str, Any]] = []
    for record in scan:
        event = str(record.get("event") or "")
        if event not in USEFUL_EVENTS and not event.startswith(("rd_", "JOB_")):
            continue
        line = _event_to_line(record)
        if line:
            if not lines or lines[-1].get("text") != line.get("text"):
                lines.append(line)

    if after == 0 and len(lines) > max_lines:
        lines = lines[-max_lines:]
    elif len(lines) > max_lines:
        lines = lines[:max_lines]

    return {
        "job_id": job_id,
        "cursor": cursor,
        "has_diagnostics": bool(events),
        "summary": _summary(events, summary_file),
        "lines": lines,
    }
