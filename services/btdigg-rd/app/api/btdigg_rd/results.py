from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import BTDIGG_EXPORTS_DIR
from .utils import read_json


BTIH_RE = re.compile(r"(?:btih:|btih%3a)([a-z0-9]{32,40})", re.I)


def normalize_infohash(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    match = BTIH_RE.search(text)
    if match:
        text = match.group(1)
    text = re.sub(r"[^a-z0-9]", "", text)
    return text if len(text) in (32, 40) else ""


def _result_hash(item: dict[str, Any]) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("hash", "infohash", "btih", "qbit_hash", "torrent_hash"):
        value = normalize_infohash(item.get(key))
        if value:
            return value
    for key in ("qbit_magnet", "magnet", "torrent_url", "url", "source_url", "link"):
        value = normalize_infohash(item.get(key))
        if value:
            return value
    return ""


def _num_float(value: Any) -> float:
    try:
        if value in ("", None):
            return 0.0
        return float(str(value).replace(",", "."))
    except Exception:
        return 0.0


def _num_int(value: Any) -> int:
    try:
        if value in ("", None):
            return 0
        return int(float(str(value).replace(",", ".")))
    except Exception:
        return 0


def _rd_ok_status(status: Any) -> bool:
    return str(status or "") in {"RD_INSTANT", "RD_OK", "DIRECT_OK", "TORRENT_PENDIENTE"}


def _result_source(item: dict[str, Any]) -> str:
    if _rd_ok_status(item.get("rd_status")):
        return "RD"
    if str(item.get("qbt_status") or "").startswith("QBT_"):
        return "qBit"
    return "BTDigg"


def _result_status(item: dict[str, Any]) -> str:
    rd = str(item.get("rd_status") or "")
    qbt = str(item.get("qbt_status") or "")
    if rd == "RD_INSTANT":
        return "RD instant"
    if rd == "RD_OK":
        return "RD OK"
    if rd == "DIRECT_OK":
        return "Directo"
    if qbt in {"QBT_OK", "QBT_VIVO"}:
        return "qBit vivo"
    return rd or qbt or "-"


def _clean_display_title(value: Any) -> str:
    text = str(value or "").strip().lstrip("/\\").strip()
    return text or "(sin nombre)"


def _result_added(item: dict[str, Any]) -> str:
    for key in ("added", "publish_date", "pubdate", "date", "time"):
        value = str(item.get(key) or "").strip()
        if value:
            return value[:16]
    raw_context = str(item.get("raw_context") or "")
    match = re.search(r"found\s+([^<\n\r]{1,40}? ago)", raw_context, re.I)
    if match:
        return match.group(1).strip()
    return "hoy"


def sanitize_result_item(item: Any, idx: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"index": idx, "title": str(item)[:200], "size": "", "link": ""}

    title = _clean_display_title(
        item.get("qbit_name")
        or item.get("selected_file_name")
        or item.get("btdigg_file_name")
        or item.get("title")
        or item.get("name")
        or "(sin nombre)"
    )
    link = item.get("qbit_magnet") or item.get("magnet") or item.get("torrent_url") or item.get("url") or item.get("source_url") or ""
    item_hash = _result_hash(item)
    size = item.get("selected_file_size_gb") or item.get("qbit_size_gb") or item.get("size_gb") or item.get("rd_largest_gb") or item.get("btdigg_file_size_gb") or ""
    size_value = _num_float(size)
    size_txt = f"{size_value:.2f} GB" if size not in ("", None) else ""
    source = _result_source(item)
    status = _result_status(item)
    seeds = item.get("qbit_seeds") or item.get("qbit_total_seeds") or item.get("seeders") or item.get("qbt_seeds") or ""
    peers = item.get("qbit_peers") or item.get("peers") or item.get("qbt_peers") or ""

    return {
        "index": idx,
        "title": title[:260],
        "hash": item_hash,
        "size": size_txt,
        "size_value": size_value,
        "quality": str(item.get("quality") or item.get("tracker_name") or item.get("indexer") or source)[:80],
        "source": source[:80],
        "confidence": str(item.get("confidence") or item.get("qbit_confidence") or item.get("score") or item.get("rd_status") or item.get("qbt_status") or "")[:80],
        "status": status[:80],
        "seeds": seeds,
        "seeds_value": _num_int(seeds),
        "peers": peers,
        "peers_value": _num_int(peers),
        "added": _result_added(item),
        "added_value": idx,
        "link": str(link),
        "raw": item,
    }


def _source_sort_rank(item: dict[str, Any]) -> int:
    source = str(item.get("source") or "").lower()
    if source == "rd":
        return 0
    if source == "qbit":
        return 1
    return 2


def load_results(path: Path | str | None = None, export_dir: Path | str | None = None) -> list[dict[str, Any]]:
    data = None
    if path:
        data = read_json(Path(path))
    if data is None:
        base = Path(export_dir) if export_dir else BTDIGG_EXPORTS_DIR
        data = read_json(base / "EDITOR_MAESTRO_SHOWN.json")
        if data is None:
            data = read_json(base / "ULTIMOS_RESULTADOS.json")
    if data is None:
        data = []
    if isinstance(data, dict):
        items = data.get("shown") or data.get("results") or data.get("items") or []
    else:
        items = data or []
    visible = [sanitize_result_item(item, i) for i, item in enumerate(items, 1)]
    visible.sort(
        key=lambda item: (
            _source_sort_rank(item),
            -_num_float(item.get("size_value")),
            str(item.get("title") or "").lower(),
        )
    )
    for i, item in enumerate(visible, 1):
        item["index"] = i
    return visible


def resolve_btdigg_card_to_magnet(link: str, title: str, expected_hash: str = "") -> str:
    raw_link = str(link or "").strip()
    expected_hash = normalize_infohash(expected_hash)
    if raw_link.startswith("magnet:"):
        link_hash = normalize_infohash(raw_link)
        if expected_hash and link_hash and expected_hash != link_hash:
            raise ValueError("El magnet no coincide con la fila seleccionada.")
        return raw_link
    if raw_link.startswith(("http://", "https://")):
        link_hash = normalize_infohash(raw_link)
        if expected_hash and link_hash and expected_hash != link_hash:
            raise ValueError("El enlace no coincide con la fila seleccionada.")
        return raw_link

    return raw_link
