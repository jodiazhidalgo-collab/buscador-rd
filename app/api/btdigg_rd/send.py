from __future__ import annotations

from difflib import SequenceMatcher
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import requests
from flask import jsonify, request

from ._qbt_client import (
    _qbit_post_add,
    client_delete_by_hash,
    client_info_by_hash,
    qbit_add_torrent_bytes,
    qbit_add_url,
    qbit_login,
)
from ._send_contracts import (
    QBIT_REUSABLE_STATUSES,
    RD_REUSABLE_STATUSES,
    _payload_index,
    _truthy,
    _validate_btdigg_download_payload,
    _validate_btdigg_history_payload,
    build_btdigg_download_contract,
    decide_btdigg_download_route,
    trace_contract,
)
from ._send_manual_flow import handle_manual_magnet_flow, handle_manual_torrent_url_flow
from ._send_routing import dest, download_dest_from_title, title_has_tv_marker
from ._rd_client import rd_api, rd_delete, rd_select_all, rd_select_files, rd_token
from ._rdt_client import (
    RDT_BLOCKED_PENDING,
    RDT_NATIVE_RETRY_CODES,
    rdt_native_error,
    rdt_native_phase_is_ready,
    rdt_native_retry_delay,
    rdt_native_retryable,
    rdt_native_row_hash,
    rdt_native_row_id,
    rdt_native_row_phase,
    rdt_native_row_status,
    rdt_native_rows,
    rdt_native_settings,
    rdt_native_text,
)
from ._send_tracking import (
    _elapsed,
    _int_value,
    _link_kind,
    _link_ref,
    _short,
    hash_from_magnet,
    log_download,
    safe_filename,
    trace_download,
)
from .config import (
    QBIT_BASE,
    QBIT_PASS,
    QBIT_USER,
    RDT_BASE,
    RDT_PASS,
    RDT_USER,
    TRACKING_FILE,
)
from .results import normalize_infohash, resolve_btdigg_card_to_magnet
from .utils import read_json, write_json


VIDEO_EXT_RE = re.compile(r"\.(mkv|mp4|avi|mov|m4v|ts|m2ts|wmv)$", re.I)


