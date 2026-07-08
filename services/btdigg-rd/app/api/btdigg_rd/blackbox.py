from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import BTDIGG_CONFIG_FILE, DIAGNOSTICS_DIR, RD_TEST_DIAGNOSTICS_DIR

SECRET_MARKERS = ("token", "pass", "password", "authorization", "auth", "apikey", "api_key")
PRIVATE_VALUE_MARKERS = ("magnet", "link", "url", "unrestricted", "download_url")
TEXT_LIMIT = 600
LIST_LIMIT = 40
TRACE_LOCK_TIMEOUT_SEC = 10.0
TRACE_LOCK_STALE_SEC = 60.0

CONFIG_SNAPSHOT_KEYS = (
    "version",
    "default_pages",
    "default_mode",
    "safe_max_pages_when_zero",
    "max_results_to_show",
    "hide_non_working_results",
    "screen_hide_qbit_not_working",
    "strict_query_prefilter",
    "strict_query_prefilter_keep_discarded_in_exports",
    "min_size_gb",
    "max_size_gb",
    "qbit_probe_enabled",
    "qbit_probe_only_non_rd_working",
    "qbit_probe_max_candidates",
    "qbit_probe_parallel_workers",
    "qbit_probe_wait_sec",
    "qbit_probe_poll_sec",
    "qbit_delete_probe_after",
    "qbit_require_same_file_match",
    "qbit_same_file_min_ratio",
    "qbit_show_metadata_only",
    "qbit_show_irrelevant_skipped",
    "qbit_probe_category",
    "qbit_probe_save_path",
    "qbit_host",
    "verify_candidates_when_api_off",
    "verify_instant_results_with_addmagnet",
    "verify_max_candidates",
    "verify_wait_attempts",
    "verify_wait_sec",
    "rd_verify_parallel_workers",
    "rd_fast_mode_enabled",
    "rd_verify_queue_enabled",
    "rd_api_rate_limit_per_min",
    "rd_api_rate_limit_burst",
    "rd_api_429_cooldown_sec",
    "rd_mass_429_cooldown_sec",
    "rd_mass_429_groups_threshold",
    "rd_mass_429_total_threshold",
    "rd_mass_429_window_sec",
    "rd_429_retry_attempts",
    "rd_endpoint_pacer_enabled",
    "rd_endpoint_adaptive_429_enabled",
    "rd_addmagnet_min_interval_sec",
    "rd_selectfiles_min_interval_sec",
    "rd_delete_min_interval_sec",
    "rd_info_min_interval_sec",
    "rd_addmagnet_max_concurrent",
    "rd_selectfiles_max_concurrent",
    "rd_delete_max_concurrent",
    "rd_info_max_concurrent",
    "rd_endpoint_429_cooldown_sec",
    "rd_endpoint_429_min_interval_multiplier",
    "rd_endpoint_429_min_interval_max_sec",
    "rd_fast_discard_enabled",
    "rd_fast_discard_message_match_enabled",
    "rd_fast_discard_zero_progress_enabled",
    "rd_fast_discard_dead_status_enabled",
    "rd_cleanup_final_skip_already_deleted",
    "rd_temp_error_retries",
    "rd_temp_error_retry_sec",
    "cleanup_failed_verifications",
    "cleanup_unselected_verified",
    "rd_check_existing_torrents",
    "rd_existing_torrents_limit",
    "rd_rescue_enabled",
    "rd_rescue_max_candidates",
    "rd_rescue_only_if_no_rd_ok",
    "rd_rescue_min_title_ratio",
    "browser_preferred",
    "browser_wait_after_load_sec",
    "browser_delay_between_pages_sec",
    "browser_close_when_done",
    "delay_between_btdigg_pages_sec",
    "delay_after_btdigg_429_sec",
    "stop_btdigg_on_429",
    "request_timeout_sec",
    "torznab_enabled",
    "torznab_min_seeders",
    "torznab_max_results",
    "write_exports",
    "write_last_links_txt",
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _safe_name(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    return clean[:120] or "sin_id"


def _kind_from_folder(folder: Path) -> str:
    collection = folder.parent.parent.name
    if collection == "rd_tests":
        return "rd_test"
    if collection.endswith("s"):
        return collection[:-1]
    return collection or "job"


def _collection_for_kind(kind: str) -> str:
    clean = str(kind or "job").strip().lower().replace("-", "_")
    if clean in {"rd_test", "rd_tests", "rd_tuning"}:
        return "rd_tests"
    if clean in {"download", "downloads"}:
        return "downloads"
    if clean in {"voice", "voices", "micro", "microphone"}:
        return "voice"
    return "jobs"


def _event_count(path: Path) -> int:
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except Exception:
        return 0


def _acquire_event_lock(events_path: Path) -> Path | None:
    lock_dir = events_path.with_name("events.lock")
    try:
        lock_dir.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    deadline = time.monotonic() + TRACE_LOCK_TIMEOUT_SEC
    while True:
        try:
            lock_dir.mkdir()
            return lock_dir
        except FileExistsError:
            try:
                if time.time() - lock_dir.stat().st_mtime > TRACE_LOCK_STALE_SEC:
                    lock_dir.rmdir()
                    continue
            except Exception:
                pass
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)
        except Exception:
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)


