from __future__ import annotations

from typing import Any

from ._send_tracking import _int_value, _link_kind, _link_ref, clean_text, trace_download
from .config import HISTORY_FILE, QBIT_NO_SEEDS_HISTORY_FILE
from .results import load_results, normalize_infohash
from .utils import read_json


RD_REUSABLE_STATUSES = {"RD_OK", "RD_INSTANT", "DIRECT_OK"}
QBIT_REUSABLE_STATUSES = {"QBT_OK", "QBT_VIVO"}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def _payload_index(value: Any) -> int:
    try:
        return int(str(value or "").strip())
    except Exception:
        return 0


def _validate_btdigg_download_payload(payload: dict[str, Any], trace_id: str) -> tuple[dict[str, Any] | None, str]:
    results = load_results()
    index = _payload_index(payload.get("index"))
    client_link = str(payload.get("link") or payload.get("url") or "").strip()
    client_hash = normalize_infohash(payload.get("hash") or payload.get("btih") or client_link)
    client_source = clean_text(payload.get("source"))
    client_status = clean_text(payload.get("status"))

    trace_download(
        trace_id,
        "BTDIGG_CLIENT_CARD",
        index=index or "sin_index",
        hash=client_hash or "sin_hash",
        source=client_source,
        status=client_status,
        visible_results=len(results),
    )

    if not results:
        return None, "No hay resultados actuales para validar el clic."
    if index < 1 or index > len(results):
        return None, f"El indice {index or '(vacio)'} no existe en los resultados actuales."

    item = results[index - 1]
    server_link = str(item.get("link") or "").strip()
    server_hash = normalize_infohash(item.get("hash") or server_link)
    server_title = str(item.get("title") or "").strip()

    if not server_link:
        return None, "El resultado actual no trae magnet/enlace real."
    if client_hash and server_hash and client_hash != server_hash:
        return None, f"El hash del clic no coincide con la fila actual: {client_hash} != {server_hash}."

    client_link_hash = normalize_infohash(client_link)
    if client_link_hash and server_hash and client_link_hash != server_hash:
        return None, f"El enlace del clic no coincide con la fila actual: {client_link_hash} != {server_hash}."
    if client_link and not client_link_hash and client_link != server_link:
        return None, "El enlace del clic no coincide con el enlace actual del servidor."

    trace_download(
        trace_id,
        "BTDIGG_SERVER_CARD_OK",
        index=index,
        hash=server_hash or "sin_hash",
        title=server_title,
        link_type=_link_kind(server_link),
        link_ref=_link_ref(server_link),
        source=item.get("source") or "",
        status=item.get("status") or "",
    )
    return item, ""


def _history_file_for_kind(kind: Any):
    if str(kind or "").strip() == "qbit_no_seeds":
        return QBIT_NO_SEEDS_HISTORY_FILE
    return HISTORY_FILE


def _find_history_result(search_id: Any, result_position: Any, history_kind: Any = "") -> dict[str, Any] | None:
    search_id = str(search_id or "").strip()
    try:
        position = int(result_position)
    except Exception:
        position = 0
    if not search_id or position < 1:
        return None
    data = read_json(_history_file_for_kind(history_kind))
    entries = data.get("searches") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("id") or "").strip() != search_id:
            continue
        results = entry.get("results") if isinstance(entry.get("results"), list) else []
        if position <= len(results) and isinstance(results[position - 1], dict):
            return dict(results[position - 1])
        return None
    return None


def _validate_btdigg_history_payload(payload: dict[str, Any], trace_id: str) -> tuple[dict[str, Any] | None, str]:
    history_id = str(payload.get("history_id") or "").strip()
    history_kind = str(payload.get("history_kind") or "").strip()
    history_result = _payload_index(payload.get("history_result") or payload.get("history_index"))
    client_link = str(payload.get("link") or payload.get("url") or "").strip()
    client_hash = normalize_infohash(payload.get("hash") or payload.get("btih") or client_link)
    client_source = clean_text(payload.get("source"))
    client_status = clean_text(payload.get("status"))

    trace_download(
        trace_id,
        "BTDIGG_HISTORY_CARD",
        history_kind=history_kind or "default",
        history_id=history_id or "sin_id",
        result=history_result or "sin_result",
        hash=client_hash or "sin_hash",
        source=client_source,
        status=client_status,
    )

    item = _find_history_result(history_id, history_result, history_kind)
    if not item:
        return None, "No encuentro esa tarjeta guardada en el historial."

    server_link = str(item.get("link") or "").strip()
    server_hash = normalize_infohash(item.get("hash") or server_link)
    server_title = str(item.get("title") or "").strip()

    if not server_link:
        return None, "La tarjeta guardada no trae magnet/enlace real."
    if client_hash and server_hash and client_hash != server_hash:
        return None, f"El hash del historial no coincide: {client_hash} != {server_hash}."

    client_link_hash = normalize_infohash(client_link)
    if client_link_hash and server_hash and client_link_hash != server_hash:
        return None, f"El enlace del historial no coincide: {client_link_hash} != {server_hash}."
    if client_link and not client_link_hash and client_link != server_link:
        return None, "El enlace del historial no coincide con la tarjeta guardada."

    trace_download(
        trace_id,
        "BTDIGG_HISTORY_CARD_OK",
        history_id=history_id,
        result=history_result,
        hash=server_hash or "sin_hash",
        title=server_title,
        link_type=_link_kind(server_link),
        link_ref=_link_ref(server_link),
        source=item.get("source") or "",
        status=item.get("status") or "",
    )
    return item, ""