def _norm_file_name(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip().lower()
    text = re.sub(r"^[./]+", "", text)
    text = re.sub(r"[^a-z0-9áéíóúüñ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_file_basename(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip().split("/")[-1]
    return _norm_file_name(text)


def get_bytes(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(str(url), headers={"User-Agent": "BTDiggRD/1.0"})
    with urllib.request.build_opener().open(req, timeout=timeout) as response:
        return response.read()


def rdt_file_prio(opener, base: str, download_hash: str, ids: list[str], priority: int) -> str:
    if not ids:
        return ""
    body = urllib.parse.urlencode({"hash": download_hash, "id": "|".join(ids), "priority": str(priority)}).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/api/v2/torrents/filePrio",
        data=body,
        headers={"User-Agent": "BTDiggRD/RDT", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with opener.open(req, timeout=15) as response:
        return response.read().decode("utf-8", errors="replace").strip()


def rdt_select_main_files(download_hash: str, title: str = "", attempts: int = 12, wait_sec: float = 2.0, trace_id: str = "", preferred_file_name: str = "") -> bool:
    hash_value = str(download_hash or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{40}", hash_value):
        trace_download(trace_id, "RDT_FILES_AUTO_SKIP", reason="hash invalido", hash=hash_value, title=title)
        return False
    base = RDT_BASE.rstrip("/")
    started = time.monotonic()
    trace_download(trace_id, "RDT_FILES_AUTO_START", hash=hash_value, title=title, attempts=attempts, wait_sec=wait_sec, preferred_file_name=preferred_file_name or "")
    try:
        opener, _basic = qbit_login(base, RDT_USER, RDT_PASS)
        trace_download(trace_id, "RDT_FILES_AUTO_LOGIN_OK", elapsed=_elapsed(started))
    except Exception as exc:
        trace_download(trace_id, "RDT_FILES_AUTO_LOGIN_FAIL", hash=hash_value, error=f"{type(exc).__name__}: {str(exc)[:160]}")
        log_download(f"RDT FILES AUTO login fallo hash={hash_value} titulo={title!r}: {type(exc).__name__}: {str(exc)[:160]}")
        return False

    last_error = ""
    for _attempt in range(max(1, int(attempts))):
        attempt = _attempt + 1
        try:
            url = base + "/api/v2/torrents/files?" + urllib.parse.urlencode({"hash": hash_value})
            req = urllib.request.Request(url, headers={"User-Agent": "BTDiggRD/RDT"})
            with opener.open(req, timeout=15) as response:
                files = json.loads(response.read().decode("utf-8", errors="replace") or "[]")
            if not isinstance(files, list) or not files:
                trace_download(trace_id, "RDT_FILES_AUTO_WAIT_FILES", hash=hash_value, attempt=attempt, files=0)
                time.sleep(wait_sec)
                continue

            videos = []
            for item in files:
                name = str(item.get("name") or "")
                if VIDEO_EXT_RE.search(name) and not re.search(r"(^|[\\/ ._-])sample([\\/ ._-]|$)", name, re.I):
                    videos.append(item)
            if not videos:
                videos = [item for item in files if VIDEO_EXT_RE.search(str(item.get("name") or ""))]

            selected = []
            selection_mode = "fallback_video_or_largest"
            preferred_norm = _norm_file_name(preferred_file_name)
            preferred_base = _norm_file_basename(preferred_file_name)
            if preferred_norm:
                exact_matches = []
                similar_matches: list[tuple[float, dict[str, Any]]] = []
                for item in files:
                    name = str(item.get("name") or "")
                    item_norm = _norm_file_name(name)
                    item_base = _norm_file_basename(name)
                    if item_norm == preferred_norm or (preferred_base and item_base == preferred_base):
                        exact_matches.append(item)
                        continue
                    ratio = max(
                        SequenceMatcher(None, preferred_norm, item_norm).ratio() if item_norm else 0.0,
                        SequenceMatcher(None, preferred_base, item_base).ratio() if preferred_base and item_base else 0.0,
                    )
                    if ratio >= 0.86:
                        similar_matches.append((ratio, item))
                if exact_matches:
                    selected = exact_matches[:1]
                    selection_mode = "preferred_exact"
                elif similar_matches:
                    similar_matches.sort(key=lambda row: (row[0], int(row[1].get("size") or 0)), reverse=True)
                    selected = [similar_matches[0][1]]
                    selection_mode = f"preferred_similar_{similar_matches[0][0]:.2f}"

            if not selected:
                selected = videos or sorted(files, key=lambda item: int(item.get("size") or 0), reverse=True)[:1]

            selected_ids = [str(item.get("index")) for item in selected if item.get("index") is not None]
            selected_set = set(selected_ids)
            other_ids = [str(item.get("index")) for item in files if item.get("index") is not None and str(item.get("index")) not in selected_set]
            selected_names = " | ".join(_short(item.get("name"), 80) for item in selected[:5])
            trace_download(trace_id, "RDT_FILES_AUTO_FILES_FOUND", hash=hash_value, attempt=attempt, total_files=len(files), videos=len(videos), selected_ids="|".join(selected_ids), selected_names=selected_names, selection_mode=selection_mode, preferred_file_name=preferred_file_name or "")
            if other_ids:
                try:
                    rdt_file_prio(opener, base, hash_value, other_ids, 0)
                    trace_download(trace_id, "RDT_FILES_AUTO_PRIO0_OK", hash=hash_value, count=len(other_ids))
                except Exception as exc:
                    last_error = f"prio0 {type(exc).__name__}: {exc}"
                    trace_download(trace_id, "RDT_FILES_AUTO_PRIO0_FAIL", hash=hash_value, error=last_error)
            rdt_file_prio(opener, base, hash_value, selected_ids, 1)
            trace_download(trace_id, "RDT_FILES_AUTO_OK", hash=hash_value, selected_ids="|".join(selected_ids), elapsed=_elapsed(started))
            log_download(f"RDT FILES AUTO OK hash={hash_value} ids={'|'.join(selected_ids)} titulo={title!r}")
            return True
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            trace_download(trace_id, "RDT_FILES_AUTO_ATTEMPT_FAIL", hash=hash_value, attempt=attempt, error=last_error)
            time.sleep(wait_sec)

    trace_download(trace_id, "RDT_FILES_AUTO_NO_SELECTION", hash=hash_value, elapsed=_elapsed(started), error=last_error[:180])
    log_download(f"RDT FILES AUTO sin seleccion hash={hash_value} titulo={title!r} error={last_error[:180]}")
    return False


def rdt_select_main_files_async(download_hash: str, title: str = "", trace_id: str = "", preferred_file_name: str = "") -> None:
    hash_value = str(download_hash or "").strip().lower()
    if hash_value:
        trace_download(trace_id, "RDT_FILES_AUTO_THREAD_START", hash=hash_value, title=title, preferred_file_name=preferred_file_name or "")
        threading.Thread(target=rdt_select_main_files, args=(hash_value, title, 12, 2.0, trace_id, preferred_file_name), daemon=True).start()


def rdt_dispatch_torrent_bytes(raw: bytes, filename: str, target: dict[str, str], title: str = "", trace_id: str = "", preferred_file_name: str = "") -> dict[str, str]:
    torrent_hash = torrent_infohash_from_bytes(raw)
    started = time.monotonic()
    trace_download(trace_id, "RDT_TORRENT_DISPATCH_START", filename=filename, title=title, bytes=len(raw or b""), hash=torrent_hash or "sin_hash", destino=target.get("key"))
    try:
        response = qbit_add_torrent_bytes(RDT_BASE, RDT_USER, RDT_PASS, raw, filename, target, is_rdt=True, trace_id=trace_id, engine_label="RDT")
        torrent_hash = hash_from_qbit_response(response) or torrent_hash
        trace_download(trace_id, "RDT_TORRENT_DISPATCH_API_OK", hash=torrent_hash or "sin_hash", elapsed=_elapsed(started), response=_short(response, 160))
        rdt_select_main_files_async(torrent_hash, title or filename, trace_id=trace_id, preferred_file_name=preferred_file_name)
        return {"mode": "api", "hash": torrent_hash, "resp": response, "path": ""}
    except Exception as exc:
        trace_download(trace_id, "RDT_TORRENT_DISPATCH_API_FAIL", error=f"{type(exc).__name__}: {str(exc)[:180]}", fallback="inbox")
        safe = safe_filename(filename, "btdigg")
        folder = Path(target["inbox"])
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / f"{safe}.torrent"
        if output.exists():
            output = folder / f"{safe}__{int(time.time())}.torrent"
        tmp = output.with_suffix(output.suffix + ".tmp")
        tmp.write_bytes(raw)
        tmp.replace(output)
        trace_download(trace_id, "RDT_TORRENT_DISPATCH_INBOX_OK", path=str(output), filename=output.name, hash=torrent_hash or "sin_hash", elapsed=_elapsed(started))
        rdt_select_main_files_async(torrent_hash, title or filename, trace_id=trace_id, preferred_file_name=preferred_file_name)
        return {"mode": "inbox", "hash": torrent_hash, "resp": "", "path": str(output), "error": str(exc)[:180], "filename": output.name}


def rdt_native_base() -> str:
    base = str(RDT_BASE or "").strip().rstrip("/")
    if not base or not RDT_USER or not RDT_PASS:
        raise RuntimeError("falta configuracion de RDT-Client")
    return base


def rdt_native_login(trace_id: str = "") -> requests.Session:
    base = rdt_native_base()
    session = requests.Session()
    url = f"{base}/Api/Authentication/Login"
    last_response: requests.Response | None = None
    last_error = ""
    for attempt in range(5):
        try:
            response = session.post(url, json={"userName": RDT_USER, "password": RDT_PASS}, timeout=20)
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            trace_download(trace_id, "RDT_NATIVE_LOGIN_EXC", attempt=attempt + 1, error=_short(last_error, 180))
            if attempt == 4:
                raise RuntimeError(f"RDT native login: {last_error}") from exc
            time.sleep(rdt_native_retry_delay(None, attempt))
            continue

        if response.status_code < 400:
            text = rdt_native_text(response, 120)
            if text and text not in {"Ok.", "Ok"}:
                raise RuntimeError(f"RDT native login: {text}")
            trace_download(trace_id, "RDT_NATIVE_LOGIN_OK", attempt=attempt + 1)
            return session

        last_response = response
        trace_download(trace_id, "RDT_NATIVE_LOGIN_HTTP", attempt=attempt + 1, status=response.status_code, body=rdt_native_text(response, 180))
        if not rdt_native_retryable(response) or attempt == 4:
            break
        time.sleep(rdt_native_retry_delay(response, attempt))

    raise RuntimeError(last_error or rdt_native_error("RDT native login", last_response))


def rdt_native_json(session: requests.Session, path: str, trace_id: str = "") -> Any:
    url = f"{rdt_native_base()}{path}"
    last_response: requests.Response | None = None
    last_error = ""
    for attempt in range(5):
        try:
            response = session.get(url, timeout=20)
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            trace_download(trace_id, "RDT_NATIVE_GET_EXC", path=path, attempt=attempt + 1, error=_short(last_error, 180))
            if attempt == 4:
                raise RuntimeError(f"RDT native GET {path}: {last_error}") from exc
            time.sleep(rdt_native_retry_delay(None, attempt))
            continue

        if response.status_code < 400:
            text = rdt_native_text(response, 4000)
            if not text:
                return None
            try:
                return response.json()
            except ValueError:
                return text

        last_response = response
        if not rdt_native_retryable(response) or attempt == 4:
            break
        time.sleep(rdt_native_retry_delay(response, attempt))

    raise RuntimeError(rdt_native_error(f"RDT native GET {path}", last_response) or last_error)


def rdt_native_post(session: requests.Session, path: str, payload: dict[str, Any], trace_id: str = "") -> Any:
    url = f"{rdt_native_base()}{path}"
    last_response: requests.Response | None = None
    last_error = ""
    for attempt in range(5):
        try:
            response = session.post(url, json=payload, timeout=30)
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            trace_download(trace_id, "RDT_NATIVE_POST_EXC", path=path, attempt=attempt + 1, error=_short(last_error, 180))
            if attempt == 4:
                raise RuntimeError(f"RDT native POST {path}: {last_error}") from exc
            time.sleep(rdt_native_retry_delay(None, attempt))
            continue

        if response.status_code < 400:
            text = rdt_native_text(response, 4000)
            if not text:
                return None
            try:
                return response.json()
            except ValueError:
                return text

        last_response = response
        if not rdt_native_retryable(response) or attempt == 4:
            break
        time.sleep(rdt_native_retry_delay(response, attempt))

    raise RuntimeError(rdt_native_error(f"RDT native POST {path}", last_response) or last_error)


def rdt_native_delete(session: requests.Session, torrent_id: str, trace_id: str = "", why: str = "") -> None:
    if not torrent_id:
        return
    try:
        rdt_native_post(
            session,
            f"/Api/Torrents/Delete/{urllib.parse.quote(str(torrent_id), safe='')}",
            {"deleteData": True, "deleteRdTorrent": True, "deleteLocalFiles": True},
            trace_id=trace_id,
        )
        trace_download(trace_id, "RDT_NATIVE_DELETE_OK", rdt_id=torrent_id, why=why or "")
    except Exception as exc:
        trace_download(trace_id, "RDT_NATIVE_DELETE_FAIL", rdt_id=torrent_id, why=why or "", error=f"{type(exc).__name__}: {str(exc)[:180]}")


def rdt_native_existing_by_hash(hash_value: str, trace_id: str = "") -> tuple[dict[str, Any] | None, bool]:
    expected = normalize_infohash(hash_value)
    if not expected:
        return None, True
    try:
        session = rdt_native_login(trace_id=trace_id)
        rows = rdt_native_rows(rdt_native_json(session, "/Api/Torrents", trace_id=trace_id))
        for row in rows:
            if rdt_native_row_hash(row) == expected:
                trace_download(trace_id, "RDT_NATIVE_ALREADY_PRESENT", hash=expected, rdt_id=rdt_native_row_id(row), status=rdt_native_row_status(row))
                return row, True
        trace_download(trace_id, "RDT_NATIVE_DUPLICATE_CLEAR", hash=expected, checked=len(rows))
        return None, True
    except Exception as exc:
        trace_download(trace_id, "RDT_NATIVE_DUPLICATE_CHECK_FAIL", hash=expected, error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return None, False


def rdt_native_existing_health_by_hash(hash_value: str, trace_id: str = "") -> tuple[dict[str, Any] | None, str, bool]:
    expected = normalize_infohash(hash_value)
    if not expected:
        return None, "missing", True
    try:
        session = rdt_native_login(trace_id=trace_id)
        rows = rdt_native_rows(rdt_native_json(session, "/Api/Torrents", trace_id=trace_id))
        for row in rows:
            if rdt_native_row_hash(row) == expected:
                phase = rdt_native_row_phase(row)
                trace_download(trace_id, "RDT_NATIVE_EXISTING_HEALTH", hash=expected, rdt_id=rdt_native_row_id(row), status=rdt_native_row_status(row), phase=phase)
                return row, phase, True
        trace_download(trace_id, "RDT_NATIVE_DUPLICATE_CLEAR", hash=expected, checked=len(rows))
        return None, "missing", True
    except Exception as exc:
        trace_download(trace_id, "RDT_NATIVE_DUPLICATE_CHECK_FAIL", hash=expected, error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return None, "unknown", False


def rdt_native_delete_by_id(torrent_id: str, trace_id: str = "", why: str = "") -> None:
    if not torrent_id:
        return
    session = rdt_native_login(trace_id=trace_id)
    rdt_native_delete(session, torrent_id, trace_id=trace_id, why=why)


def rdt_native_upload_magnet_response(session: requests.Session, magnet: str, category: str, manual_files: str = "", trace_id: str = "") -> Any:
    payload = {"magnetLink": magnet, "torrent": rdt_native_settings(category, manual_files)}
    return rdt_native_post(session, "/Api/Torrents/UploadMagnet", payload, trace_id=trace_id)


def rdt_native_upload_file_response(session: requests.Session, raw: bytes, filename: str, category: str, manual_files: str = "", trace_id: str = "") -> Any:
    url = f"{rdt_native_base()}/Api/Torrents/UploadFile"
    form_data = json.dumps({"torrent": rdt_native_settings(category, manual_files)}, ensure_ascii=False)
    files = {
        "file": (safe_filename(filename, "btdigg") or "btdigg.torrent", raw, "application/x-bittorrent"),
        "formData": (None, form_data, "application/json"),
    }
    last_response: requests.Response | None = None
    last_error = ""
    for attempt in range(5):
        try:
            response = session.post(url, files=files, timeout=45)
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            trace_download(trace_id, "RDT_NATIVE_UPLOAD_FILE_EXC", attempt=attempt + 1, error=_short(last_error, 180))
            if attempt == 4:
                raise RuntimeError(f"RDT native UploadFile: {last_error}") from exc
            time.sleep(rdt_native_retry_delay(None, attempt))
            continue

        if response.status_code < 400:
            text = rdt_native_text(response, 4000)
            if not text:
                return None
            try:
                return response.json()
            except ValueError:
                return text

        last_response = response
        if not rdt_native_retryable(response) or attempt == 4:
            break
        time.sleep(rdt_native_retry_delay(response, attempt))

    raise RuntimeError(rdt_native_error("RDT native UploadFile", last_response) or last_error)


def rdt_native_new_id(session: requests.Session, before: set[str], expected_hash: str = "", trace_id: str = "") -> str:
    expected = normalize_infohash(expected_hash)
    started = time.monotonic()
    before_ids = {str(item) for item in (before or set()) if str(item).strip()}
    for attempt in range(30):
        rows = rdt_native_rows(rdt_native_json(session, "/Api/Torrents", trace_id=trace_id))
        new_rows = [row for row in rows if rdt_native_row_id(row) and rdt_native_row_id(row) not in before_ids]
        if expected:
            for row in new_rows:
                if rdt_native_row_hash(row) == expected:
                    rdt_id = rdt_native_row_id(row)
                    trace_download(trace_id, "RDT_NATIVE_NEW_ID_HASH_OK", hash=expected, rdt_id=rdt_id, elapsed=_elapsed(started))
                    return rdt_id
            for row in rows:
                if rdt_native_row_hash(row) == expected:
                    rdt_id = rdt_native_row_id(row)
                    trace_download(trace_id, "RDT_NATIVE_NEW_ID_EXISTING_HASH_OK", hash=expected, rdt_id=rdt_id, elapsed=_elapsed(started))
                    return rdt_id
        if len(new_rows) == 1:
            rdt_id = rdt_native_row_id(new_rows[0])
            trace_download(trace_id, "RDT_NATIVE_NEW_ID_SINGLE_OK", rdt_id=rdt_id, elapsed=_elapsed(started))
            return rdt_id
        time.sleep(1)
    raise RuntimeError("RDT native no devolvio torrentId nuevo")


def rdt_native_find_row(session: requests.Session, torrent_id: str, expected_hash: str = "", before: set[str] | None = None, trace_id: str = "") -> dict[str, Any] | None:
    if torrent_id:
        url = f"{rdt_native_base()}/Api/Torrents/Get/{urllib.parse.quote(str(torrent_id), safe='')}"
        try:
            response = session.get(url, timeout=20)
            if response.status_code == 404:
                trace_download(trace_id, "RDT_NATIVE_GET_ROW_404", rdt_id=torrent_id)
            elif response.status_code >= 400:
                raise RuntimeError(rdt_native_error("RDT native Get row", response))
            else:
                data = response.json()
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            trace_download(trace_id, "RDT_NATIVE_GET_ROW_FAIL", rdt_id=torrent_id, error=f"{type(exc).__name__}: {str(exc)[:180]}")

    expected = normalize_infohash(expected_hash)
    rows = rdt_native_rows(rdt_native_json(session, "/Api/Torrents", trace_id=trace_id))
    if torrent_id:
        for row in rows:
            if rdt_native_row_id(row) == str(torrent_id):
                return row
    if expected:
        before_ids = {str(item) for item in (before or set()) if str(item).strip()}
        for row in rows:
            if rdt_native_row_hash(row) == expected and rdt_native_row_id(row) not in before_ids:
                return row
        for row in rows:
            if rdt_native_row_hash(row) == expected:
                return row
    return None


def rdt_native_ready_result(torrent_id: str, row: dict[str, Any], pending: bool = False) -> dict[str, Any]:
    status = rdt_native_row_status(row)
    raw_status = str(row.get("rdStatusRaw") or row.get("rdStatus") or "").strip()
    error = str(row.get("error") or row.get("errorMessage") or "").strip()
    status_lower = f"{status} {raw_status} {error}".lower()
    phase = rdt_native_row_phase(row)
    if phase == "error" or error or "error" in status_lower or "failed" in status_lower:
        raise RuntimeError(f"RDT native fallo: {status or raw_status or error}")
    downloads = _int_value(row.get("downloadsCount") or row.get("downloads") or 0)
    files_selected = _int_value(row.get("filesSelected") or row.get("selectedFiles") or 0)
    result = {
        "engine": "rdt-native",
        "rdt_id": rdt_native_row_id(row) or str(torrent_id or ""),
        "status": status or raw_status or "",
        "rd_status": raw_status,
        "phase": phase,
        "downloads": downloads,
        "files_selected": files_selected,
    }
    if pending:
        result["pending"] = True
    return result


def rdt_native_wait_ready(session: requests.Session, torrent_id: str, manual_files: str = "", expected_hash: str = "", before: set[str] | None = None, trace_id: str = "") -> dict[str, Any]:
    started = time.monotonic()
    last_status = ""
    for attempt in range(45):
        row = rdt_native_find_row(session, torrent_id, expected_hash=expected_hash, before=before, trace_id=trace_id)
        if row:
            result = rdt_native_ready_result(torrent_id, row, pending=False)
            last_status = str(result.get("status") or result.get("rd_status") or "")
            phase = str(result.get("phase") or "")
            if rdt_native_phase_is_ready(phase):
                trace_download(
                    trace_id,
                    "RDT_NATIVE_READY_OK",
                    rdt_id=result.get("rdt_id") or torrent_id,
                    status=result.get("status") or "",
                    phase=phase,
                    downloads=result.get("downloads"),
                    files_selected=result.get("files_selected"),
                    manual_files=manual_files or "",
                    elapsed=_elapsed(started),
                )
                return result
            trace_download(trace_id, "RDT_NATIVE_READY_WAIT", rdt_id=torrent_id, attempt=attempt + 1, status=last_status, phase=phase, elapsed=_elapsed(started))
        time.sleep(1)

    row = rdt_native_find_row(session, torrent_id, expected_hash=expected_hash, before=before, trace_id=trace_id)
    if row:
        result = rdt_native_ready_result(torrent_id, row, pending=True)
        phase = str(result.get("phase") or "")
        trace_download(trace_id, "RDT_NATIVE_READY_PENDING", rdt_id=result.get("rdt_id") or torrent_id, status=result.get("status") or "", phase=phase, elapsed=_elapsed(started))
        return result
    raise RuntimeError(f"RDT native no encuentra fila final: {torrent_id} {last_status}")


def rdt_manual_files_from_contract(contract: dict[str, Any]) -> str:
    preferred = str(contract.get("selected_file_name") or "").strip().replace("\\", "/")
    if not preferred:
        return ""
    if not preferred.startswith("/"):
        preferred = "/" + preferred.lstrip("./")
    return preferred


def rdt_native_upload_magnet(magnet: str, title: str, category: str, expected_hash: str = "", manual_files: str = "", trace_id: str = "") -> dict[str, Any]:
    expected = normalize_infohash(expected_hash) or hash_from_magnet(magnet)
    session = rdt_native_login(trace_id=trace_id)
    before_rows = rdt_native_rows(rdt_native_json(session, "/Api/Torrents", trace_id=trace_id))
    before_ids = {rdt_native_row_id(row) for row in before_rows if rdt_native_row_id(row)}
    created_id = ""
    started = time.monotonic()
    try:
        trace_download(trace_id, "RDT_NATIVE_UPLOAD_MAGNET_START", hash=expected or "sin_hash", title=title or "", category=category, manual_files=manual_files or "")
        response = rdt_native_upload_magnet_response(session, magnet, category, manual_files=manual_files, trace_id=trace_id)
        trace_download(trace_id, "RDT_NATIVE_UPLOAD_MAGNET_OK", response=_short(response, 180), elapsed=_elapsed(started))
        created_id = rdt_native_new_id(session, before_ids, expected_hash=expected, trace_id=trace_id)
        result = rdt_native_wait_ready(session, created_id, manual_files=manual_files, expected_hash=expected, before=before_ids, trace_id=trace_id)
        result.update({"mode": "native", "hash": expected, "manual_files": manual_files or ""})
        return result
    except Exception:
        if created_id:
            rdt_native_delete(session, created_id, trace_id=trace_id, why="upload_magnet_failed")
        raise


def rdt_native_upload_torrent(raw: bytes, filename: str, title: str, category: str, expected_hash: str = "", manual_files: str = "", trace_id: str = "") -> dict[str, Any]:
    expected = normalize_infohash(expected_hash) or torrent_infohash_from_bytes(raw)
    session = rdt_native_login(trace_id=trace_id)
    before_rows = rdt_native_rows(rdt_native_json(session, "/Api/Torrents", trace_id=trace_id))
    before_ids = {rdt_native_row_id(row) for row in before_rows if rdt_native_row_id(row)}
    created_id = ""
    started = time.monotonic()
    try:
        trace_download(trace_id, "RDT_NATIVE_UPLOAD_FILE_START", hash=expected or "sin_hash", filename=filename, title=title or "", category=category, manual_files=manual_files or "", bytes=len(raw or b""))
        response = rdt_native_upload_file_response(session, raw, filename, category, manual_files=manual_files, trace_id=trace_id)
        trace_download(trace_id, "RDT_NATIVE_UPLOAD_FILE_OK", response=_short(response, 180), elapsed=_elapsed(started))
        created_id = rdt_native_new_id(session, before_ids, expected_hash=expected, trace_id=trace_id)
        result = rdt_native_wait_ready(session, created_id, manual_files=manual_files, expected_hash=expected, before=before_ids, trace_id=trace_id)
        result.update({"mode": "native", "hash": expected, "manual_files": manual_files or ""})
        return result
    except Exception:
        if created_id:
            rdt_native_delete(session, created_id, trace_id=trace_id, why="upload_file_failed")
        raise


def rdt_followup_interval() -> float:
    try:
        return max(5.0, float(str(os.environ.get("RDT_FOLLOWUP_INTERVAL_SEC", "15")).replace(",", ".")))
    except Exception:
        return 15.0


def rdt_followup_timeout() -> float:
    try:
        return max(90.0, float(str(os.environ.get("RDT_FOLLOWUP_TIMEOUT_SEC", "900")).replace(",", ".")))
    except Exception:
        return 900.0


def rd_cleanup_preflight(torrent_id: str, trace_id: str = "", why: str = "") -> None:
    torrent_id = str(torrent_id or "").strip()
    token = rd_token()
    if not torrent_id:
        trace_download(trace_id, "RD_PREFLIGHT_CLEANUP_SKIP", reason="missing_id", why=why or "")
        return
    if not token:
        trace_download(trace_id, "RD_PREFLIGHT_CLEANUP_SKIP", reason="missing_token", id=torrent_id, why=why or "")
        return
    trace_download(trace_id, "RD_PREFLIGHT_CLEANUP_REQUESTED", id=torrent_id, why=why or "cleanup_preflight")
    rd_delete(torrent_id, token, why or "cleanup_preflight", trace_id=trace_id)


def rdt_native_followup_worker(rdt_id: str, rd_preflight_id: str, hash_value: str = "", title: str = "", trace_id: str = "") -> None:
    rdt_id = str(rdt_id or "").strip()
    rd_preflight_id = str(rd_preflight_id or "").strip()
    if not rdt_id or not rd_preflight_id:
        trace_download(trace_id, "RDT_FOLLOWUP_SKIP", rdt_id=rdt_id, rd_preflight_id=rd_preflight_id, reason="missing_id")
        return
    started = time.monotonic()
    timeout = rdt_followup_timeout()
    interval = rdt_followup_interval()
    trace_download(trace_id, "RDT_FOLLOWUP_START", rdt_id=rdt_id, rd_preflight_id=rd_preflight_id, hash=normalize_infohash(hash_value) or "sin_hash", title=title or "", timeout=timeout, interval=interval)
    try:
        session = rdt_native_login(trace_id=trace_id)
        last_phase = "missing"
        last_status = ""
        while time.monotonic() - started < timeout:
            row = rdt_native_find_row(session, rdt_id, expected_hash=hash_value, trace_id=trace_id)
            if row:
                phase = rdt_native_row_phase(row)
                status = rdt_native_row_status(row)
                last_phase = phase
                last_status = status
                trace_download(trace_id, "RDT_FOLLOWUP_POLL", rdt_id=rdt_id, phase=phase, status=status, elapsed=_elapsed(started))
                if rdt_native_phase_is_ready(phase):
                    rd_cleanup_preflight(rd_preflight_id, trace_id=trace_id, why="rdt_followup_ready")
                    trace_download(trace_id, "RDT_FOLLOWUP_DONE", rdt_id=rdt_id, rd_preflight_id=rd_preflight_id, phase=phase, elapsed=_elapsed(started))
                    return
                if phase == "error":
                    rd_cleanup_preflight(rd_preflight_id, trace_id=trace_id, why="rdt_followup_error")
                    rdt_native_delete(session, rdt_id, trace_id=trace_id, why="rdt_followup_error")
                    trace_download(trace_id, "RDT_FOLLOWUP_ERROR_CLEANED", rdt_id=rdt_id, rd_preflight_id=rd_preflight_id, status=status, elapsed=_elapsed(started))
                    return
            else:
                trace_download(trace_id, "RDT_FOLLOWUP_ROW_MISSING", rdt_id=rdt_id, elapsed=_elapsed(started))
            time.sleep(interval)
        rd_cleanup_preflight(rd_preflight_id, trace_id=trace_id, why="rdt_followup_timeout")
        rdt_native_delete(session, rdt_id, trace_id=trace_id, why="rdt_followup_timeout")
        trace_download(trace_id, "RDT_FOLLOWUP_TIMEOUT_CLEANED", rdt_id=rdt_id, rd_preflight_id=rd_preflight_id, phase=last_phase, status=last_status, elapsed=_elapsed(started))
    except Exception as exc:
        trace_download(trace_id, "RDT_FOLLOWUP_FAIL", rdt_id=rdt_id, rd_preflight_id=rd_preflight_id, error=f"{type(exc).__name__}: {str(exc)[:220]}", elapsed=_elapsed(started))
        rd_cleanup_preflight(rd_preflight_id, trace_id=trace_id, why="rdt_followup_exception")


def rdt_native_start_followup(rdt_id: str, rd_preflight_id: str, hash_value: str = "", title: str = "", trace_id: str = "") -> None:
    if not str(rdt_id or "").strip() or not str(rd_preflight_id or "").strip():
        trace_download(trace_id, "RDT_FOLLOWUP_NOT_STARTED", rdt_id=rdt_id or "", rd_preflight_id=rd_preflight_id or "")
        if str(rd_preflight_id or "").strip() and not str(rdt_id or "").strip():
            rd_cleanup_preflight(rd_preflight_id, trace_id=trace_id, why="rdt_followup_missing_rdt_id")
        return
    thread = threading.Thread(
        target=rdt_native_followup_worker,
        args=(str(rdt_id), str(rd_preflight_id), hash_value, title, trace_id),
        daemon=True,
    )
    thread.start()


def rd_precheck_torrent(raw: bytes, title: str, trace_id: str = "", selected_file_ids: str = "", keep_alive: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    token = rd_token()
    if not token:
        trace_download(trace_id, "RD_PREFILTER_TORRENT_NO_TOKEN", title=title, bytes=len(raw or b""))
        return {"ok": False, "reason": "sin token RD", "fallback": True}
    torrent_id = ""
    try:
        trace_download(trace_id, "RD_PREFILTER_TORRENT_START", title=title, bytes=len(raw or b""), hash=torrent_infohash_from_bytes(raw) or "sin_hash")
        result = rd_api("PUT", "/torrents/addTorrent", token, raw=raw, content_type="application/x-bittorrent", timeout=10)
        if not isinstance(result, dict) or not result.get("id"):
            trace_download(trace_id, "RD_PREFILTER_TORRENT_WEIRD_RESPONSE", response=_short(result, 180), elapsed=_elapsed(started))
            return {"ok": False, "reason": f"RD respuesta rara: {str(result)[:180]}", "fallback": True}
        torrent_id = str(result.get("id") or "")
        trace_download(trace_id, "RD_PREFILTER_TORRENT_ACCEPTED", id=torrent_id, elapsed=_elapsed(started))
        rd_select_files(torrent_id, token, selected_file_ids or "all", trace_id=trace_id)
        if keep_alive:
            trace_download(trace_id, "RD_PREFILTER_TORRENT_KEEP_ALIVE", id=torrent_id, files=selected_file_ids or "all")
        else:
            rd_delete(torrent_id, token, "prefiltro_ok_torrent", trace_id=trace_id)
        return {"ok": True, "reason": "RD aceptó el .torrent", "id": torrent_id}
    except Exception as exc:
        if torrent_id:
            rd_delete(torrent_id, token, "prefiltro_error_torrent", trace_id=trace_id)
        trace_download(trace_id, "RD_PREFILTER_TORRENT_FAIL", id=torrent_id, error=str(exc)[:240], elapsed=_elapsed(started))
        return {"ok": False, "reason": str(exc)[:240], "fallback": True}


def rd_precheck_magnet(magnet: str, title: str, trace_id: str = "", selected_file_ids: str = "", keep_alive: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    token = rd_token()
    if not token:
        trace_download(trace_id, "RD_PREFILTER_MAGNET_NO_TOKEN", title=title, hash=hash_from_magnet(magnet) or "sin_hash")
        return {"ok": False, "reason": "sin token RD", "fallback": True}
    torrent_id = ""
    try:
        trace_download(trace_id, "RD_PREFILTER_MAGNET_START", title=title, hash=hash_from_magnet(magnet) or "sin_hash")
        result = rd_api("POST", "/torrents/addMagnet", token, data={"magnet": magnet}, timeout=10)
        if not isinstance(result, dict) or not result.get("id"):
            trace_download(trace_id, "RD_PREFILTER_MAGNET_WEIRD_RESPONSE", response=_short(result, 180), elapsed=_elapsed(started))
            return {"ok": False, "reason": f"RD respuesta rara: {str(result)[:180]}", "fallback": True}
        torrent_id = str(result.get("id") or "")
        trace_download(trace_id, "RD_PREFILTER_MAGNET_ACCEPTED", id=torrent_id, elapsed=_elapsed(started))
        rd_select_files(torrent_id, token, selected_file_ids or "all", trace_id=trace_id)
        if keep_alive:
            trace_download(trace_id, "RD_PREFILTER_MAGNET_KEEP_ALIVE", id=torrent_id, files=selected_file_ids or "all")
        else:
            rd_delete(torrent_id, token, "prefiltro_ok_magnet", trace_id=trace_id)
        return {"ok": True, "reason": "RD aceptó el magnet", "id": torrent_id}
    except Exception as exc:
        if torrent_id:
            rd_delete(torrent_id, token, "prefiltro_error_magnet", trace_id=trace_id)
        trace_download(trace_id, "RD_PREFILTER_MAGNET_FAIL", id=torrent_id, error=str(exc)[:240], elapsed=_elapsed(started))
        return {"ok": False, "reason": str(exc)[:240], "fallback": True}


def parse_bencode_item(data: bytes, pos: int = 0):
    char = data[pos : pos + 1]
    if char == b"i":
        end = data.index(b"e", pos)
        return int(data[pos + 1 : end]), end + 1
    if char == b"l":
        pos += 1
        output = []
        while data[pos : pos + 1] != b"e":
            value, pos = parse_bencode_item(data, pos)
            output.append(value)
        return output, pos + 1
    if char == b"d":
        pos += 1
        output = {}
        while data[pos : pos + 1] != b"e":
            key, pos = parse_bencode_item(data, pos)
            value, pos = parse_bencode_item(data, pos)
            output[key] = value
        return output, pos + 1
    if char.isdigit():
        colon = data.index(b":", pos)
        length = int(data[pos:colon])
        start = colon + 1
        return data[start : start + length], start + length
    raise ValueError("bencode inválido")


def torrent_infohash_from_bytes(data: bytes) -> str:
    try:
        if not data or data[:1] != b"d":
            return ""
        pos = 1
        while data[pos : pos + 1] != b"e":
            key, pos = parse_bencode_item(data, pos)
            if key == b"info":
                start = pos
                _obj, pos = parse_bencode_item(data, pos)
                return hashlib.sha1(data[start:pos]).hexdigest().lower()
            _skip, pos = parse_bencode_item(data, pos)
    except Exception:
        return ""
    return ""


def hash_from_qbit_response(response: Any) -> str:
    try:
        data = json.loads(str(response or "") or "{}")
        ids = data.get("added_torrent_ids") or []
        if isinstance(ids, list) and ids:
            torrent_hash = str(ids[0] or "").strip().lower()
            if re.fullmatch(r"[a-f0-9]{40}", torrent_hash):
                return torrent_hash
    except Exception:
        pass
    return ""


def record_download(title: str, module: str, link: str, torrent_path: Any = None, torrent_bytes: bytes | None = None, download_hash: str = "", destino: str = "", trace_id: str = "", rdt_id: str = "", route: str = "", rd_preflight_id: str = "") -> None:
    title = title or "(sin título)"
    torrent_hash = str(download_hash or "").strip().lower() or hash_from_magnet(link)
    if not torrent_hash and torrent_bytes:
        torrent_hash = torrent_infohash_from_bytes(torrent_bytes)
    record = {
        "id": hashlib.sha1(f"{torrent_hash}\n{module}\n{link}\n{title}\n{time.time_ns()}".encode("utf-8", errors="ignore")).hexdigest()[:16],
        "title": title,
        "module": module or "btdigg",
        "link": link or "",
        "hash": torrent_hash,
        "destino": destino or "",
        "rdt_id": str(rdt_id or ""),
        "route": route or "",
        "rd_preflight_id": str(rd_preflight_id or ""),
        "torrent_path": str(torrent_path or ""),
        "time": time.strftime("%d-%m-%Y %H:%M:%S"),
        "ts": time.time(),
    }
    old = read_json(TRACKING_FILE)
    records = old if isinstance(old, list) else []
    records.insert(0, record)
    write_json(TRACKING_FILE, records[:50])
    trace_download(trace_id, "TRACKING_REGISTERED", record_id=record["id"], module=module, destino=destino or "", hash=torrent_hash or "sin_hash", tracking_file=TRACKING_FILE)
    log_download(f"REGISTRADO module={module} destino={destino or ''} hash={torrent_hash or 'sin_hash'} title={title!r}")


def _rd_links_count(info: Any) -> int:
    if not isinstance(info, dict):
        return 0
    links = info.get("links") or []
    return len(links) if isinstance(links, list) else 0


def _rd_info_reusable(info: Any) -> bool:
    if not isinstance(info, dict):
        return False
    return str(info.get("status") or "") == "downloaded" and _rd_links_count(info) > 0


def rd_refresh_reusable_evidence(contract: dict[str, Any], trace_id: str = "") -> dict[str, Any]:
    token = rd_token()
    hash_value = normalize_infohash(contract.get("hash") or contract.get("magnet") or contract.get("link"))
    torrent_id = str(contract.get("rd_torrent_id") or "").strip()
    if not token:
        trace_download(trace_id, "RD_REUSABLE_NO_TOKEN", hash=hash_value or "sin_hash", id=torrent_id)
        return {"ok": False, "reason": "sin token RD"}

    if torrent_id:
        try:
            trace_download(trace_id, "RD_REUSABLE_INFO_START", id=torrent_id, hash=hash_value or "sin_hash")
            info = rd_api("GET", f"/torrents/info/{torrent_id}", token, timeout=12)
            if _rd_info_reusable(info):
                trace_download(trace_id, "RD_REUSABLE_INFO_OK", id=torrent_id, hash=hash_value or "sin_hash", links=_rd_links_count(info), status=(info or {}).get("status"))
                return {"ok": True, "id": torrent_id, "info": info, "links": _rd_links_count(info), "reason": "rd_torrent_id vivo"}
            trace_download(trace_id, "RD_REUSABLE_INFO_NOT_READY", id=torrent_id, status=(info or {}).get("status") if isinstance(info, dict) else "", links=_rd_links_count(info))
        except Exception as exc:
            trace_download(trace_id, "RD_REUSABLE_INFO_FAIL", id=torrent_id, hash=hash_value or "sin_hash", error=f"{type(exc).__name__}: {exc}")

    if hash_value:
        try:
            trace_download(trace_id, "RD_REUSABLE_LIST_SEARCH_START", hash=hash_value)
            listing = rd_api("GET", "/torrents", token, timeout=15)
            if isinstance(listing, list):
                for item in listing:
                    if not isinstance(item, dict):
                        continue
                    if normalize_infohash(item.get("hash")) != hash_value:
                        continue
                    candidate_id = str(item.get("id") or "").strip()
                    if not candidate_id:
                        continue
                    try:
                        info = rd_api("GET", f"/torrents/info/{candidate_id}", token, timeout=12)
                    except Exception as exc:
                        trace_download(trace_id, "RD_REUSABLE_LIST_INFO_FAIL", id=candidate_id, hash=hash_value, error=f"{type(exc).__name__}: {exc}")
                        continue
                    if _rd_info_reusable(info):
                        trace_download(trace_id, "RD_REUSABLE_LIST_SEARCH_OK", id=candidate_id, hash=hash_value, links=_rd_links_count(info), status=(info or {}).get("status"))
                        return {"ok": True, "id": candidate_id, "info": info, "links": _rd_links_count(info), "reason": "hash vivo en RD"}
            trace_download(trace_id, "RD_REUSABLE_LIST_SEARCH_EMPTY", hash=hash_value)
        except Exception as exc:
            trace_download(trace_id, "RD_REUSABLE_LIST_SEARCH_FAIL", hash=hash_value, error=f"{type(exc).__name__}: {exc}")

    return {"ok": False, "reason": "la evidencia RD ya no esta viva"}


def route_qbit_reusable(contract: dict[str, Any], link: str, target: dict[str, str], title: str, module: str, started: float, trace_id: str):
    hash_value = normalize_infohash(contract.get("hash") or link)
    trace_download(trace_id, "ROUTE_SELECTED", engine="qBittorrent", route="QBIT_REUSABLE", hash=hash_value or "sin_hash", qbt_was_existing=contract.get("qbt_was_existing"))
    if link.startswith("magnet:"):
        if not hash_value:
            trace_download(trace_id, "DOWNLOAD_REJECTED", route="QBIT_REUSABLE", reason="magnet sin hash")
            return jsonify({"ok": False, "error": "Este magnet no trae hash validable.", "trace_id": trace_id}), 400
        info, checked = client_info_by_hash(QBIT_BASE, QBIT_USER, QBIT_PASS, hash_value, trace_id=trace_id, engine_label="qBittorrent")
        if not checked:
            trace_download(trace_id, "DOWNLOAD_REJECTED", route="QBIT_REUSABLE", reason="no se pudo comprobar duplicado qBit")
            return jsonify({"ok": False, "error": "No pude comprobar qBittorrent por hash; no lo añado para evitar duplicados.", "trace_id": trace_id}), 502
        if info:
            trace_download(trace_id, "QBIT_REUSABLE_ALREADY_PRESENT", hash=hash_value, state=info.get("state") or "", progress=info.get("progress") or "")
            trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="qbit_already_present")
            trace_download(trace_id, "DOWNLOAD_END_OK", engine="qBittorrent", route="QBIT_REUSABLE", already_present=True, elapsed=_elapsed(started))
            return jsonify({"ok": True, "message": "Ya estaba en qBittorrent", "module": module, "title": title, "engine": "qBittorrent", "already_present": True, "trace_id": trace_id})
        response = qbit_add_url(QBIT_BASE, QBIT_USER, QBIT_PASS, link, target, is_rdt=False, trace_id=trace_id, engine_label="qBittorrent")
        qbit_hash = hash_from_qbit_response(response) or hash_value
        record_download(title, module, link, download_hash=qbit_hash, destino=target["key"], trace_id=trace_id)
        trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="qbit_target")
        trace_download(trace_id, "DOWNLOAD_END_OK", engine="qBittorrent", route="QBIT_REUSABLE", already_present=False, elapsed=_elapsed(started))
        return jsonify({"ok": True, "message": "Enviado a qBittorrent", "module": module, "title": title, "engine": "qBittorrent", "already_present": False, "trace_id": trace_id})

    if link.startswith(("http://", "https://")):
        raw = get_bytes(link, timeout=90)
        torrent_hash = torrent_infohash_from_bytes(raw)
        trace_download(trace_id, "QBIT_REUSABLE_TORRENT_URL_OK", bytes=len(raw or b""), hash=torrent_hash or "sin_hash")
        if not raw or len(raw) < 40:
            return jsonify({"ok": False, "error": "El enlace devolvió un torrent vacío o inválido.", "trace_id": trace_id}), 500
        check_hash = torrent_hash or hash_value
        info, checked = client_info_by_hash(QBIT_BASE, QBIT_USER, QBIT_PASS, check_hash, trace_id=trace_id, engine_label="qBittorrent")
        if check_hash and not checked:
            return jsonify({"ok": False, "error": "No pude comprobar qBittorrent por hash; no lo añado para evitar duplicados.", "trace_id": trace_id}), 502
        if info:
            trace_download(trace_id, "QBIT_REUSABLE_ALREADY_PRESENT", hash=check_hash, state=info.get("state") or "", progress=info.get("progress") or "")
            trace_download(trace_id, "DOWNLOAD_END_OK", engine="qBittorrent", route="QBIT_REUSABLE", already_present=True, elapsed=_elapsed(started))
            return jsonify({"ok": True, "message": "Ya estaba en qBittorrent", "module": module, "title": title, "engine": "qBittorrent", "already_present": True, "trace_id": trace_id})
        response = qbit_add_torrent_bytes(QBIT_BASE, QBIT_USER, QBIT_PASS, raw, safe_filename(title, module or "descarga"), target, trace_id=trace_id, engine_label="qBittorrent")
        qbit_hash = hash_from_qbit_response(response) or check_hash
        record_download(title, module, "qbit-torrent", download_hash=qbit_hash, torrent_bytes=raw, destino=target["key"], trace_id=trace_id)
        trace_download(trace_id, "DOWNLOAD_END_OK", engine="qBittorrent", route="QBIT_REUSABLE", already_present=False, elapsed=_elapsed(started))
        return jsonify({"ok": True, "message": "Enviado a qBittorrent", "module": module, "title": title, "engine": "qBittorrent", "already_present": False, "trace_id": trace_id})

    return jsonify({"ok": False, "error": "No pude resolver este resultado a magnet o .torrent real.", "trace_id": trace_id}), 400


def route_rd_reusable(contract: dict[str, Any], link: str, target: dict[str, str], title: str, module: str, started: float, trace_id: str):
    hash_value = normalize_infohash(contract.get("hash") or link)
    preferred_file = str(contract.get("selected_file_name") or "").strip()
    trace_download(trace_id, "ROUTE_SELECTED", engine="RDT-Client", route="RD_REUSABLE", hash=hash_value or "sin_hash", rd_torrent_id=contract.get("rd_torrent_id") or "", preferred_file_name=preferred_file)
    evidence = rd_refresh_reusable_evidence(contract, trace_id=trace_id)
    trace_download(trace_id, "RD_REUSABLE_EVIDENCE_RESULT", ok=evidence.get("ok"), id=evidence.get("id") or "", links=evidence.get("links") or 0, reason=evidence.get("reason") or "")
    if not evidence.get("ok"):
        trace_download(trace_id, "DOWNLOAD_REJECTED", route="RD_REUSABLE", reason=evidence.get("reason") or "RD no reutilizable")
        return jsonify({"ok": False, "error": "La evidencia RD de esta fila ya no está viva. Vuelve a buscar antes de descargar.", "trace_id": trace_id}), 409

    if hash_value:
        info, checked = client_info_by_hash(RDT_BASE, RDT_USER, RDT_PASS, hash_value, trace_id=trace_id, engine_label="RDT")
        if not checked:
            trace_download(trace_id, "DOWNLOAD_REJECTED", route="RD_REUSABLE", reason="no se pudo comprobar duplicado RDT")
            return jsonify({"ok": False, "error": "No pude comprobar RDT-Client por hash; no lo añado para evitar duplicados.", "trace_id": trace_id}), 502
        if info:
            trace_download(trace_id, "RDT_ALREADY_PRESENT", hash=hash_value, state=info.get("state") or "", progress=info.get("progress") or "")
            rdt_select_main_files_async(hash_value, title, trace_id=trace_id, preferred_file_name=preferred_file)
            trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="rdt_already_present")
            trace_download(trace_id, "DOWNLOAD_END_OK", engine="RDT-Client", route="RD_REUSABLE", already_present=True, elapsed=_elapsed(started))
            return jsonify({"ok": True, "message": "RD validado - ya estaba en RDT-Client", "module": module, "title": title, "engine": "RDT-Client", "already_present": True, "trace_id": trace_id})

    trace_download(trace_id, "RD_REUSABLE_RDT_IMPORT_EXPLICIT", hash=hash_value or "sin_hash", link_type=_link_kind(link), link_ref=_link_ref(link))
    if link.startswith("magnet:"):
        response = qbit_add_url(RDT_BASE, RDT_USER, RDT_PASS, link, target, is_rdt=True, trace_id=trace_id, engine_label="RDT")
        rdt_hash = hash_from_qbit_response(response) or hash_value or hash_from_magnet(link)
        record_download(title, module, link, download_hash=rdt_hash, destino=target["key"], trace_id=trace_id)
        rdt_select_main_files_async(rdt_hash, title, trace_id=trace_id, preferred_file_name=preferred_file)
        trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="rd_reusable_import_explicit")
        trace_download(trace_id, "DOWNLOAD_END_OK", engine="RDT-Client", route="RD_REUSABLE", already_present=False, elapsed=_elapsed(started))
        return jsonify({"ok": True, "message": "RD validado - enviado a RDT-Client", "module": module, "title": title, "engine": "RDT-Client", "already_present": False, "trace_id": trace_id})

    if link.startswith(("http://", "https://")):
        raw = get_bytes(link, timeout=90)
        if not raw or len(raw) < 40:
            return jsonify({"ok": False, "error": "El enlace devolvió un torrent vacío o inválido.", "trace_id": trace_id}), 500
        rdt = rdt_dispatch_torrent_bytes(raw, safe_filename(title, module or "descarga"), target, title, trace_id=trace_id, preferred_file_name=preferred_file)
        path = rdt.get("path") or ""
        record_download(title, module, path or "rdt-api-torrent", torrent_path=path or None, torrent_bytes=raw, download_hash=rdt.get("hash") or "", destino=target["key"], trace_id=trace_id)
        trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="rd_reusable_torrent_import_explicit")
        trace_download(trace_id, "DOWNLOAD_END_OK", engine="RDT-Client", route="RD_REUSABLE", mode=rdt.get("mode"), path=path, elapsed=_elapsed(started))
        return jsonify({"ok": True, "message": "RD validado - enviado a RDT-Client", "module": module, "title": title, "engine": "RDT-Client", "path": path, "trace_id": trace_id})

    return jsonify({"ok": False, "error": "No pude resolver este RD OK a magnet o .torrent real.", "trace_id": trace_id}), 400


def route_rd_verified_magnet(contract: dict[str, Any], link: str, target: dict[str, str], title: str, module: str, started: float, trace_id: str):
    hash_value = normalize_infohash(contract.get("hash") or link)
    preferred_file = str(contract.get("selected_file_name") or "").strip()
    trace_download(
        trace_id,
        "ROUTE_SELECTED",
        engine="RDT-Client",
        route="RD_VERIFIED_MAGNET",
        hash=hash_value or "sin_hash",
        rd_torrent_id=contract.get("rd_torrent_id") or "",
        rd_existing=contract.get("rd_existing"),
        rd_links=contract.get("rd_links"),
        preferred_file_name=preferred_file,
    )
    trace_download(trace_id, "RD_TEMP_ID_NOT_REUSED", reason="rd_existing_false_prefilter_id_can_be_deleted", rd_torrent_id=contract.get("rd_torrent_id") or "")

    if hash_value:
        info, checked = client_info_by_hash(RDT_BASE, RDT_USER, RDT_PASS, hash_value, trace_id=trace_id, engine_label="RDT")
        if not checked:
            trace_download(trace_id, "DOWNLOAD_REJECTED", route="RD_VERIFIED_MAGNET", reason="no se pudo comprobar duplicado RDT")
            return jsonify({"ok": False, "error": "No pude comprobar RDT-Client por hash; no lo añado para evitar duplicados.", "trace_id": trace_id}), 502
        if info:
            trace_download(trace_id, "RDT_ALREADY_PRESENT", hash=hash_value, state=info.get("state") or "", progress=info.get("progress") or "")
            rdt_select_main_files_async(hash_value, title, trace_id=trace_id, preferred_file_name=preferred_file)
            trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="rd_verified_already_present")
            trace_download(trace_id, "DOWNLOAD_END_OK", engine="RDT-Client", route="RD_VERIFIED_MAGNET", already_present=True, elapsed=_elapsed(started))
            return jsonify({"ok": True, "message": "RD validado - ya estaba en RDT-Client", "module": module, "title": title, "engine": "RDT-Client", "already_present": True, "trace_id": trace_id})

    trace_download(trace_id, "RD_VERIFIED_RDT_IMPORT_EXPLICIT", hash=hash_value or "sin_hash", link_type=_link_kind(link), link_ref=_link_ref(link))
    if link.startswith("magnet:"):
        rd = rd_precheck_magnet(link, title, trace_id=trace_id)
        trace_download(trace_id, "RD_VERIFIED_PREFLIGHT_RESULT", ok=rd.get("ok"), id=rd.get("id") or "", reason=rd.get("reason") or "")
        if not rd.get("ok"):
            trace_download(trace_id, "DOWNLOAD_REJECTED", route="RD_VERIFIED_MAGNET", reason=rd.get("reason") or "RD no acepto preflight final")
            return jsonify({"ok": False, "error": "Real-Debrid no aceptó esta descarga en la comprobación final.", "reason": str(rd.get("reason") or "")[:220], "trace_id": trace_id}), 409
        response = qbit_add_url(RDT_BASE, RDT_USER, RDT_PASS, link, target, is_rdt=True, trace_id=trace_id, engine_label="RDT")
        rdt_hash = hash_from_qbit_response(response) or hash_value or hash_from_magnet(link)
        record_download(title, module, link, download_hash=rdt_hash, destino=target["key"], trace_id=trace_id)
        rdt_select_main_files_async(rdt_hash, title, trace_id=trace_id, preferred_file_name=preferred_file)
        trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="rd_verified_temp_import_explicit")
        trace_download(trace_id, "DOWNLOAD_END_OK", engine="RDT-Client", route="RD_VERIFIED_MAGNET", already_present=False, elapsed=_elapsed(started))
        return jsonify({"ok": True, "message": "RD validado - enviado a RDT-Client", "module": module, "title": title, "engine": "RDT-Client", "already_present": False, "trace_id": trace_id})

    if link.startswith(("http://", "https://")):
        raw = get_bytes(link, timeout=90)
        if not raw or len(raw) < 40:
            return jsonify({"ok": False, "error": "El enlace devolvió un torrent vacío o inválido.", "trace_id": trace_id}), 500
        rd = rd_precheck_torrent(raw, title, trace_id=trace_id)
        trace_download(trace_id, "RD_VERIFIED_PREFLIGHT_RESULT", ok=rd.get("ok"), id=rd.get("id") or "", reason=rd.get("reason") or "")
        if not rd.get("ok"):
            trace_download(trace_id, "DOWNLOAD_REJECTED", route="RD_VERIFIED_MAGNET", reason=rd.get("reason") or "RD no acepto preflight final")
            return jsonify({"ok": False, "error": "Real-Debrid no aceptó este torrent en la comprobación final.", "reason": str(rd.get("reason") or "")[:220], "trace_id": trace_id}), 409
        rdt = rdt_dispatch_torrent_bytes(raw, safe_filename(title, module or "descarga"), target, title, trace_id=trace_id, preferred_file_name=preferred_file)
        path = rdt.get("path") or ""
        record_download(title, module, path or "rdt-api-torrent", torrent_path=path or None, torrent_bytes=raw, download_hash=rdt.get("hash") or "", destino=target["key"], trace_id=trace_id)
        trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="rd_verified_temp_torrent_import_explicit")
        trace_download(trace_id, "DOWNLOAD_END_OK", engine="RDT-Client", route="RD_VERIFIED_MAGNET", mode=rdt.get("mode"), path=path, elapsed=_elapsed(started))
        return jsonify({"ok": True, "message": "RD validado - enviado a RDT-Client", "module": module, "title": title, "engine": "RDT-Client", "path": path, "trace_id": trace_id})

    return jsonify({"ok": False, "error": "No pude resolver este RD OK a magnet o .torrent real.", "trace_id": trace_id}), 400


def route_rd_reusable_native(contract: dict[str, Any], link: str, target: dict[str, str], title: str, module: str, started: float, trace_id: str):
    hash_value = normalize_infohash(contract.get("hash") or link)
    preferred_file = str(contract.get("selected_file_name") or "").strip()
    manual_files = rdt_manual_files_from_contract(contract)
    trace_download(trace_id, "ROUTE_SELECTED", engine="RDT-Client", route="RD_REUSABLE_NATIVE", hash=hash_value or "sin_hash", rd_torrent_id=contract.get("rd_torrent_id") or "", preferred_file_name=preferred_file, manual_files=manual_files or "")

    evidence = rd_refresh_reusable_evidence(contract, trace_id=trace_id)
    trace_download(trace_id, "RD_REUSABLE_EVIDENCE_RESULT", ok=evidence.get("ok"), id=evidence.get("id") or "", links=evidence.get("links") or 0, reason=evidence.get("reason") or "")
    if not evidence.get("ok"):
        trace_download(trace_id, "DOWNLOAD_REJECTED", route="RD_REUSABLE_NATIVE", reason=evidence.get("reason") or "RD no reutilizable")
        return jsonify({"ok": False, "error": "La evidencia RD de esta fila ya no esta viva. Vuelve a buscar antes de descargar.", "trace_id": trace_id}), 409

    if hash_value:
        info, phase, checked = rdt_native_existing_health_by_hash(hash_value, trace_id=trace_id)
        if not checked:
            trace_download(trace_id, "DOWNLOAD_REJECTED", route="RD_REUSABLE_NATIVE", reason="no se pudo comprobar duplicado RDT native")
            return jsonify({"ok": False, "error": "No pude comprobar RDT-Client por hash; no lo anado para evitar duplicados.", "trace_id": trace_id}), 502
        if info:
            rdt_id = rdt_native_row_id(info)
            if rdt_native_phase_is_ready(phase):
                trace_download(trace_id, "RDT_NATIVE_ALREADY_PRESENT_RETURN", hash=hash_value, rdt_id=rdt_id, status=rdt_native_row_status(info), phase=phase)
                trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="rdt_native_already_present")
                trace_download(trace_id, "DOWNLOAD_END_OK", engine="RDT-Client", route="RD_REUSABLE_NATIVE", already_present=True, elapsed=_elapsed(started))
                return jsonify({"ok": True, "message": "RD validado - ya estaba en RDT-Client", "module": module, "title": title, "engine": "RDT-Client", "already_present": True, "rdt_id": rdt_id, "trace_id": trace_id})
            if phase in {"blocked_pending", "error"}:
                trace_download(trace_id, "RDT_NATIVE_STALE_DELETE_BEFORE_RETRY", hash=hash_value, rdt_id=rdt_id, status=rdt_native_row_status(info), phase=phase)
                rdt_native_delete_by_id(rdt_id, trace_id=trace_id, why="stale_before_retry")
            else:
                trace_download(trace_id, "DOWNLOAD_REJECTED", route="RD_REUSABLE_NATIVE", reason=f"RDT pendiente no saludable: {phase}", rdt_id=rdt_id)
                return jsonify({"ok": False, "error": "RDT-Client tiene esta descarga pendiente. No la marco como correcta para evitar falso OK.", "trace_id": trace_id}), 409

    trace_download(trace_id, "RD_REUSABLE_RDT_NATIVE_IMPORT", hash=hash_value or "sin_hash", link_type=_link_kind(link), link_ref=_link_ref(link), manual_files=manual_files or "")
    if link.startswith("magnet:"):
        result = rdt_native_upload_magnet(link, title, target["key"], expected_hash=hash_value, manual_files=manual_files, trace_id=trace_id)
        rdt_hash = str(result.get("hash") or hash_value or hash_from_magnet(link))
        record_download(title, module, link, download_hash=rdt_hash, destino=target["key"], trace_id=trace_id, rdt_id=str(result.get("rdt_id") or ""), route="RD_REUSABLE_NATIVE")
        trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="rd_reusable_native_import")
        trace_download(trace_id, "DOWNLOAD_END_PENDING" if result.get("pending") else "DOWNLOAD_END_OK", engine="RDT-Client", route="RD_REUSABLE_NATIVE", mode=result.get("mode"), rdt_id=result.get("rdt_id") or "", status=result.get("status") or "", already_present=False, elapsed=_elapsed(started))
        return jsonify({"ok": True, "message": "RD validado - enviado a RDT-Client", "module": module, "title": title, "engine": "RDT-Client", "already_present": False, "rdt_id": result.get("rdt_id") or "", "status": result.get("status") or "", "pending": bool(result.get("pending")), "trace_id": trace_id})

    if link.startswith(("http://", "https://")):
        raw = get_bytes(link, timeout=90)
        if not raw or len(raw) < 40:
            return jsonify({"ok": False, "error": "El enlace devolvio un torrent vacio o invalido.", "trace_id": trace_id}), 500
        filename = safe_filename(title, module or "descarga")
        result = rdt_native_upload_torrent(raw, filename, title, target["key"], expected_hash=hash_value, manual_files=manual_files, trace_id=trace_id)
        record_download(title, module, "rdt-native-torrent", torrent_bytes=raw, download_hash=str(result.get("hash") or ""), destino=target["key"], trace_id=trace_id, rdt_id=str(result.get("rdt_id") or ""), route="RD_REUSABLE_NATIVE")
        trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="rd_reusable_native_torrent_import")
        trace_download(trace_id, "DOWNLOAD_END_PENDING" if result.get("pending") else "DOWNLOAD_END_OK", engine="RDT-Client", route="RD_REUSABLE_NATIVE", mode=result.get("mode"), rdt_id=result.get("rdt_id") or "", status=result.get("status") or "", elapsed=_elapsed(started))
        return jsonify({"ok": True, "message": "RD validado - enviado a RDT-Client", "module": module, "title": title, "engine": "RDT-Client", "rdt_id": result.get("rdt_id") or "", "status": result.get("status") or "", "pending": bool(result.get("pending")), "trace_id": trace_id})

    return jsonify({"ok": False, "error": "No pude resolver este RD OK a magnet o .torrent real.", "trace_id": trace_id}), 400


