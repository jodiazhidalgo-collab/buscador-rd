from __future__ import annotations

import base64
import http.cookiejar
import json
import urllib.parse
import urllib.request
import uuid
from typing import Any

from ._send_tracking import _elapsed, _link_kind, _link_ref, _short, safe_filename, trace_download
from .results import normalize_infohash


def qbit_login(base: str, user: str, password: str):
    base = base.rstrip("/")
    auth_raw = f"{user}:{password}".encode("utf-8")
    basic = "Basic " + base64.b64encode(auth_raw).decode("ascii")
    header_sets = [
        {"User-Agent": "BTDiggRD/1.0", "Content-Type": "application/x-www-form-urlencoded"},
        {
            "User-Agent": "BTDiggRD/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": base,
            "Referer": base + "/",
            "Authorization": basic,
        },
    ]
    last_error = None
    for headers in header_sets:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        body = urllib.parse.urlencode({"username": user, "password": password}).encode("utf-8")
        req = urllib.request.Request(base + "/api/v2/auth/login", data=body, headers=headers, method="POST")
        try:
            with opener.open(req, timeout=20) as response:
                text = response.read().decode("utf-8", errors="replace").strip()
            if text in ("Ok.", "Ok", ""):
                return opener, basic
            last_error = f"login no aceptado: {text[:120]}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    raise RuntimeError(last_error or "login qBittorrent fallÃ³")


def qbit_add_url(base: str, user: str, password: str, url: str, target: dict[str, str], is_rdt: bool = False, trace_id: str = "", engine_label: str = "qBittorrent") -> str:
    base = base.rstrip("/")
    started = _elapsed_start()
    trace_download(trace_id, f"{engine_label}_ADD_URL_START", base=base, destino=target.get("key"), savepath=target["rdt_savepath"] if is_rdt else target["qbt_savepath"], link_type=_link_kind(url), link_ref=_link_ref(url))
    try:
        opener, basic = qbit_login(base, user, password)
    except Exception as exc:
        trace_download(trace_id, f"{engine_label}_LOGIN_FAIL", elapsed=_elapsed(started), error=f"{type(exc).__name__}: {exc}")
        raise
    trace_download(trace_id, f"{engine_label}_LOGIN_OK", elapsed=_elapsed(started))
    payload = {
        "urls": url,
        "category": target["key"],
        "savepath": target["rdt_savepath"] if is_rdt else target["qbt_savepath"],
        "paused": "false",
        "stopped": "false",
        "contentLayout": "Original",
        "autoTMM": "false",
    }
    body = urllib.parse.urlencode(payload).encode("utf-8")
    response = _qbit_post_add(opener, basic, base, body, "application/x-www-form-urlencoded", trace_id=trace_id, engine_label=engine_label)
    trace_download(trace_id, f"{engine_label}_ADD_URL_OK", elapsed=_elapsed(started), response=_short(response, 160))
    return response


