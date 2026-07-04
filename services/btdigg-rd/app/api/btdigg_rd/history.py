from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from .config import HISTORY_FILE
from .utils import read_json


HISTORY_RETENTION_DAYS = 30
HISTORY_MAX_SEARCHES = 30


def _now() -> datetime:
    return datetime.now().astimezone()


def _safe_text(value: Any, limit: int = 260) -> str:
    return str(value or "").strip()[:limit]


def _clean_result(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"title": _safe_text(item), "link": ""}
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
        "seeds": item.get("seeds") or "",
        "seeds_value": item.get("seeds_value") or 0,
        "peers": item.get("peers") or "",
        "peers_value": item.get("peers_value") or 0,
        "added": _safe_text(item.get("added"), 80),
        "added_value": item.get("added_value") or item.get("index") or 0,
        "link": str(item.get("link") or ""),
        "raw": item.get("raw") if isinstance(item.get("raw"), dict) else {},
    }


def _load_entries() -> list[dict[str, Any]]:
    data = read_json(HISTORY_FILE)
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


def _write_entries(entries: list[dict[str, Any]]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "retention_days": HISTORY_RETENTION_DAYS,
        "max_searches": HISTORY_MAX_SEARCHES,
        "searches": _prune(entries),
    }
    HISTORY_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    entries = _load_entries()
    entries.insert(0, entry)
    _write_entries(entries)


def load_history() -> dict[str, Any]:
    entries = _prune(_load_entries())
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