def route_rd_verified_magnet_native(contract: dict[str, Any], link: str, target: dict[str, str], title: str, module: str, started: float, trace_id: str):
    hash_value = normalize_infohash(contract.get("hash") or link)
    preferred_file = str(contract.get("selected_file_name") or "").strip()
    selected_file_ids = str(contract.get("selected_file_ids") or "").strip()
    manual_files = rdt_manual_files_from_contract(contract)
    trace_download(
        trace_id,
        "ROUTE_SELECTED",
        engine="RDT-Client",
        route="RD_VERIFIED_MAGNET_NATIVE",
        hash=hash_value or "sin_hash",
        rd_torrent_id=contract.get("rd_torrent_id") or "",
        rd_existing=contract.get("rd_existing"),
        rd_links=contract.get("rd_links"),
        preferred_file_name=preferred_file,
        selected_file_ids=selected_file_ids or "",
        manual_files=manual_files or "",
    )
    trace_download(trace_id, "RD_TEMP_ID_NOT_REUSED", reason="rd_existing_false_prefilter_id_can_be_deleted", rd_torrent_id=contract.get("rd_torrent_id") or "")

    if hash_value:
        info, phase, checked = rdt_native_existing_health_by_hash(hash_value, trace_id=trace_id)
        if not checked:
            trace_download(trace_id, "DOWNLOAD_REJECTED", route="RD_VERIFIED_MAGNET_NATIVE", reason="no se pudo comprobar duplicado RDT native")
            return jsonify({"ok": False, "error": "No pude comprobar RDT-Client por hash; no lo anado para evitar duplicados.", "trace_id": trace_id}), 502
        if info:
            rdt_id = rdt_native_row_id(info)
            if rdt_native_phase_is_ready(phase):
                trace_download(trace_id, "RDT_NATIVE_ALREADY_PRESENT_RETURN", hash=hash_value, rdt_id=rdt_id, status=rdt_native_row_status(info), phase=phase)
                trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="rd_verified_native_already_present")
                trace_download(trace_id, "DOWNLOAD_END_OK", engine="RDT-Client", route="RD_VERIFIED_MAGNET_NATIVE", already_present=True, elapsed=_elapsed(started))
                return jsonify({"ok": True, "message": "RD validado - ya estaba en RDT-Client", "module": module, "title": title, "engine": "RDT-Client", "already_present": True, "rdt_id": rdt_id, "trace_id": trace_id})
            if phase in {"blocked_pending", "error"}:
                trace_download(trace_id, "RDT_NATIVE_STALE_DELETE_BEFORE_RETRY", hash=hash_value, rdt_id=rdt_id, status=rdt_native_row_status(info), phase=phase)
                rdt_native_delete_by_id(rdt_id, trace_id=trace_id, why="stale_before_retry")
            else:
                trace_download(trace_id, "DOWNLOAD_REJECTED", route="RD_VERIFIED_MAGNET_NATIVE", reason=f"RDT pendiente no saludable: {phase}", rdt_id=rdt_id)
                return jsonify({"ok": False, "error": "RDT-Client tiene esta descarga pendiente. No la marco como correcta para evitar falso OK.", "trace_id": trace_id}), 409

    trace_download(trace_id, "RD_VERIFIED_RDT_NATIVE_IMPORT", hash=hash_value or "sin_hash", link_type=_link_kind(link), link_ref=_link_ref(link), manual_files=manual_files or "")
    if link.startswith("magnet:"):
        rd = rd_precheck_magnet(link, title, trace_id=trace_id, selected_file_ids=selected_file_ids, keep_alive=True)
        trace_download(trace_id, "RD_VERIFIED_PREFLIGHT_RESULT", ok=rd.get("ok"), id=rd.get("id") or "", reason=rd.get("reason") or "")
        if not rd.get("ok"):
            trace_download(trace_id, "DOWNLOAD_REJECTED", route="RD_VERIFIED_MAGNET_NATIVE", reason=rd.get("reason") or "RD no acepto preflight final")
            return jsonify({"ok": False, "error": "Real-Debrid no acepto esta descarga en la comprobacion final.", "reason": str(rd.get("reason") or "")[:220], "trace_id": trace_id}), 409
        rd_preflight_id = str(rd.get("id") or "")
        try:
            result = rdt_native_upload_magnet(link, title, target["key"], expected_hash=hash_value, manual_files=manual_files, trace_id=trace_id)
        except Exception:
            rd_cleanup_preflight(rd_preflight_id, trace_id=trace_id, why="rdt_upload_magnet_failed")
            raise
        rdt_hash = str(result.get("hash") or hash_value or hash_from_magnet(link))
        record_download(title, module, link, download_hash=rdt_hash, destino=target["key"], trace_id=trace_id, rdt_id=str(result.get("rdt_id") or ""), route="RD_VERIFIED_MAGNET_NATIVE", rd_preflight_id=str(rd.get("id") or ""))
        rdt_native_start_followup(str(result.get("rdt_id") or ""), rd_preflight_id, hash_value=rdt_hash, title=title, trace_id=trace_id)
        trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="rd_verified_native_import")
        trace_download(trace_id, "DOWNLOAD_END_PENDING" if result.get("pending") else "DOWNLOAD_END_OK", engine="RDT-Client", route="RD_VERIFIED_MAGNET_NATIVE", mode=result.get("mode"), rdt_id=result.get("rdt_id") or "", status=result.get("status") or "", already_present=False, elapsed=_elapsed(started))
        return jsonify({"ok": True, "message": "RD validado - enviado a RDT-Client", "module": module, "title": title, "engine": "RDT-Client", "already_present": False, "rdt_id": result.get("rdt_id") or "", "status": result.get("status") or "", "pending": bool(result.get("pending")), "trace_id": trace_id})

    if link.startswith(("http://", "https://")):
        raw = get_bytes(link, timeout=90)
        if not raw or len(raw) < 40:
            return jsonify({"ok": False, "error": "El enlace devolvio un torrent vacio o invalido.", "trace_id": trace_id}), 500
        rd = rd_precheck_torrent(raw, title, trace_id=trace_id, selected_file_ids=selected_file_ids, keep_alive=True)
        trace_download(trace_id, "RD_VERIFIED_PREFLIGHT_RESULT", ok=rd.get("ok"), id=rd.get("id") or "", reason=rd.get("reason") or "")
        if not rd.get("ok"):
            trace_download(trace_id, "DOWNLOAD_REJECTED", route="RD_VERIFIED_MAGNET_NATIVE", reason=rd.get("reason") or "RD no acepto preflight final")
            return jsonify({"ok": False, "error": "Real-Debrid no acepto este torrent en la comprobacion final.", "reason": str(rd.get("reason") or "")[:220], "trace_id": trace_id}), 409
        filename = safe_filename(title, module or "descarga")
        rd_preflight_id = str(rd.get("id") or "")
        try:
            result = rdt_native_upload_torrent(raw, filename, title, target["key"], expected_hash=hash_value, manual_files=manual_files, trace_id=trace_id)
        except Exception:
            rd_cleanup_preflight(rd_preflight_id, trace_id=trace_id, why="rdt_upload_torrent_failed")
            raise
        record_download(title, module, "rdt-native-torrent", torrent_bytes=raw, download_hash=str(result.get("hash") or ""), destino=target["key"], trace_id=trace_id, rdt_id=str(result.get("rdt_id") or ""), route="RD_VERIFIED_MAGNET_NATIVE", rd_preflight_id=str(rd.get("id") or ""))
        rdt_native_start_followup(str(result.get("rdt_id") or ""), rd_preflight_id, hash_value=str(result.get("hash") or hash_value or ""), title=title, trace_id=trace_id)
        trace_download(trace_id, "CLEANUP_FINAL", action="none", reason="rd_verified_native_torrent_import")
        trace_download(trace_id, "DOWNLOAD_END_PENDING" if result.get("pending") else "DOWNLOAD_END_OK", engine="RDT-Client", route="RD_VERIFIED_MAGNET_NATIVE", mode=result.get("mode"), rdt_id=result.get("rdt_id") or "", status=result.get("status") or "", elapsed=_elapsed(started))
        return jsonify({"ok": True, "message": "RD validado - enviado a RDT-Client", "module": module, "title": title, "engine": "RDT-Client", "rdt_id": result.get("rdt_id") or "", "status": result.get("status") or "", "pending": bool(result.get("pending")), "trace_id": trace_id})

    return jsonify({"ok": False, "error": "No pude resolver este RD OK a magnet o .torrent real.", "trace_id": trace_id}), 400


