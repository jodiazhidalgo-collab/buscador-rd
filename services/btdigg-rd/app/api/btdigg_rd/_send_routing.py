from __future__ import annotations

from typing import Any

from .classification import (
    download_dest_from_title as configured_download_dest_from_title,
    title_has_tv_marker as configured_title_has_tv_marker,
)
from .config import TORRENT_INBOX


def title_has_tv_marker(value: Any) -> bool:
    return configured_title_has_tv_marker(value)


def download_dest_from_title(title: Any, fallback: str = "movies") -> str:
    return configured_download_dest_from_title(title, fallback)


def dest(value: Any) -> dict[str, str]:
    raw = str(value or "movies").strip().lower()
    if raw not in {"movies", "tv", "manual"}:
        raw = "movies"
    labels = {"movies": "Películas", "tv": "Series", "manual": "Manual"}
    return {
        "key": raw,
        "label": labels[raw],
        "rdt_savepath": f"/data/downloads/{raw}",
        "qbt_savepath": f"/data/downloads/torrents/complete/{raw}",
        "inbox": str(TORRENT_INBOX / raw),
    }