def _release_event_lock(lock_dir: Path | None) -> None:
    if not lock_dir:
        return
    try:
        lock_dir.rmdir()
    except Exception:
        pass


def _next_seq_locked(events_path: Path) -> int:
    seq_path = events_path.with_name("events.seq")
    try:
        current = int((seq_path.read_text(encoding="utf-8").strip() or "0"))
    except Exception:
        current = 0
    seq = max(current, _event_count(events_path)) + 1
    try:
        seq_path.write_text(f"{seq}\n", encoding="utf-8")
    except Exception:
        pass
    return seq


def _next_seq(folder: Path) -> int:
    events_path = folder / "events.jsonl"
    lock_dir = _acquire_event_lock(events_path)
    try:
        return _next_seq_locked(events_path)
    finally:
        _release_event_lock(lock_dir)


def _redact(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(marker in lowered for marker in SECRET_MARKERS):
        return "***"
    if any(marker in lowered for marker in PRIVATE_VALUE_MARKERS):
        if isinstance(value, str) and value.strip():
            return "***"
        if isinstance(value, (list, tuple, set)):
            return ["***" for _ in list(value)[:LIST_LIMIT]]
    return _clean(value)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _redact(str(k), v) for k, v in list(value.items())[:LIST_LIMIT]}
    if isinstance(value, (list, tuple, set)):
        return [_clean(v) for v in list(value)[:LIST_LIMIT]]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > TEXT_LIMIT:
            return value[:TEXT_LIMIT] + "...[truncated]"
        return value
    return str(value)[:TEXT_LIMIT]


def _config_snapshot() -> dict[str, Any]:
    path = BTDIGG_CONFIG_FILE
    try:
        cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception as exc:
        return {"read_error": type(exc).__name__}
    if not isinstance(cfg, dict):
        return {"read_error": "config_not_dict"}
    snapshot = {key: cfg.get(key) for key in CONFIG_SNAPSHOT_KEYS if key in cfg}
    snapshot["source"] = str(path)
    return _clean(snapshot)


def _phase(event: str) -> str:
    lower = event.lower()
    if lower.startswith(("qbt", "qbit")) or "qbittorrent" in lower:
        return "qbittorrent"
    if lower.startswith("rdt") or "rdt" in lower:
        return "rdt-client"
    if lower.startswith("rd") or "real_debrid" in lower or "real-debrid" in lower:
        return "real-debrid"
    if lower.startswith(("btdigg", "browser", "dom", "extract")):
        return "btdigg"
    if lower.startswith(("voice", "speech", "micro")):
        return "voice"
    if lower.startswith(("download", "route", "contract", "client", "cleanup", "tracking")):
        return "download"
    if lower.startswith(("job", "process", "web", "command")):
        return "web"
    if lower.startswith(("export", "history", "editor")):
        return "search"
    return "general"


