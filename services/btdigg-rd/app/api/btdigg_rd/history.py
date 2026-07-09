from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import HISTORY_FILE, QBIT_NO_SEEDS_HISTORY_FILE
from .utils import read_json


HISTORY_RETENTION_DAYS = 30
HISTORY_MAX_SEARCHES = 30


def _now() -> datetime:
    return datetime.now().astimezone()


def _safe_text(value: Any, limit: int = 260) -> str:
    return str(value or "").strip()[:limit]


def _num_int(value: Any) -> int:
    try:
        if value in ("", None):
            return 0
        return int(float(str(value).replace(",", ".")))
    except Exception:
        return 0


def _clean_result(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"title": _safe_text(item), "link": ""}
    seeds = item.get("seeds")
    peers = item.get("peers")
    return {
        "index": item.get("index"),
        "title": _safe_text(item.get("title")),
        "hash": _safe_text(item.get("hash"), 80),
        "size": _safe_text(item.get("size"), 40),
        "size_value": item.get("size_value") or 0,
        "quality": _safe_text(item.get("quality"), 80),
        "source": _safe_text(item.get("source"), 80),
        "confidence": _safe_text(item.get("confidence"), 80),
        "status": _safe_text(item.get("status"), 80),
        "seeds": seeds if seeds not in ("", None) else "",
        "seeds_value": item.get("seeds_value") or 0,
        "peers": peers if peers not in ("", None) else "",
        "peers_value": item.get("peers_value") or 0,
        "added": _safe_text(item.get("added"), 80),
        "added_value": item.get("added_value") or item.get("index") or 0,
        "link": str(item.get("link") or ""),
        "raw": item.get("raw") if isinstance(item.get("raw"), dict) else {},
    }


def _load_entries(path: Path = HISTORY_FILE) -> list[dict[str, Any]]:
    data = read_json(path)
    entries = data.get("searches") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []
    return [item for item in entries if isinstance(item, dict)]


def _prune(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cutoff = _now() - timedelta(days=HISTORY_RETENTION_DAYS)
    kept: list[dict[str, Any]] = []
    for item in entries:
        try:
            created = datetime.fromisoformat(str(item.get("created_at") or ""))
            if created.tzinfo is None:
                created = created.astimezone()
        except Exception:
            created = _now()
        if created >= cutoff:
            kept.append(item)
    kept.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return kept[:HISTORY_MAX_SEARCHES]


def _write_entries(entries: list[dict[str, Any]], path: Path = HISTORY_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "retention_days": HISTORY_RETENTION_DAYS,
        "max_searches": HISTORY_MAX_SEARCHES,
        "searches": _prune(entries),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record_search(payload: dict[str, Any], results: list[dict[str, Any]]) -> None:
    if not results:
        return
    now = _now()
    entry = {
        "id": uuid.uuid4().hex[:12],
        "created_at": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "date_label": now.strftime("%d/%m/%Y"),
        "time_label": now.strftime("%H:%M"),
        "query": _safe_text(payload.get("query")),
        "pages": _safe_text(payload.get("pages"), 40),
        "mode": _safe_text(payload.get("mode"), 20),
        "min_gb": _safe_text(payload.get("min_gb"), 40),
        "result_count": len(results),
        "results": [_clean_result(item) for item in results],
    }
    entries = _load_entries(HISTORY_FILE)
    entries.insert(0, entry)
    _write_entries(entries, HISTORY_FILE)


def _result_identity(item: dict[str, Any]) -> str:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else item
    return _safe_text(
        raw.get("hash")
        or raw.get("magnet")
        or raw.get("torrent_url")
        or item.get("hash")
        or item.get("link")
        or item.get("title"),
        500,
    ).lower()


def _is_qbit_no_seed_result(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    qbt_status = str(item.get("qbt_status") or "").strip()
    if qbt_status != "QBT_NO_PEERS":
        return False
    return _num_int(item.get("qbt_seeds")) <= 0


def _clean_qbit_no_seed_result(item: dict[str, Any], idx: int) -> dict[str, Any]:
    from .results import sanitize_result_item

    cleaned = sanitize_result_item(item, idx)
    seeds = _num_int(item.get("qbt_seeds"))
    peers = _num_int(item.get("qbt_peers"))
    cleaned.update(
        {
            "quality": "qBit",
            "source": "qBit",
            "confidence": str(item.get("qbt_status") or "QBT_NO_PEERS")[:80],
            "status": "Sin semillas qB",
            "seeds": seeds,
            "seeds_value": seeds,
            "peers": peers,
            "peers_value": peers,
        }
    )
    return _clean_result(cleaned)


def record_qbit_no_seed_search(payload: dict[str, Any], results: list[dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in results:
        if not _is_qbit_no_seed_result(item):
            continue
        cleaned = _clean_qbit_no_seed_result(item, len(rows) + 1)
        identity = _result_identity(cleaned)
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        rows.append(cleaned)
    if not rows:
        return
    now = _now()
    entry = {
        "id": uuid.uuid4().hex[:12],
        "created_at": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "date_label": now.strftime("%d/%m/%Y"),
        "time_label": now.strftime("%H:%M"),
        "query": _safe_text(payload.get("query")),
        "pages": _safe_text(payload.get("pages"), 40),
        "mode": _safe_text(payload.get("mode"), 20),
        "min_gb": _safe_text(payload.get("min_gb"), 40),
        "result_count": len(rows),
        "results": rows,
    }
    entries = _load_entries(QBIT_NO_SEEDS_HISTORY_FILE)
    entries.insert(0, entry)
    _write_entries(entries, QBIT_NO_SEEDS_HISTORY_FILE)


def record_qbit_no_seed_search_from_export(payload: dict[str, Any], export_dir: Path | str) -> None:
    data = read_json(Path(export_dir) / "ULTIMOS_RESULTADOS.json")
    if not isinstance(data, list):
        return
    record_qbit_no_seed_search(payload, [item for item in data if isinstance(item, dict)])


def _load_history_from(path: Path) -> dict[str, Any]:
    entries = _prune(_load_entries(path))
    days: list[dict[str, Any]] = []
    by_day: dict[str, dict[str, Any]] = {}
    for entry in entries:
        date_key = str(entry.get("date") or str(entry.get("created_at") or "")[:10])
        day = by_day.get(date_key)
        if not day:
            day = {
                "date": date_key,
                "label": entry.get("date_label") or date_key,
                "count": 0,
                "searches": [],
            }
            by_day[date_key] = day
            days.append(day)
        day["searches"].append(entry)
        day["count"] += 1
    return {
        "retention_days": HISTORY_RETENTION_DAYS,
        "max_searches": HISTORY_MAX_SEARCHES,
        "days": days,
    }


def load_history() -> dict[str, Any]:
    return _load_history_from(HISTORY_FILE)


def load_qbit_no_seed_history() -> dict[str, Any]:
    return _load_history_from(QBIT_NO_SEEDS_HISTORY_FILE)
