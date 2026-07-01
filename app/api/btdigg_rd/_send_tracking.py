from __future__ import annotations

import re
import time
import urllib.parse
from typing import Any

from .blackbox import download_event as blackbox_download_event


def log_download(line: str) -> None:
    return None


def _elapsed(start: float) -> str:
    return f"{time.monotonic() - start:.2f}s"


def _short(value: Any, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text if len(text) <= limit else text[:limit] + "..."


def hash_from_magnet(link: str) -> str:
    match = re.search(r"btih:([a-zA-Z0-9]{32,40})", str(link or ""), re.I)
    return match.group(1).lower() if match else ""


def _link_kind(link: str) -> str:
    if str(link or "").startswith("magnet:"):
        return "magnet"
    if str(link or "").startswith(("http://", "https://")):
        return "url"
    return "desconocido"


def _link_ref(link: str) -> str:
    value = str(link or "")
    torrent_hash = hash_from_magnet(value)
    if torrent_hash:
        return f"btih:{torrent_hash}"
    if value.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(value)
        path = parsed.path or "/"
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    return _short(value, 120)


def trace_download(trace_id: str, step: str, **data: Any) -> None:
    trace_id = str(trace_id or "sin_trace")
    blackbox_download_event(trace_id, step, **data)
    parts = []
    for key, value in data.items():
        if value is None:
            continue
        if any(secret in key.lower() for secret in ("pass", "token", "authorization", "auth")):
            continue
        parts.append(f"{key}={_short(value)!r}")
    suffix = (" " + " ".join(parts)) if parts else ""
    log_download(f"TRACE {trace_id} {step}{suffix}")


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _int_value(value: Any) -> int:
    try:
        if value in ("", None):
            return 0
        return int(float(str(value).replace(",", ".").strip()))
    except Exception:
        return 0


def safe_filename(value: Any, fallback: str = "btdigg") -> str:
    name = clean_text(value) or fallback
    name = re.sub(r'[\\/:*?"<>|]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:140].strip(" ._-") or fallback