def _problem_counter_total(data: dict[str, Any]) -> float:
    total = 0.0
    for key, value in (data or {}).items():
        key_text = str(key).lower()
        if not any(marker in key_text for marker in ("error", "fail", "api_off", "temporal")):
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            total += float(value)
            continue
        if isinstance(value, str):
            try:
                total += float(value.replace(",", "."))
            except ValueError:
                pass
    return total


def _event_is_ok(event: str) -> bool:
    lower = str(event or "").lower()
    return lower.endswith(("_ok", "_done", "_registered", "_selected", "_resolved")) or lower in {
        "job_finished_ok",
        "download_end_ok",
    }


def _http_code(data: dict[str, Any]) -> int | None:
    value = data.get("code") or data.get("status_code")
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _expected_rd_problem(event: str, data: dict[str, Any]) -> bool:
    lower_event = str(event or "").lower()
    text = json.dumps(_clean(data), ensure_ascii=False, default=str).lower()
    code = _http_code(data)
    if "disabled_endpoint" in text and lower_event in {"rd_api_http_error", "rd_cache_api_disabled"}:
        return True
    if code in {429, 451} and lower_event.startswith("rd"):
        return True
    if lower_event == "rd_verify_error" and ("http 451" in text or "infringing_file" in text):
        return True
    if lower_event == "rd_delete_torrent_error" and ("unknown_ressource" in text or "unknown_resource" in text):
        return True
    return False


def _http_level(event: str, data: dict[str, Any]) -> str | None:
    code = _http_code(data)
    if code is None:
        return None
    if _expected_rd_problem(event, data):
        return "warn"
    if code >= 500:
        return "error"
    if code >= 400:
        return "warn"
    return None


def _has_explicit_error_value(data: dict[str, Any]) -> bool:
    for key, value in (data or {}).items():
        key_text = str(key).lower()
        if key_text != "error":
            continue
        if value is None or value is False:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return True
    return False


def _level(event: str, data: dict[str, Any]) -> str:
    lower_event = str(event or "").lower()
    if _event_is_ok(event):
        return "info"
    if lower_event.endswith("_errors") and str(data.get("total", "")).strip() in {"0", "0.0"}:
        return "info"
    if "skipped" in lower_event and str(data.get("reason", "")).lower() in {"disabled", "solo_enlaces_directos"}:
        return "info"
    if lower_event in {"rd_verify_batch_end", "rd_check_summary"}:
        return "warn" if _problem_counter_total(data) > 0 else "info"
    level = _http_level(event, data)
    if level:
        return level
    if any(word in lower_event for word in ("fatal", "traceback", "exception")):
        return "error"
    if any(word in lower_event for word in ("error", "fail", "failed")):
        return "warn" if _expected_rd_problem(event, data) else "error"
    if "poll" in lower_event or "wait" in lower_event or "heartbeat" in lower_event or "tick" in lower_event:
        return "debug"
    if any(word in lower_event for word in ("warn", "retry", "rejected", "pending", "timeout")):
        return "warn"
    if data.get("ok") is False or _has_explicit_error_value(data):
        return "warn"
    return "info"


def _code(event: str, data: dict[str, Any], level: str) -> str | None:
    if level not in {"warn", "error"}:
        return None
    category = _phase(event).upper().replace("-", "_")
    http_code = data.get("code") or data.get("status") or data.get("status_code")
    if isinstance(http_code, int) or (isinstance(http_code, str) and http_code.isdigit()):
        return f"{category}.HTTP_{http_code}"
    clean_event = re.sub(r"[^A-Z0-9]+", "_", event.upper()).strip("_")
    return f"{category}.{clean_event or 'EVENT'}"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
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


