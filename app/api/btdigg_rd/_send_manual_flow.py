from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Callable

from flask import jsonify


def handle_manual_magnet_flow(
    *,
    link: str,
    title: str,
    module: str,
    target: dict[str, str],
    started: float,
    trace_id: str,
    rdt_base: str,
    rdt_user: str,
    rdt_pass: str,
    qbit_base: str,
    qbit_user: str,
    qbit_pass: str,
    rd_precheck_magnet: Callable[..., dict[str, Any]],
    qbit_add_url: Callable[..., str],
    hash_from_qbit_response: Callable[[Any], str],
    hash_from_magnet: Callable[[str], str],
    record_download: Callable[..., None],
    rdt_select_main_files_async: Callable[..., None],
    log_download: Callable[[str], None],
    trace_download: Callable[..., None],
    elapsed: Callable[[float], str],
):
    trace_download(trace_id, "MAGNET_FLOW_START", hash=hash_from_magnet(link) or "sin_hash")
    rd = rd_precheck_magnet(link, title, trace_id=trace_id)
    trace_download(trace_id, "RD_PREFILTER_RESULT", ok=rd.get("ok"), id=rd.get("id") or "", reason=rd.get("reason") or "")
    if rd.get("ok"):
        trace_download(trace_id, "ROUTE_SELECTED", engine="RDT-Client", reason="RD acepto magnet")
        response = qbit_add_url(rdt_base, rdt_user, rdt_pass, link, target, is_rdt=True, trace_id=trace_id, engine_label="RDT")
        rdt_hash = hash_from_qbit_response(response) or hash_from_magnet(link)
        trace_download(trace_id, "RDT_HASH_RESOLVED", hash=rdt_hash or "sin_hash")
        record_download(title, module, link, download_hash=rdt_hash, destino=target["key"], trace_id=trace_id)
        rdt_select_main_files_async(rdt_hash, title, trace_id=trace_id)
        log_download(f"DESCARGAR {module} MAGNET RD-FIRST OK destino={target['key']} titulo={title!r} resp={response[:160]!r}")
        trace_download(trace_id, "DOWNLOAD_END_OK", engine="RDT-Client", elapsed=elapsed(started))
        return jsonify({"ok": True, "message": "RD aceptó · enviado a RDT-Client", "module": module, "title": title, "engine": "RDT-Client"})

    trace_download(trace_id, "ROUTE_SELECTED", engine="qBittorrent", reason=rd.get("reason") or "RD no acepto magnet")
    response = qbit_add_url(qbit_base, qbit_user, qbit_pass, link, target, is_rdt=False, trace_id=trace_id, engine_label="qBittorrent")
    qbit_hash = hash_from_qbit_response(response) or hash_from_magnet(link)
    trace_download(trace_id, "QBIT_HASH_RESOLVED", hash=qbit_hash or "sin_hash")
    record_download(title, module, link, download_hash=qbit_hash, destino=target["key"], trace_id=trace_id)
    log_download(f"DESCARGAR {module} MAGNET RD-FIRST FALLBACK_QBIT destino={target['key']} titulo={title!r} motivo={str(rd.get('reason') or '')[:180]!r} resp={response[:160]!r}")
    trace_download(trace_id, "DOWNLOAD_END_OK", engine="qBittorrent", elapsed=elapsed(started), reason=rd.get("reason") or "")
    return jsonify({"ok": True, "message": "RD no lo aceptó · enviado a qBittorrent", "module": module, "title": title, "engine": "qBittorrent", "reason": str(rd.get("reason") or "")[:200]})


def handle_manual_torrent_url_flow(
    *,
    link: str,
    title: str,
    module: str,
    target: dict[str, str],
    started: float,
    trace_id: str,
    qbit_base: str,
    qbit_user: str,
    qbit_pass: str,
    get_bytes: Callable[..., bytes],
    torrent_infohash_from_bytes: Callable[[bytes], str],
    rd_precheck_torrent: Callable[..., dict[str, Any]],
    rdt_dispatch_torrent_bytes: Callable[..., dict[str, str]],
    qbit_add_torrent_bytes: Callable[..., str],
    hash_from_qbit_response: Callable[[Any], str],
    record_download: Callable[..., None],
    log_download: Callable[[str], None],
    trace_download: Callable[..., None],
    elapsed: Callable[[float], str],
    link_ref: Callable[[str], str],
    safe_filename: Callable[[Any, str], str],
):
    trace_download(trace_id, "URL_FLOW_START", url=link_ref(link))
    download_started = time.monotonic()
    raw = get_bytes(link, timeout=90)
    trace_download(trace_id, "URL_DOWNLOAD_OK", bytes=len(raw or b""), elapsed=elapsed(download_started), torrent_hash=torrent_infohash_from_bytes(raw) or "sin_hash")
    if not raw or len(raw) < 40:
        trace_download(trace_id, "URL_DOWNLOAD_INVALID", bytes=len(raw or b""))
        return jsonify({"ok": False, "error": "El enlace devolvió un torrent vacío o inválido."}), 500

    rd = rd_precheck_torrent(raw, title, trace_id=trace_id)
    trace_download(trace_id, "RD_PREFILTER_RESULT", ok=rd.get("ok"), id=rd.get("id") or "", reason=rd.get("reason") or "")
    base_name = safe_filename(title, module or "descarga")

    if rd.get("ok"):
        trace_download(trace_id, "ROUTE_SELECTED", engine="RDT-Client", reason="RD acepto torrent")
        rdt = rdt_dispatch_torrent_bytes(raw, base_name, target, title, trace_id=trace_id)
        path = rdt.get("path") or ""
        record_download(title, module, path or "rdt-api-torrent", torrent_path=path or None, torrent_bytes=raw, download_hash=rdt.get("hash") or "", destino=target["key"], trace_id=trace_id)
        log_download(f"DESCARGAR {module} TORRENT RD-FIRST OK destino={target['key']} modo={rdt.get('mode')} archivo={Path(path).name if path else 'api'} titulo={title!r}")
        trace_download(trace_id, "DOWNLOAD_END_OK", engine="RDT-Client", mode=rdt.get("mode"), path=path, elapsed=elapsed(started))
        return jsonify({"ok": True, "message": "RD aceptó · enviado a RDT-Client", "module": module, "title": title, "engine": "RDT-Client", "path": path})

    trace_download(trace_id, "ROUTE_SELECTED", engine="qBittorrent", reason=rd.get("reason") or "RD no acepto torrent")
    response = qbit_add_torrent_bytes(qbit_base, qbit_user, qbit_pass, raw, base_name, target, trace_id=trace_id, engine_label="qBittorrent")
    qbit_hash = hash_from_qbit_response(response) or torrent_infohash_from_bytes(raw)
    trace_download(trace_id, "QBIT_HASH_RESOLVED", hash=qbit_hash or "sin_hash")
    record_download(title, module, "qbit-fallback-torrent", download_hash=qbit_hash, torrent_bytes=raw, destino=target["key"], trace_id=trace_id)
    log_download(f"DESCARGAR {module} TORRENT RD-FIRST FALLBACK_QBIT destino={target['key']} titulo={title!r} motivo={str(rd.get('reason') or '')[:180]!r} resp={response[:160]!r}")
    trace_download(trace_id, "DOWNLOAD_END_OK", engine="qBittorrent", elapsed=elapsed(started), reason=rd.get("reason") or "")
    return jsonify({"ok": True, "message": "RD no lo aceptó · enviado a qBittorrent", "module": module, "title": title, "engine": "qBittorrent", "reason": str(rd.get("reason") or "")[:200]})
