from __future__ import annotations

from typing import Any

import requests

from ._send_tracking import _int_value
from .results import normalize_infohash


RDT_NATIVE_RETRY_CODES = {408, 429, 500, 502, 503, 504}
RDT_BLOCKED_PENDING = (
    "not yet added to provider",
    "torrent waiting for file selection",
    "waiting_files_selection",
)


def rdt_native_text(response: requests.Response | None, limit: int = 240) -> str:
    if response is None:
        return ""
    try:
        return str(response.text or "").strip()[:limit]
    except Exception:
        return ""


def rdt_native_error(label: str, response: requests.Response | None) -> str:
    if response is None:
        return f"{label}: sin respuesta"
    text = rdt_native_text(response)
    return f"{label} HTTP {response.status_code}: {text}"


def rdt_native_retryable(response: requests.Response | None) -> bool:
    return bool(response is not None and response.status_code in RDT_NATIVE_RETRY_CODES)


def rdt_native_retry_delay(response: requests.Response | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        try:
            if retry_after:
                return max(1.0, min(12.0, float(retry_after)))
        except Exception:
            pass
    return min(8.0, 1.0 + (attempt * 1.5))


def rdt_native_settings(category: str, manual_files: str = "") -> dict[str, Any]:
    cat = str(category or "movies").strip() or "movies"
    manual = str(manual_files or "").strip()
    return {
        "category": cat,
        "hostDownloadAction": 0,
        "downloadAction": 2 if manual else 0,
        "finishedAction": 1,
        "finishedActionDelay": 0,
        "downloadMinSize": 0,
        "includeRegex": "",
        "excludeRegex": "",
        "downloadManualFiles": manual or None,
        "priority": 0,
        "torrentRetryAttempts": 1,
        "downloadRetryAttempts": 3,
        "deleteOnError": 0,
        "lifetime": 0,
        "downloadClient": 0,
        "type": 0,
    }


def rdt_native_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("items", "torrents", "data", "results"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def rdt_native_row_id(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    for key in ("torrentId", "id", "Id", "torrent_id"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def rdt_native_row_hash(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    for key in ("hash", "hashString", "infoHash", "info_hash", "rdHash"):
        value = normalize_infohash(row.get(key))
        if value:
            return value
    return ""


def rdt_native_row_status(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    for key in ("statusText", "status", "Status", "rdStatusRaw", "rdStatus"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def rdt_native_row_phase(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return "missing"
    status = " ".join(
        str(row.get(key) or "").strip()
        for key in ("statusText", "status", "Status", "rdStatusRaw", "rdStatus", "error", "errorMessage")
    ).lower()
    downloads = _int_value(row.get("downloadsCount") or row.get("downloads") or 0)
    files_selected = _int_value(row.get("filesSelected") or row.get("selectedFiles") or 0)
    if "error" in status or "failed" in status:
        return "error"
    if any(token in status for token in RDT_BLOCKED_PENDING):
        return "blocked_pending"
    if any(token in status for token in ("finished", "downloaded", "complete", "completed")):
        return "finished"
    if downloads > 0 or any(token in status for token in ("downloading", "downloading metadata")):
        return "healthy_started"
    if files_selected > 0:
        return "selected_only"
    return "pending_other"


def rdt_native_phase_is_ready(phase: str) -> bool:
    return str(phase or "") in {"healthy_started", "finished"}
