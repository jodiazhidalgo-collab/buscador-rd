from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ._send_tracking import log_download, trace_download
from .config import BTDIGG_TOKEN_FILE, DATA, REAL_DEBRID_API


def rd_token() -> str:
    for key in ("REAL_DEBRID_API_KEY", "REAL_DEBRID_TOKEN", "RD_API_KEY", "RD_TOKEN"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    for path in (BTDIGG_TOKEN_FILE, DATA / "rd_token.txt", DATA / "real_debrid_token.txt"):
        try:
            if path.exists():
                value = path.read_text(encoding="utf-8", errors="ignore").strip()
                if value and not value.upper().startswith("PON_AQUI"):
                    return value
        except Exception:
            pass
    return ""


def rd_api(method: str, path: str, token: str, data: dict[str, Any] | None = None, raw: bytes | None = None, content_type: str | None = None, timeout: int = 10) -> Any:
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "BTDiggRD/RDPrecheck"}
    body = None
    if raw is not None:
        body = raw
        if content_type:
            headers["Content-Type"] = content_type
    elif data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(REAL_DEBRID_API.rstrip("/") + path, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            output = response.read().decode("utf-8", errors="replace").strip()
        if not output:
            return None
        try:
            return json.loads(output)
        except Exception:
            return output
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"RD HTTP {exc.code}: {body_text}")
    except Exception as exc:
        raise RuntimeError(f"RD {type(exc).__name__}: {exc}")


def rd_delete(torrent_id: str, token: str, why: str = "", trace_id: str = "") -> None:
    if not torrent_id:
        return
    try:
        trace_download(trace_id, "RD_DELETE_START", id=torrent_id, why=why)
        rd_api("DELETE", f"/torrents/delete/{torrent_id}", token, timeout=10)
        trace_download(trace_id, "RD_DELETE_OK", id=torrent_id, why=why)
        log_download(f"RD PREFILTRO delete id={torrent_id} why={why}")
    except Exception as exc:
        trace_download(trace_id, "RD_DELETE_FAIL", id=torrent_id, why=why, error=str(exc)[:180])
        log_download(f"RD PREFILTRO delete fallo id={torrent_id} why={why} error={str(exc)[:180]}")


def rd_select_files(torrent_id: str, token: str, files_spec: str = "all", trace_id: str = "") -> None:
    files = str(files_spec or "").strip() or "all"
    last_error = ""
    for attempt in range(1, 7):
        try:
            trace_download(trace_id, "RD_SELECT_FILES_START", id=torrent_id, files=files, attempt=attempt)
            rd_api("POST", f"/torrents/selectFiles/{torrent_id}", token, data={"files": files}, timeout=35)
            trace_download(trace_id, "RD_SELECT_FILES_OK", id=torrent_id, files=files, attempt=attempt)
            return
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            trace_download(trace_id, "RD_SELECT_FILES_FAIL", id=torrent_id, files=files, attempt=attempt, error=last_error[:180])
            time.sleep(2)
    raise RuntimeError(last_error or "Real-Debrid no acepto selectFiles")


def rd_select_all(torrent_id: str, token: str, trace_id: str = "") -> None:
    rd_select_files(torrent_id, token, "all", trace_id=trace_id)