def qbit_add_torrent_bytes(base: str, user: str, password: str, raw: bytes, filename: str, target: dict[str, str], is_rdt: bool = False, trace_id: str = "", engine_label: str = "qBittorrent") -> str:
    base = base.rstrip("/")
    started = _elapsed_start()
    trace_download(trace_id, f"{engine_label}_ADD_TORRENT_START", base=base, destino=target.get("key"), savepath=target["rdt_savepath"] if is_rdt else target["qbt_savepath"], filename=filename, bytes=len(raw or b""))
    try:
        opener, basic = qbit_login(base, user, password)
    except Exception as exc:
        trace_download(trace_id, f"{engine_label}_LOGIN_FAIL", elapsed=_elapsed(started), error=f"{type(exc).__name__}: {exc}")
        raise
    trace_download(trace_id, f"{engine_label}_LOGIN_OK", elapsed=_elapsed(started))
    boundary = "----BTDiggRD" + uuid.uuid4().hex
    fields = {
        "category": target["key"],
        "savepath": target["rdt_savepath"] if is_rdt else target["qbt_savepath"],
        "paused": "false",
        "stopped": "false",
        "contentLayout": "Original",
        "autoTMM": "false",
    }
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")
    safe_name = safe_filename(filename, "btdigg") + ".torrent"
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        (
            f'Content-Disposition: form-data; name="torrents"; filename="{safe_name}"\r\n'
            "Content-Type: application/x-bittorrent\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(raw)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    response = _qbit_post_add(opener, basic, base, body, f"multipart/form-data; boundary={boundary}", content_length=len(body), trace_id=trace_id, engine_label=engine_label)
    trace_download(trace_id, f"{engine_label}_ADD_TORRENT_OK", elapsed=_elapsed(started), response=_short(response, 160))
    return response


def _qbit_post_add(opener, basic: str, base: str, body: bytes, content_type: str, content_length: int | None = None, trace_id: str = "", engine_label: str = "qBittorrent") -> str:
    header_sets = [
        {"User-Agent": "BTDiggRD/1.0", "Content-Type": content_type},
        {
            "User-Agent": "BTDiggRD/1.0",
            "Content-Type": content_type,
            "Origin": base,
            "Referer": base + "/",
            "Authorization": basic,
        },
    ]
    if content_length is not None:
        for headers in header_sets:
            headers["Content-Length"] = str(content_length)
    last_error = None
    for attempt, headers in enumerate(header_sets, 1):
        req = urllib.request.Request(base + "/api/v2/torrents/add", data=body, headers=headers, method="POST")
        try:
            trace_download(trace_id, f"{engine_label}_POST_ADD_ATTEMPT", attempt=attempt, content_type=content_type.split(";")[0], bytes=len(body or b""))
            with opener.open(req, timeout=35) as response:
                return response.read().decode("utf-8", errors="replace").strip()
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            trace_download(trace_id, f"{engine_label}_POST_ADD_ATTEMPT_FAIL", attempt=attempt, error=last_error)
    raise RuntimeError(last_error or "qBittorrent no aceptÃ³ la descarga")


def client_info_by_hash(base: str, user: str, password: str, torrent_hash: str, trace_id: str = "", engine_label: str = "qBittorrent") -> tuple[dict[str, Any] | None, bool]:
    hash_value = normalize_infohash(torrent_hash)
    if not hash_value:
        trace_download(trace_id, f"{engine_label}_INFO_SKIP", reason="hash invalido", hash=torrent_hash or "")
        return None, False
    base = base.rstrip("/")
    started = _elapsed_start()
    try:
        opener, basic = qbit_login(base, user, password)
        url = base + "/api/v2/torrents/info?" + urllib.parse.urlencode({"hashes": hash_value})
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "BTDiggRD/1.0", "Authorization": basic},
            method="GET",
        )
        with opener.open(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace") or "[]")
        info = data[0] if isinstance(data, list) and data else None
        trace_download(
            trace_id,
            f"{engine_label}_INFO_BY_HASH_OK",
            hash=hash_value,
            found=bool(info),
            state=(info or {}).get("state") if isinstance(info, dict) else "",
            progress=(info or {}).get("progress") if isinstance(info, dict) else "",
            elapsed=_elapsed(started),
        )
        return (info if isinstance(info, dict) else None), True
    except Exception as exc:
        trace_download(trace_id, f"{engine_label}_INFO_BY_HASH_FAIL", hash=hash_value, elapsed=_elapsed(started), error=f"{type(exc).__name__}: {exc}")
        return None, False


def client_delete_by_hash(base: str, user: str, password: str, torrent_hash: str, delete_files: bool = False, trace_id: str = "", engine_label: str = "qBittorrent", why: str = "") -> bool:
    hash_value = normalize_infohash(torrent_hash)
    if not hash_value:
        return False
    base = base.rstrip("/")
    try:
        opener, basic = qbit_login(base, user, password)
        body = urllib.parse.urlencode({"hashes": hash_value, "deleteFiles": "true" if delete_files else "false"}).encode("utf-8")
        req = urllib.request.Request(
            base + "/api/v2/torrents/delete",
            data=body,
            headers={"User-Agent": "BTDiggRD/1.0", "Authorization": basic, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with opener.open(req, timeout=20) as response:
            response.read()
        trace_download(trace_id, f"{engine_label}_DELETE_BY_HASH_OK", hash=hash_value, delete_files=delete_files, why=why)
        return True
    except Exception as exc:
        trace_download(trace_id, f"{engine_label}_DELETE_BY_HASH_FAIL", hash=hash_value, why=why, error=f"{type(exc).__name__}: {exc}")
        return False


def _elapsed_start() -> float:
    import time

    return time.monotonic()