def _parse_json_text(value: Any) -> Any:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _last_event(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for record in reversed(events):
        if record.get("event") == name:
            return record
    return None


def _first_event(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for record in events:
        if record.get("event") == name:
            return record
    return None


def _summary_status(operation_status: str | None, counts: dict[str, int]) -> str:
    if operation_status in {"ok", "error", "rejected", "cancelled"}:
        return operation_status
    if int(counts.get("error", 0)) > 0:
        return "error"
    if int(counts.get("warn", 0)) > 0:
        return "warning"
    return "running"


def _diagnostic_status(counts: dict[str, int]) -> str:
    if int(counts.get("error", 0)) > 0:
        return "error"
    if int(counts.get("warn", 0)) > 0:
        return "warning"
    return "ok"


def _derive_job_summary(events: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    job_started = _first_event(events, "JOB_STARTED")
    payload = ((job_started or {}).get("data") or {}).get("payload") or {}
    if isinstance(payload, dict):
        for key in ("query", "pages", "mode", "min_gb", "module", "action"):
            if payload.get(key) not in (None, ""):
                summary[key] = payload.get(key)

    command = _last_event(events, "COMMAND_PREPARED")
    if command:
        data = command.get("data") or {}
        summary["command"] = {"cmd": data.get("cmd"), "cwd": data.get("cwd")}

    config = _last_event(events, "CONFIG_SNAPSHOT")
    if config:
        data = config.get("data") or {}
        if isinstance(data.get("config_snapshot"), dict):
            summary["config_snapshot"] = data.get("config_snapshot")

    browser_end = _last_event(events, "browser_auto_search_end_dom") or _last_event(events, "btdigg_search_end")
    if browser_end:
        summary["btdigg_found"] = (browser_end.get("data") or {}).get("total")

    prefilter = _last_event(events, "prepare_after_query_prefilter")
    if prefilter:
        data = prefilter.get("data") or {}
        summary["query_prefilter"] = {k: data.get(k) for k in ("before", "after", "removed", "rescue", "terms") if k in data}

    rd_summary = _last_event(events, "rd_verify_batch_end") or _last_event(events, "rd_check_summary")
    if rd_summary:
        summary["real_debrid"] = rd_summary.get("data") or {}

    qbit_summary = _last_event(events, "qbt_probe_batch_end")
    if qbit_summary:
        summary["qbittorrent"] = qbit_summary.get("data") or {}

    working = _last_event(events, "prepare_after_working_filter")
    if working:
        data = working.get("data") or {}
        summary["working_filter"] = {k: data.get(k) for k in ("before", "after", "removed", "qbit_extras", "rd_valid") if k in data}

    exports = [record for record in events if record.get("event") == "export_results"]
    if exports:
        data = (exports[-1].get("data") or {}).copy()
        summary["export"] = {k: data.get(k) for k in ("total", "shown", "all_json", "top_txt") if k in data}
        if data.get("shown") is not None:
            summary["results_shown"] = data.get("shown")

    finished = _last_event(events, "JOB_FINISHED_OK") or _last_event(events, "JOB_FINISHED_CANCELLED") or _last_event(events, "JOB_FINISHED_ERROR")
    if finished:
        data = finished.get("data") or {}
        for key in ("exit_code", "results_count", "elapsed_sec"):
            if key in data:
                summary[key] = data.get(key)


def _derive_download_summary(events: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    click = _first_event(events, "DOWNLOAD_CLICK_RECEIVED")
    if click:
        data = click.get("data") or {}
        for key in ("title", "hash", "index", "module", "link_type", "link_ref", "remote"):
            if data.get(key) not in (None, ""):
                summary[key] = data.get(key)

    card = _last_event(events, "BTDIGG_SERVER_CARD_OK") or _last_event(events, "BTDIGG_HISTORY_CARD_OK")
    if card:
        data = card.get("data") or {}
        summary["card"] = {k: data.get(k) for k in ("source", "status", "hash", "title") if k in data}

    route = _last_event(events, "ROUTE_SELECTED") or _last_event(events, "ROUTE_DECIDED")
    if route:
        data = route.get("data") or {}
        summary["route"] = data.get("route")
        if data.get("engine"):
            summary["engine"] = data.get("engine")
        if data.get("reason"):
            summary["route_reason"] = data.get("reason")

    dest = _last_event(events, "DESTINATION_SELECTED")
    if dest:
        data = dest.get("data") or {}
        summary["destination"] = {k: data.get(k) for k in ("destino", "rdt_savepath", "qbt_savepath", "inbox") if k in data}

    qbit_add = _last_event(events, "qBittorrent_ADD_URL_OK")
    if qbit_add:
        data = qbit_add.get("data") or {}
        parsed = _parse_json_text(data.get("response"))
        summary["qbittorrent_add"] = parsed if isinstance(parsed, dict) else {"response": data.get("response")}

    rdt_id_event = _last_event(events, "RDT_NATIVE_NEW_ID_HASH_OK")
    if rdt_id_event:
        data = rdt_id_event.get("data") or {}
        summary["rdt_id"] = data.get("rdt_id")

    tracking = _last_event(events, "TRACKING_REGISTERED")
    if tracking:
        data = tracking.get("data") or {}
        summary["tracking"] = {k: data.get(k) for k in ("record_id", "tracking_file", "destino", "hash") if k in data}

    finished = _last_event(events, "DOWNLOAD_END_OK") or _last_event(events, "DOWNLOAD_END_PENDING") or _last_event(events, "DOWNLOAD_REJECTED")
    if finished:
        data = finished.get("data") or {}
        for key in ("engine", "route", "elapsed", "rdt_id", "status", "already_present"):
            if key in data:
                summary[key] = data.get(key)


def _rebuild_summary_from_events(folder: Path, updates: dict[str, Any] | None = None) -> None:
    events = _iter_jsonl(folder / "events.jsonl")
    if not events:
        return
    existing = _read_json(folder / "summary.json")
    counts = {"info": 0, "warn": 0, "error": 0, "debug": 0}
    phases: dict[str, int] = {}
    last_error_code = None
    last_motor_event = None
    for record in events:
        level = str(record.get("level") or "info")
        counts[level] = int(counts.get(level, 0)) + 1
        phase = str(record.get("phase") or "general")
        phases[phase] = int(phases.get(phase, 0)) + 1
        if record.get("source") == "motor":
            last_motor_event = record.get("event")
        if level == "error":
            last_error_code = record.get("code")

    summary = {
        "id": existing.get("id") or folder.name,
        "kind": existing.get("kind") or _kind_from_folder(folder),
        "started_at": existing.get("started_at") or events[0].get("ts"),
        "read_order": ["summary.json", "timeline.md", "warnings.jsonl", "errors.jsonl", "events.jsonl"],
        "counts": counts,
        "event_count": len(events),
        "phases": phases,
        "updated_at": events[-1].get("ts"),
        "last_event": events[-1].get("event"),
        "diagnostic_status": _diagnostic_status(counts),
    }
    for key in ("action", "payload", "config_snapshot"):
        if key in existing:
            summary[key] = existing[key]
    if last_motor_event:
        summary["last_motor_event"] = last_motor_event
    if last_error_code:
        summary["last_error_code"] = last_error_code

    if summary["kind"] in {"job", "rd_test"}:
        _derive_job_summary(events, summary)
    elif summary["kind"] == "download":
        _derive_download_summary(events, summary)

    if updates:
        clean_updates = _clean(updates)
        if "status" in clean_updates:
            summary["operation_status"] = clean_updates.pop("status")
        summary.update(clean_updates)
    else:
        summary["operation_status"] = existing.get("operation_status")

    summary["status"] = _summary_status(summary.get("operation_status"), counts)
    _write_json(folder / "summary.json", summary)


def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")


def _append_timeline(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = record.get("data") or {}
    detail = data.get("message") or data.get("error") or data.get("reason") or data.get("title") or ""
    detail = f" - {detail}" if detail else ""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"- {record['ts']} [{record['level']}] {record['phase']}::{record['event']}{detail}\n")


def _update_summary(folder: Path, record: dict[str, Any], updates: dict[str, Any] | None = None) -> None:
    summary_path = folder / "summary.json"
    summary = _read_json(summary_path)
    if not summary:
        summary = {
            "id": folder.name,
            "kind": _kind_from_folder(folder),
            "started_at": record["ts"],
            "status": "running",
            "read_order": ["summary.json", "timeline.md", "warnings.jsonl", "errors.jsonl", "events.jsonl"],
            "counts": {"info": 0, "warn": 0, "error": 0, "debug": 0},
        }
    counts = summary.setdefault("counts", {"info": 0, "warn": 0, "error": 0, "debug": 0})
    counts[record["level"]] = int(counts.get(record["level"], 0)) + 1
    summary["updated_at"] = record["ts"]
    summary["last_event"] = record["event"]
    if record["level"] == "error":
        summary["last_error_code"] = record.get("code")
    if updates:
        clean_updates = _clean(updates)
        if "status" in clean_updates:
            summary["operation_status"] = clean_updates.pop("status")
        summary.update(clean_updates)
    operation_status = summary.get("operation_status")
    summary["event_count"] = sum(int(v) for v in counts.values())
    summary["diagnostic_status"] = _diagnostic_status({k: int(v) for k, v in counts.items()})
    summary["status"] = _summary_status(operation_status, {k: int(v) for k, v in counts.items()})
    _write_json(summary_path, summary)


def _record(folder: Path, event: str, data: dict[str, Any] | None = None, updates: dict[str, Any] | None = None) -> dict[str, Any]:
    clean_data = _clean(data or {})
    level = _level(event, clean_data)
    events_path = folder / "events.jsonl"
    lock_dir = _acquire_event_lock(events_path)
    try:
        seq = _next_seq_locked(events_path)
        trace_kind = _kind_from_folder(folder)
        trace_id = folder.name
        ts = _now()
        record = {
            "ts": ts,
            "observed_ts": ts,
            "event_id": f"E{seq:06d}",
            "seq": seq,
            "trace_kind": trace_kind,
            "trace_id": trace_id,
            "event": event,
            "level": level,
            "phase": _phase(event),
            "code": _code(event, clean_data, level),
            "data": clean_data,
        }
        _append_jsonl(events_path, record)
        if level == "warn":
            _append_jsonl(folder / "warnings.jsonl", record)
        elif level == "error":
            _append_jsonl(folder / "errors.jsonl", record)
        _append_timeline(folder / "timeline.md", record)
        _update_summary(folder, record, updates)
        return record
    finally:
        _release_event_lock(lock_dir)


def trace_folder(kind: str, trace_id: str, day: str | None = None) -> Path:
    collection = _collection_for_kind(kind)
    base = RD_TEST_DIAGNOSTICS_DIR if collection == "rd_tests" else DIAGNOSTICS_DIR / collection
    return base / (day or _today()) / _safe_name(trace_id)


def trace_events_file(kind: str, trace_id: str) -> Path:
    folder = trace_folder(kind, trace_id)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return folder / "events.jsonl"


def job_folder(job_id: str) -> Path:
    return trace_folder("job", job_id)


def download_folder(trace_id: str) -> Path:
    return trace_folder("download", trace_id)


def rd_test_folder(run_id: str) -> Path:
    return trace_folder("rd_test", run_id)


def job_events_file(job_id: str) -> Path:
    return trace_events_file("job", job_id)


def rd_test_events_file(run_id: str) -> Path:
    return trace_events_file("rd_test", run_id)


def voice_folder(trace_id: str) -> Path:
    return trace_folder("voice", trace_id)


def voice_event(trace_id: str, event: str, status: str | None = None, **data: Any) -> None:
    if not trace_id:
        return
    updates = {"status": status} if status in {"ok", "error", "rejected", "cancelled"} else None
    try:
        folder = trace_folder("voice", trace_id)
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("warnings.jsonl", "errors.jsonl", "timeline.md"):
            (folder / name).touch(exist_ok=True)
        _record(folder, event, data, updates)
    except Exception:
        pass


def start_trace(kind: str, trace_id: str, action: str, payload: dict[str, Any] | None = None, meta: dict[str, Any] | None = None) -> Path:
    folder = trace_folder(kind, trace_id)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        snapshot = _config_snapshot()
        trace_kind = _kind_from_folder(folder)
        started_at = _now()
        base_doc = {
            "id": trace_id,
            "kind": trace_kind,
            "trace_kind": trace_kind,
            "trace_id": trace_id,
            "action": action,
            "payload": _clean(payload or {}),
            "meta": _clean(meta or {}),
            "config_snapshot": snapshot,
            "started_at": started_at,
            "status": "running",
            "read_order": ["summary.json", "timeline.md", "warnings.jsonl", "errors.jsonl", "events.jsonl"],
            "counts": {"info": 0, "warn": 0, "error": 0, "debug": 0},
        }
        _write_json(
            folder / "summary.json",
            base_doc,
        )
        _write_json(folder / "meta.json", base_doc)
        for name in ("warnings.jsonl", "errors.jsonl", "timeline.md"):
            (folder / name).touch(exist_ok=True)
        _record(folder, "JOB_STARTED", {"action": action, "payload": payload or {}, "trace_kind": trace_kind, "meta": meta or {}})
        _record(folder, "CONFIG_SNAPSHOT", {"config_snapshot": snapshot})
    except Exception:
        pass
    return folder


def trace_event(kind: str, trace_id: str, event: str, **data: Any) -> None:
    try:
        _record(trace_folder(kind, trace_id), event, data)
    except Exception:
        pass


def trace_command(kind: str, trace_id: str, cmd: list[str], cwd: Path | str) -> None:
    trace_event(kind, trace_id, "COMMAND_PREPARED", cmd=cmd, cwd=str(cwd))


def finish_trace(kind: str, trace_id: str, status: str, **data: Any) -> None:
    try:
        if status == "ok":
            event = "JOB_FINISHED_OK"
        elif status == "cancelled":
            event = "JOB_FINISHED_CANCELLED"
        else:
            event = "JOB_FINISHED_ERROR"
        folder = trace_folder(kind, trace_id)
        _record(folder, event, data, {"status": status})
        _rebuild_summary_from_events(folder, {"status": status, **data})
    except Exception:
        pass


def trace_error(kind: str, trace_id: str, event: str, error: Any, **data: Any) -> None:
    try:
        data["error"] = str(error)
        _record(trace_folder(kind, trace_id), event, data, {"status": "error"})
    except Exception:
        pass


def start_job(job_id: str, action: str, payload: dict[str, Any] | None = None) -> Path:
    return start_trace("job", job_id, action, payload)


def job_event(job_id: str, event: str, **data: Any) -> None:
    try:
        trace_event("job", job_id, event, **data)
    except Exception:
        pass


def job_command(job_id: str, cmd: list[str], cwd: Path | str) -> None:
    try:
        trace_command("job", job_id, cmd, cwd)
    except Exception:
        pass


def finish_job(job_id: str, status: str, **data: Any) -> None:
    finish_trace("job", job_id, status, **data)


def job_error(job_id: str, event: str, error: Any, **data: Any) -> None:
    trace_error("job", job_id, event, error, **data)


def start_rd_test(run_id: str, action: str, payload: dict[str, Any] | None = None, meta: dict[str, Any] | None = None) -> Path:
    return start_trace("rd_test", run_id, action, payload, meta)


def rd_test_event(run_id: str, event: str, **data: Any) -> None:
    trace_event("rd_test", run_id, event, **data)


def rd_test_command(run_id: str, cmd: list[str], cwd: Path | str) -> None:
    trace_command("rd_test", run_id, cmd, cwd)


def finish_rd_test(run_id: str, status: str, **data: Any) -> None:
    finish_trace("rd_test", run_id, status, **data)


def rd_test_error(run_id: str, event: str, error: Any, **data: Any) -> None:
    trace_error("rd_test", run_id, event, error, **data)


def download_event(trace_id: str, event: str, **data: Any) -> None:
    if not trace_id:
        return
    try:
        status = None
        lower = event.lower()
        if "end_ok" in lower or lower.endswith("_ok") or "sent_ok" in lower:
            status = "ok"
        elif "error" in lower or "fail" in lower:
            status = "error"
        elif "reject" in lower:
            status = "rejected"
        updates = {"status": status} if status else None
        folder = download_folder(trace_id)
        _record(folder, event, data, updates)
        if status:
            _rebuild_summary_from_events(folder, updates)
    except Exception:
        pass
