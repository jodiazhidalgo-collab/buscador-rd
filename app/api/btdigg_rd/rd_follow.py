from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .blackbox import trace_folder


TRANSLATOR_VERSION = "rd_follow_v2"


IMPORTANT_STATUS = {"RD_OK", "RD_FAIL", "RD_ERROR", "RD_ERROR_TEMPORAL", "PACK_SIN_COINCIDENCIA", "NO_INSTANT"}
USEFUL_EVENTS = {
    "JOB_STARTED",
    "PROCESS_STARTED",
    "JOB_FINISHED_OK",
    "JOB_FINISHED_CANCELLED",
    "JOB_FINISHED_ERROR",
    "browser_auto_search_start_dom",
    "browser_auto_search_end_dom",
    "extract_magnets",
    "prepare_after_filter",
    "prepare_after_query_prefilter",
    "btdigg_search_end",
    "rd_verify_batch_start",
    "rd_verify_queue_start",
    "rd_verify_queue_done_item",
    "rd_endpoint_pace_wait",
    "rd_rate_wait",
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


def _first_data(events: list[dict[str, Any]], *names: str) -> dict[str, Any]:
    wanted = set(names)
    for record in events:
        if record.get("event") in wanted:
            return _data(record)
    return {}


def _last_data(events: list[dict[str, Any]], *names: str) -> dict[str, Any]:
    wanted = set(names)
    for record in reversed(events):
        if record.get("event") in wanted:
            return _data(record)
    return {}


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


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = text[:-2] + ":" + text[-2:]
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _job_started_at(events: list[dict[str, Any]], summary_file: dict[str, Any]) -> datetime | None:
    for record in events:
        when = _parse_dt(record.get("ts"))
        if when:
            return when
    return _parse_dt(summary_file.get("started_at"))


def _elapsed(record: dict[str, Any], started_at: datetime | None) -> str:
    current = _parse_dt(record.get("ts"))
    if not current or not started_at:
        return "+0.0s"
    try:
        seconds = max(0.0, (current - started_at).total_seconds())
    except Exception:
        return "+0.0s"
    return "+" + _fmt_sec(seconds)


def _elapsed_ms(record: dict[str, Any], started_at: datetime | None) -> int:
    current = _parse_dt(record.get("ts"))
    if not current or not started_at:
        return 0
    try:
        return int(max(0.0, (current - started_at).total_seconds()) * 1000)
    except Exception:
        return 0


def _mode_label(value: Any) -> str:
    labels = {
        "0": "Sin filtro",
        "1": "Calidad pura",
        "3": "Castellano obligatorio",
    }
    return labels.get(str(value), "Sin filtro")


def _endpoint_label(value: Any) -> str:
    text = str(value or "")
    labels = {
        "addMagnet": "Meter magnet",
        "selectFiles": "Seleccionar archivos",
        "delete": "Borrar",
        "info": "Mirar info",
        "activeCount": "Estado RD",
        "list": "Lista RD",
    }
    if text in labels:
        return labels[text]
    if "addMagnet" in text:
        return labels["addMagnet"]
    if "selectFiles" in text:
        return labels["selectFiles"]
    if "delete" in text:
        return labels["delete"]
    if "/info" in text:
        return labels["info"]
    if "/activeCount" in text:
        return labels["activeCount"]
    if text == "/torrents":
        return labels["list"]
    return text or "RD"


def _endpoint_hint(value: Any) -> str:
    label = _endpoint_label(value)
    if label == "Meter magnet":
        return 'sube "Meter magnet" o "Pausa endpoint"'
    if label == "Seleccionar archivos":
        return 'sube "Seleccionar archivos" o "Pausa endpoint"'
    if label == "Borrar":
        return 'sube "Borrar" o "Pausa endpoint"'
    if label == "Mirar info":
        return 'baja "Info a la vez" si se repite'
    return 'sube "Pausa 429" si se repite'


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




def _status_label(value: Any) -> str:
    labels = {
        "RD_OK": "OK con link",
        "NO_INSTANT": "no instantáneo",
        "PACK_SIN_COINCIDENCIA": "pack descartado",
        "RD_FAIL": "fallo RD descartado",
        "RD_ERROR": "aviso RD",
        "RD_ERROR_TEMPORAL": "aviso temporal RD",
    }
    return labels.get(str(value or ""), str(value or "procesado"))


def _default_badge(kind: str, level: str) -> tuple[str, str]:
    if level in {"warn", "error"}:
        return "Aviso", "principal"
    return "", "neutral"


def _endpoint_badge_tone(value: Any) -> tuple[str, str]:
    label = _endpoint_label(value)
    if label == "Meter magnet":
        return "Principal", "principal"
    if label in {"Seleccionar archivos", "Borrar"}:
        return "Secundario", "secundario"
    if label in {"Mirar info", "Estado RD", "Lista RD"}:
        return "Ajuste", "ajuste"
    return "RD", "neutral"


def _line(
    record: dict[str, Any],
    started_at: datetime | None,
    level: str,
    kind: str,
    text: str,
    badge: str | None = None,
    tone: str | None = None,
) -> dict[str, Any]:
    ts = str(record.get("ts") or "")[11:19] or "--:--:--"
    default_badge, default_tone = _default_badge(kind, level)
    seq = record.get("seq")
    try:
        seq_num = int(seq)
    except Exception:
        seq_num = 0
    event_id = str(record.get("event_id") or (f"E{seq_num:06d}" if seq_num else ""))
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    endpoint_group = data.get("group") or data.get("endpoint_group") or data.get("op") or data.get("path") or record.get("phase") or kind
    action = data.get("action") or data.get("op") or data.get("path") or data.get("method") or record.get("event") or kind
    internal_code = record.get("code") or f"{str(record.get('phase') or kind).upper().replace('-', '_')}.{str(record.get('event') or kind).upper()}"
    return {
        "line_id": f"L{event_id}" if event_id else (f"L{seq_num:06d}" if seq_num else ""),
        "source_event_id": event_id,
        "translator_version": TRANSLATOR_VERSION,
        "ts": ts,
        "elapsed": _elapsed(record, started_at),
        "elapsed_ms": _elapsed_ms(record, started_at),
        "level": level,
        "kind": kind,
        "text": text,
        "badge": badge or default_badge,
        "tone": tone or default_tone,
        "source_event": record.get("event"),
        "source_phase": record.get("phase"),
        "source_code": record.get("code"),
        "trace_kind": record.get("trace_kind"),
        "trace_id": record.get("trace_id") or record.get("job_id"),
        "action": action,
        "endpoint_group": endpoint_group,
        "internal_code": internal_code,
        "advice_id": data.get("advice_id") or "",
    }


def _event_to_line(record: dict[str, Any], started_at: datetime | None) -> dict[str, Any] | None:
    event = str(record.get("event") or "")
    data = _data(record)

    if event == "JOB_STARTED":
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        query = payload.get("query") or "sin título"
        pages = payload.get("pages") or "1"
        mode = _mode_label(payload.get("mode"))
        return _line(record, started_at, "info", "start", f"Búsqueda: {query} | Páginas: {pages} | Modo: {mode}")

    if event == "PROCESS_STARTED":
        return _line(record, started_at, "info", "start", "Motor arrancado. Esperando señales de RD.")

    if event == "browser_auto_search_start_dom":
        pages = data.get("parsed_pages")
        if isinstance(pages, list) and pages:
            return _line(record, started_at, "info", "btdigg", f"BTDigg: revisando página {pages[0]}/{pages[-1]}...")
        return _line(record, started_at, "info", "btdigg", "BTDigg: revisando páginas...")

    if event in {"browser_auto_search_end_dom", "extract_magnets"}:
        total = data.get("total") or data.get("magnets")
        if total is None:
            return None
        return _line(record, started_at, "info", "btdigg", f"BTDigg: {total} candidatos encontrados.")

    if event == "prepare_after_filter":
        before = data.get("before", 0)
        after_count = data.get("after", 0)
        removed = data.get("removed", 0)
        return _line(record, started_at, "info", "filter", f"Filtro: {after_count}/{before} candidatos siguen; quitados {removed}.")

    if event == "prepare_after_query_prefilter":
        before = data.get("before", 0)
        after_count = data.get("after", 0)
        removed = data.get("removed", 0)
        return _line(record, started_at, "info", "filter", f"Criba por búsqueda: {after_count}/{before} candidatos; quitados {removed}.")

    if event == "btdigg_search_end":
        return _line(record, started_at, "info", "btdigg", f"BTDigg: {_fmt_num(data.get('total'))} candidatos para cribar.")

    if event == "rd_verify_batch_start":
        total = data.get("verifying") or data.get("total")
        return _line(record, started_at, "info", "rd", f"RD: preparando {total} candidatos.")

    if event == "rd_verify_queue_start":
        cfg = data.get("config") if isinstance(data.get("config"), dict) else {}
        verifying = data.get("verifying")
        workers = data.get("workers")
        per_min = cfg.get("rd_api_rate_limit_per_min")
        burst = cfg.get("rd_api_rate_limit_burst")
        return _line(record, started_at, "info", "rd", f"RD: {verifying} candidatos | {workers} workers | límite {per_min}/min | ráfaga {burst}.")

    if event == "rd_endpoint_pace_wait":
        wait = float(data.get("wait_sec") or 0)
        if wait < 0.05:
            return None
        raw_group = data.get("group") or data.get("path")
        group = _endpoint_label(raw_group)
        badge, tone = _endpoint_badge_tone(raw_group)
        why = str(data.get("why") or "")
        reason = "concurrencia" if "max_concurrent" in why else "ritmo"
        return _line(record, started_at, "info", "pace", f"Ritmo: {group} espera {_fmt_sec(wait)} por {reason}.", badge, tone)

    if event == "rd_rate_wait":
        wait = float(data.get("wait_sec") or 0)
        if wait < 0.05:
            return None
        why = str(data.get("why") or "ritmo")
        why_label = "ráfaga" if why == "burst" else why
        return _line(record, started_at, "info", "pace", f"Ritmo global: espera {_fmt_sec(wait)} por {why_label}.", "Avanzado", "avanzado")

    if event == "rd_verify_queue_done_item":
        done = int(data.get("done") or 0)
        total = int(data.get("total") or 0)
        status = str(data.get("status") or "")
        if status in {"RD_ERROR", "RD_ERROR_TEMPORAL"}:
            return _line(record, started_at, "warn", "progress", f"RD: {done}/{total} aviso.", "Principal", "principal")
        return _line(record, started_at, "info", "progress", f"RD: {done}/{total} OK.", "OK", "ok")

    if event == "rd_verify_select_files":
        files = data.get("files") or data.get("selected_file") or ""
        suffix = f" | archivos {files}" if files else ""
        return _line(record, started_at, "info", "select", "RD: pack detectado, seleccionando archivo interno" + suffix + ".", "Secundario", "secundario")

    if event == "rd_verify_post_select_poll":
        progress = _fmt_num(data.get("progress"))
        links = _fmt_num(data.get("links"))
        try:
            has_links = int(float(str(links or 0))) > 0
        except Exception:
            has_links = False
        level = "ok" if has_links else "info"
        badge, tone = ("OK", "ok") if has_links else ("Secundario", "secundario")
        return _line(record, started_at, level, "select", f"RD: tras seleccionar | progreso {progress}% | links {links}.", badge, tone)

    if event == "rd_verify_ok":
        links = _fmt_num(data.get("links"))
        size = _fmt_num(data.get("size_gb"))
        return _line(record, started_at, "ok", "ok", f"RD_OK: {links} link real | {size} GB.", "OK", "ok")

    if event == "rd_verify_not_instant":
        status = data.get("status") or "no instantáneo"
        return _line(record, started_at, "info", "discard", f"RD: no instantáneo | {status}.", "OK", "ok")

    if event == "rd_fast_discard":
        return None

    if event == "rd_call_retry_429":
        op = data.get("op") or data.get("path") or "RD"
        attempt = data.get("attempt")
        max_attempts = data.get("max_attempts")
        wait = _fmt_sec(data.get("wait_sec"))
        label = _endpoint_label(op)
        badge, tone = _endpoint_badge_tone(op)
        return _line(record, started_at, "warn", "429", f"429: {label} protesta | intento {attempt}/{max_attempts} | espera {wait} | Consejo: {_endpoint_hint(op)}.", badge, tone)

    if event == "rd_endpoint_429_backoff":
        group = data.get("group") or "endpoint"
        cooldown = _fmt_sec(data.get("cooldown_sec"))
        interval = _fmt_sec(data.get("min_interval"))
        label = _endpoint_label(group)
        badge, tone = _endpoint_badge_tone(group)
        massive = " masivo" if data.get("massive") else ""
        return _line(record, started_at, "warn", "429", f"429{massive}: freno en {label} | pausa {cooldown} | intervalo {interval} | Consejo: {_endpoint_hint(group)}.", badge, tone)

    if event == "rd_rate_429_cooldown":
        return _line(record, started_at, "warn", "429", f"429: pausa general {_fmt_sec(data.get('cooldown_sec'))} | Consejo: sube Pausa 429 si se repite.", "Principal", "principal")

    if event == "rd_api_http_error":
        code = data.get("code")
        path = data.get("path") or "RD"
        if int(code or 0) == 429:
            label = _endpoint_label(path)
            badge, tone = _endpoint_badge_tone(path)
            return _line(record, started_at, "warn", "429", f"429: RD protesta en {label} | Consejo: {_endpoint_hint(path)}.", badge, tone)
        if int(code or 0) in {35, 37, 403, 451}:
            return None
        badge, tone = _endpoint_badge_tone(path)
        return _line(record, started_at, "warn", "http", f"RD HTTP {code} en {_endpoint_label(path)}.", badge, tone)

    if event == "rd_call_terminal_error":
        code = data.get("code")
        op = data.get("op") or data.get("path") or "RD"
        if int(code or 0) in {35, 451}:
            return None
        badge, tone = _endpoint_badge_tone(op)
        return _line(record, started_at, "warn", "terminal", f"RD: error terminal {code} en {_endpoint_label(op)}.", badge, tone)

    if event == "rd_cleanup_final_start":
        total = data.get("total")
        return _line(record, started_at, "info", "cleanup", f"Limpieza: revisando {total} temporales.", "Secundario", "secundario")

    if event == "rd_cleanup_final_end":
        deleted = data.get("cleanup_deleted", 0)
        pending = data.get("cleanup_pending", 0)
        leftover = data.get("cleanup_leftover", 0)
        level = "ok" if not pending and not leftover else "warn"
        badge, tone = ("OK", "ok") if level == "ok" else ("Secundario", "secundario")
        return _line(record, started_at, level, "cleanup", f"Limpieza: borrados {deleted} | pendientes {pending} | sobrantes {leftover}.", badge, tone)

    if event == "rd_rate_summary":
        calls = data.get("api_calls_total", 0)
        max_window = data.get("max_window_count", 0)
        cooldowns = data.get("cooldowns_429", 0)
        waits = data.get("waits_total", 0)
        level = "warn" if int(cooldowns or 0) else "info"
        text = f"Ritmo RD: {calls} peticiones | pico {max_window}/min | esperas {waits} | 429 {cooldowns}."
        if int(cooldowns or 0):
            text += " Consejo: sube Pausa 429 si se repite."
        return _line(record, started_at, level, "summary", text, "Avanzado", "avanzado")

    if event == "rd_endpoint_pacer_summary":
        by_group = data.get("429_by_group") if isinstance(data.get("429_by_group"), dict) else {}
        if not by_group:
            return None
        text_429 = ", ".join(f"{_endpoint_label(k)}={v}" for k, v in by_group.items())
        return _line(record, started_at, "warn", "summary", f"429 por zona: {text_429}. Consejo: ajusta la zona que más protesta.", "Principal", "principal")

    if event in {"rd_verify_batch_end", "rd_check_summary"}:
        ok = data.get("RD_OK", 0)
        no_inst = data.get("NO_INSTANT", 0)
        pack = data.get("PACK_SIN_COINCIDENCIA", 0)
        fail = data.get("RD_FAIL", 0)
        err = int(data.get("RD_ERROR", 0) or 0) + int(data.get("RD_ERROR_TEMPORAL", 0) or 0)
        level = "ok" if not err else "warn"
        text = f"Resumen RD: OK {ok} | no instantáneos {no_inst} | packs {pack} | descartes RD {fail} | avisos RD {err}."
        if err:
            text += " Consejo: no apures velocidad hasta revisar esos avisos."
        return _line(record, started_at, level, "summary", text, "Ajuste" if err else None, "ajuste" if err else None)

    if event == "JOB_FINISHED_OK":
        elapsed = _fmt_sec(data.get("elapsed_sec"))
        results = data.get("results_count", 0)
        return _line(record, started_at, "ok", "finish", f"Terminado: {results} resultados | tiempo total {elapsed}.")

    if event == "JOB_FINISHED_CANCELLED":
        elapsed = _fmt_sec(data.get("elapsed_sec"))
        forced = " Parada forzada: revisa caja negra." if data.get("forced_stop") or data.get("cleanup_uncertain") else ""
        return _line(record, started_at, "info", "finish", f"Cancelado: tiempo total {elapsed}.{forced}", "Cancelado", "secundario")

    if event == "JOB_FINISHED_ERROR":
        return _line(record, started_at, "error", "finish", "Terminado con error. Revisa caja negra.")

    return None


def _count_fast_discard(events: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for record in events:
        if record.get("event") != "rd_fast_discard":
            continue
        reason = str(_data(record).get("reason") or "otro")
        counter[reason] += 1
    return dict(counter)


def _sum_dict(data: dict[str, Any]) -> int:
    return sum(int(value or 0) for value in data.values())


def _advice(summary: dict[str, Any]) -> list[dict[str, Any]]:
    pacer = summary.get("pacer") if isinstance(summary.get("pacer"), dict) else {}
    by_group = pacer.get("429_by_group") if isinstance(pacer.get("429_by_group"), dict) else {}
    cleanup = summary.get("cleanup") if isinstance(summary.get("cleanup"), dict) else {}
    rd_counts = summary.get("rd_counts") if isinstance(summary.get("rd_counts"), dict) else {}
    rate = summary.get("rate") if isinstance(summary.get("rate"), dict) else {}
    out: list[dict[str, Any]] = []

    def item(rule_id: str, text: str, tone: str, targets: list[str], evidence: dict[str, Any]) -> dict[str, Any]:
        return {
            "advice_id": "ADV_" + rule_id.upper().replace(".", "_"),
            "rule_id": rule_id,
            "level": "warn" if tone != "ok" else "ok",
            "kind": "advice",
            "badge": "Consejo" if tone != "ok" else "OK",
            "tone": tone,
            "text": text,
            "config_targets": targets,
            "evidence": evidence,
        }

    if _sum_dict(by_group):
        group = max(by_group, key=lambda key: int(by_group.get(key) or 0))
        targets = {
            "addMagnet": ["rd_addmagnet_min_interval_sec", "rd_endpoint_429_cooldown_sec"],
            "selectFiles": ["rd_selectfiles_min_interval_sec", "rd_endpoint_429_cooldown_sec"],
            "delete": ["rd_delete_min_interval_sec", "rd_endpoint_429_cooldown_sec"],
            "info": ["rd_info_min_interval_sec", "rd_info_max_concurrent"],
        }.get(str(group), ["rd_api_429_cooldown_sec"])
        out.append(item(f"rd.429.{group}", f"Hay 429 en {_endpoint_label(group)}. {_endpoint_hint(group).capitalize()} y repite.", "principal", targets, {"429_by_group": by_group}))
    elif int(rate.get("cooldowns_429") or 0):
        out.append(item("rd.429.global", 'Hay pausa 429 general. Sube "Pausa 429" si se repite.', "principal", ["rd_api_429_cooldown_sec"], {"cooldowns_429": rate.get("cooldowns_429")}))

    if int(cleanup.get("pending") or 0) or int(cleanup.get("leftover") or 0):
        out.append(item("rd.cleanup.pending", 'Limpieza pendiente. Sube "Borrar" o "Pausa endpoint" y repite.', "secundario", ["rd_delete_min_interval_sec", "rd_endpoint_429_cooldown_sec"], cleanup))

    if int(rd_counts.get("RD_ERROR") or 0) or int(rd_counts.get("RD_ERROR_TEMPORAL") or 0):
        out.append(item("rd.errors.present", "Hay avisos RD. Repite prueba o mira caja negra antes de tocar velocidad.", "ajuste", [], rd_counts))

    if not out:
        waits = int(rate.get("waits_total") or 0)
        if waits:
            out.append(item("rd.clean.with_waits", 'RD no protesta. Si quieres apurar, baja "Meter magnet" 0.05s y repite.', "principal", ["rd_addmagnet_min_interval_sec"], {"waits_total": waits}))
        else:
            out.append(item("rd.clean.no_change", "No tocar ajustes. RD respondió limpio.", "ok", [], {}))
    return out[:3]


def _summary(events: list[dict[str, Any]], summary_file: dict[str, Any]) -> dict[str, Any]:
    rate = _data(_last(events, "rd_rate_summary"))
    pacer = _data(_last(events, "rd_endpoint_pacer_summary"))
    cleanup = _data(_last(events, "rd_cleanup_final_end"))
    active_before = _first_data(events, "rd_active_count_before", "rd_slots_refresh")
    active_after = _last_data(events, "rd_active_count_after", "rd_slots_refresh")
    rd_counts = _data(_last(events, "rd_verify_batch_end") or _last(events, "rd_check_summary"))
    queue_item = _data(_last(events, "rd_verify_queue_done_item"))
    queue_start = _data(_last(events, "rd_verify_queue_start"))
    payload = summary_file.get("payload") if isinstance(summary_file.get("payload"), dict) else {}

    total = int(queue_item.get("total") or queue_start.get("verifying") or rd_counts.get("total") or 0)
    done = int(queue_item.get("done") or 0)
    status_counts = {key: int(rd_counts.get(key, 0) or 0) for key in ("RD_OK", "NO_INSTANT", "PACK_SIN_COINCIDENCIA", "RD_FAIL", "RD_ERROR", "RD_ERROR_TEMPORAL") if key in rd_counts}
    http_429 = pacer.get("429_by_group") if isinstance(pacer.get("429_by_group"), dict) else {}
    calls_by_group = pacer.get("calls_by_group") if isinstance(pacer.get("calls_by_group"), dict) else {}
    waits_by_group = pacer.get("waits_by_group") if isinstance(pacer.get("waits_by_group"), dict) else {}

    result = {
        "run": {
            "status": summary_file.get("status"),
            "query": payload.get("query"),
            "pages": payload.get("pages"),
            "mode": payload.get("mode"),
            "elapsed_sec": summary_file.get("elapsed_sec"),
        },
        "progress": {"done": done, "total": total, "active": queue_item.get("active")},
        "rd_counts": status_counts,
        "rate": {
            "api_calls_total": rate.get("api_calls_total", 0),
            "max_window_count": rate.get("max_window_count", 0),
            "max_burst_count": rate.get("max_burst_count", 0),
            "cooldowns_429": rate.get("cooldowns_429", 0),
            "per_min": rate.get("per_min") or queue_start.get("config", {}).get("rd_api_rate_limit_per_min") if isinstance(queue_start.get("config"), dict) else rate.get("per_min"),
            "burst": rate.get("burst") or queue_start.get("config", {}).get("rd_api_rate_limit_burst") if isinstance(queue_start.get("config"), dict) else rate.get("burst"),
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
        "active_count": {
            "before": {
                "nb": active_before.get("nb"),
                "limit": active_before.get("limit"),
                "free": active_before.get("free"),
            },
            "after": {
                "nb": active_after.get("nb"),
                "limit": active_after.get("limit"),
                "free": active_after.get("free"),
            },
        },
        "diagnostic_status": summary_file.get("diagnostic_status"),
        "operation_status": summary_file.get("operation_status"),
        "elapsed_sec": summary_file.get("elapsed_sec"),
        "updated_at": summary_file.get("updated_at"),
        "translator_version": TRANSLATOR_VERSION,
    }
    result["advice"] = _advice(result)
    return result


def build_rd_follow(trace_id: str, after: int = 0, max_lines: int = 90, kind: str = "job") -> dict[str, Any]:
    folder = trace_folder(kind, trace_id)
    events = _read_events(folder / "events.jsonl")
    summary_file = _read_json(folder / "summary.json")
    started_at = _job_started_at(events, summary_file)
    cursor = len(events)
    after = max(0, min(int(after or 0), cursor))

    scan = events if after == 0 else events[after:]

    lines: list[dict[str, Any]] = []
    seen_summary: set[tuple[str, str]] = set()
    for record in scan:
        event = str(record.get("event") or "")
        if event not in USEFUL_EVENTS and not event.startswith(("rd_", "JOB_")):
            continue
        line = _event_to_line(record, started_at)
        if line:
            key = (str(line.get("kind") or ""), str(line.get("text") or ""))
            if line.get("kind") == "summary" and key in seen_summary:
                continue
            if line.get("kind") == "summary":
                seen_summary.add(key)
            if not lines or lines[-1].get("text") != line.get("text"):
                lines.append(line)

    if after == 0 and len(lines) > max_lines:
        lines = lines[-max_lines:]
    elif len(lines) > max_lines:
        lines = lines[:max_lines]

    return {
        "job_id": trace_id,
        "trace_id": trace_id,
        "trace_kind": kind,
        "translator_version": TRANSLATOR_VERSION,
        "cursor": cursor,
        "has_diagnostics": bool(events),
        "summary": _summary(events, summary_file),
        "lines": lines,
    }


def build_rd_event_detail(trace_id: str, event_id: str, kind: str = "rd_test") -> dict[str, Any] | None:
    folder = trace_folder(kind, trace_id)
    wanted = str(event_id or "").strip()
    if not wanted:
        return None
    for record in _read_events(folder / "events.jsonl"):
        if str(record.get("event_id") or "") == wanted or str(record.get("seq") or "") == wanted:
            return {
                "trace_id": trace_id,
                "trace_kind": kind,
                "translator_version": TRANSLATOR_VERSION,
                "event": record,
            }
    return None