def api_rdt_send():
    trace_id = uuid.uuid4().hex[:10]
    started = time.monotonic()
    payload = request.get_json(silent=True) or {}
    link = str(payload.get("link") or payload.get("url") or "").strip()
    title = str(payload.get("title") or "").strip() or "descarga"
    module = str(payload.get("module") or "btdigg").strip() or "btdigg"
    payload_hash = normalize_infohash(payload.get("hash") or link)
    trace_download(trace_id, "DOWNLOAD_CLICK_RECEIVED", module=module, index=payload.get("index") or "", title=title, hash=payload_hash or "sin_hash", link_type=_link_kind(link), link_ref=_link_ref(link), remote=request.remote_addr)

    if not link:
        trace_download(trace_id, "DOWNLOAD_REJECTED", reason="sin enlace")
        return jsonify({"ok": False, "error": "La tarjeta no trae enlace/magnet para enviar.", "trace_id": trace_id}), 400

    expected_hash = payload_hash
    current_item: dict[str, Any] | None = None
    contract: dict[str, Any] | None = None
    if module == "btdigg":
        if _truthy(payload.get("from_history")):
            current_item, validation_error = _validate_btdigg_history_payload(payload, trace_id)
        else:
            current_item, validation_error = _validate_btdigg_download_payload(payload, trace_id)
        if validation_error:
            trace_download(trace_id, "DOWNLOAD_REJECTED", reason=validation_error)
            return jsonify({"ok": False, "error": validation_error, "trace_id": trace_id}), 409
        title = str(current_item.get("title") or title).strip() or title
        link = str(current_item.get("link") or link).strip()
        expected_hash = normalize_infohash(current_item.get("hash") or expected_hash or link)
        contract = build_btdigg_download_contract(current_item, link, expected_hash)
        client_contract = payload.get("contract") if isinstance(payload.get("contract"), dict) else {}
        if client_contract:
            trace_download(trace_id, "CLIENT_CONTRACT_HINT", rd_status=client_contract.get("rd_status") or "", qbt_status=client_contract.get("qbt_status") or "", qbt_was_existing=client_contract.get("qbt_was_existing"), selected_file_name=client_contract.get("selected_file_name") or "")
        trace_contract(trace_id, contract)

    target = dest(download_dest_from_title(title, "movies"))
    trace_download(trace_id, "DESTINATION_SELECTED", destino=target["key"], rdt_savepath=target["rdt_savepath"], qbt_savepath=target["qbt_savepath"], inbox=target["inbox"])

    try:
        if module == "btdigg":
            before_resolve = link
            trace_download(trace_id, "BTDIGG_RESOLVE_START", title=title, link_type=_link_kind(link), link_ref=_link_ref(link))
            link = resolve_btdigg_card_to_magnet(link, title, expected_hash=expected_hash)
            trace_download(trace_id, "BTDIGG_RESOLVE_OK", changed=str(before_resolve != link), link_type=_link_kind(link), link_ref=_link_ref(link), hash=hash_from_magnet(link) or "sin_hash")
            if contract is not None:
                contract["link"] = link
                if link.startswith("magnet:"):
                    contract["magnet"] = link
                    contract["hash"] = normalize_infohash(contract.get("hash") or link)
                elif link.startswith(("http://", "https://")):
                    contract["torrent_url"] = link
                route, route_reason = decide_btdigg_download_route(contract)
                trace_download(trace_id, "ROUTE_DECIDED", route=route, reason=route_reason, hash=contract.get("hash") or "sin_hash")
                trace_contract(trace_id, contract, route, route_reason)
                if route == "QBIT_REUSABLE":
                    return route_qbit_reusable(contract, link, target, title, module, started, trace_id)
                if route == "RD_REUSABLE":
                    return route_rd_reusable_native(contract, link, target, title, module, started, trace_id)
                if route == "RD_VERIFIED_MAGNET":
                    return route_rd_verified_magnet_native(contract, link, target, title, module, started, trace_id)
                trace_download(trace_id, "DOWNLOAD_REJECTED", route=route, reason=route_reason)
                return jsonify({"ok": False, "error": f"Resultado bloqueado por seguridad: {route_reason}", "route": route, "trace_id": trace_id}), 409

        if link.startswith("magnet:"):
            return handle_manual_magnet_flow(
                link=link,
                title=title,
                module=module,
                target=target,
                started=started,
                trace_id=trace_id,
                rdt_base=RDT_BASE,
                rdt_user=RDT_USER,
                rdt_pass=RDT_PASS,
                qbit_base=QBIT_BASE,
                qbit_user=QBIT_USER,
                qbit_pass=QBIT_PASS,
                rd_precheck_magnet=rd_precheck_magnet,
                qbit_add_url=qbit_add_url,
                hash_from_qbit_response=hash_from_qbit_response,
                hash_from_magnet=hash_from_magnet,
                record_download=record_download,
                rdt_select_main_files_async=rdt_select_main_files_async,
                log_download=log_download,
                trace_download=trace_download,
                elapsed=_elapsed,
            )

        if link.startswith(("http://", "https://")):
            return handle_manual_torrent_url_flow(
                link=link,
                title=title,
                module=module,
                target=target,
                started=started,
                trace_id=trace_id,
                qbit_base=QBIT_BASE,
                qbit_user=QBIT_USER,
                qbit_pass=QBIT_PASS,
                get_bytes=get_bytes,
                torrent_infohash_from_bytes=torrent_infohash_from_bytes,
                rd_precheck_torrent=rd_precheck_torrent,
                rdt_dispatch_torrent_bytes=rdt_dispatch_torrent_bytes,
                qbit_add_torrent_bytes=qbit_add_torrent_bytes,
                hash_from_qbit_response=hash_from_qbit_response,
                record_download=record_download,
                log_download=log_download,
                trace_download=trace_download,
                elapsed=_elapsed,
                link_ref=_link_ref,
                safe_filename=safe_filename,
            )

        trace_download(trace_id, "DOWNLOAD_REJECTED", reason="link no soportado", link_type=_link_kind(link), link_ref=_link_ref(link))
        return jsonify({"ok": False, "error": "No pude resolver este resultado a magnet o .torrent real. Prueba otro resultado."}), 400
    except Exception as exc:
        trace_download(trace_id, "DOWNLOAD_END_ERROR", error=f"{type(exc).__name__}: {exc}", elapsed=_elapsed(started))
        log_download(f"ERROR DESCARGAR {module} RD-FIRST {type(exc).__name__}: {exc}")
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