def build_btdigg_download_contract(item: dict[str, Any], link: str, expected_hash: str = "") -> dict[str, Any]:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    magnet = str(raw.get("qbit_magnet") or raw.get("magnet") or "").strip()
    torrent_url = str(raw.get("torrent_url") or raw.get("url") or raw.get("source_url") or "").strip()
    if str(link or "").startswith("magnet:") and not magnet:
        magnet = str(link or "").strip()
    if str(link or "").startswith(("http://", "https://")) and not torrent_url:
        torrent_url = str(link or "").strip()
    item_hash = normalize_infohash(raw.get("hash") or raw.get("infohash") or item.get("hash") or expected_hash or magnet or link)
    return {
        "index": item.get("index"),
        "title": str(raw.get("selected_file_name") or raw.get("qbit_name") or raw.get("title") or item.get("title") or "").strip(),
        "hash": item_hash,
        "link": str(link or "").strip(),
        "magnet": magnet,
        "torrent_url": torrent_url,
        "rd_status": str(raw.get("rd_status") or "").strip(),
        "rd_existing": _truthy(raw.get("rd_existing")),
        "rd_links": _int_value(raw.get("rd_links")),
        "rd_torrent_id": str(raw.get("rd_torrent_id") or "").strip(),
        "selected_file_name": str(raw.get("selected_file_name") or "").strip(),
        "selected_file_ids": str(raw.get("selected_file_ids") or "").strip(),
        "qbt_status": str(raw.get("qbt_status") or "").strip(),
        "qbt_was_existing": _truthy(raw.get("qbt_was_existing")),
        "qbt_reason": str(raw.get("qbt_reason") or "").strip(),
    }


def decide_btdigg_download_route(contract: dict[str, Any]) -> tuple[str, str]:
    rd_status = str(contract.get("rd_status") or "").strip()
    qbt_status = str(contract.get("qbt_status") or "").strip()
    rd_existing = _truthy(contract.get("rd_existing"))
    rd_links = _int_value(contract.get("rd_links"))
    if rd_status in RD_REUSABLE_STATUSES and rd_existing:
        return "RD_REUSABLE", f"rd_status={rd_status} rd_existing={rd_existing} rd_links={rd_links}"
    if qbt_status in QBIT_REUSABLE_STATUSES:
        return "QBIT_REUSABLE", f"qbt_status={qbt_status}"
    if rd_status in RD_REUSABLE_STATUSES and rd_links > 0:
        return "RD_VERIFIED_MAGNET", f"rd_status={rd_status} rd_existing={rd_existing} rd_links={rd_links}"
    if rd_status == "NO_INSTANT" and qbt_status in QBIT_REUSABLE_STATUSES:
        return "QBIT_REUSABLE", f"rd_status=NO_INSTANT qbt_status={qbt_status}"
    if not (contract.get("magnet") or contract.get("torrent_url") or contract.get("link")):
        return "BLOCKED_NO_LINK", "sin magnet/torrent_url validado"
    return "BLOCKED_UNSAFE", f"sin evidencia reutilizable rd_status={rd_status or '-'} qbt_status={qbt_status or '-'}"


def trace_contract(trace_id: str, contract: dict[str, Any], route: str = "", reason: str = "") -> None:
    trace_download(
        trace_id,
        "CONTRACT_SUMMARY",
        route=route or "",
        reason=reason or "",
        index=contract.get("index"),
        hash=contract.get("hash") or "sin_hash",
        rd_status=contract.get("rd_status") or "",
        rd_existing=contract.get("rd_existing"),
        rd_links=contract.get("rd_links"),
        rd_torrent_id=contract.get("rd_torrent_id") or "",
        qbt_status=contract.get("qbt_status") or "",
        qbt_was_existing=contract.get("qbt_was_existing"),
        preferred_file_name=contract.get("selected_file_name") or "",
    )
