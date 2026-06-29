from __future__ import annotations

import json
import re
from typing import Any

from .config import BTDIGG_DIR
from .utils import read_json


TV_SERIES_TEMPLATES_KEY = "tv_series_templates"
TV_SERIES_WORDS_KEY = "tv_series_words"

DEFAULT_SERIES_TEMPLATES = [
    "SXXEXX",
    "SXEX",
    "SXX EXX",
    "XXxXX",
    "XxXX",
    "Temporada XX",
    "Temp XX",
    "Season XX",
    "Capitulo XX",
    "Capitulo X",
    "Episode XX",
    "Episodio XX",
]

DEFAULT_SERIES_WORDS = [
    "capitulo",
    "capítulo",
    "episodio",
    "episode",
    "temporada",
    "temp",
    "season",
]


def _clean_lines(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, str):
        raw_items = value.splitlines()
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = fallback

    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = re.sub(r"\s+", " ", str(item or "").strip())
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text[:120])
        if len(out) >= 80:
            break
    return out or list(fallback)


def default_tv_rules() -> dict[str, list[str]]:
    return {
        "series_templates": list(DEFAULT_SERIES_TEMPLATES),
        "series_words": list(DEFAULT_SERIES_WORDS),
    }


def normalize_tv_rules(raw: Any) -> dict[str, list[str]]:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "series_templates": _clean_lines(raw.get("series_templates"), DEFAULT_SERIES_TEMPLATES),
        "series_words": _clean_lines(raw.get("series_words"), DEFAULT_SERIES_WORDS),
    }


def load_tv_rules() -> dict[str, list[str]]:
    cfg = read_json(BTDIGG_DIR / "config.json") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return normalize_tv_rules(
        {
            "series_templates": cfg.get(TV_SERIES_TEMPLATES_KEY),
            "series_words": cfg.get(TV_SERIES_WORDS_KEY),
        }
    )


def save_tv_rules(raw: Any) -> dict[str, list[str]]:
    rules = normalize_tv_rules(raw)
    path = BTDIGG_DIR / "config.json"
    cfg = read_json(path) or {}
    if not isinstance(cfg, dict):
        cfg = {}

    cfg[TV_SERIES_TEMPLATES_KEY] = rules["series_templates"]
    cfg[TV_SERIES_WORDS_KEY] = rules["series_words"]
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rules


def reset_tv_rules() -> dict[str, list[str]]:
    return save_tv_rules(default_tv_rules())


def template_to_regex(template: str) -> re.Pattern[str]:
    parts: list[str] = []
    i = 0
    while i < len(template):
        char = template[i]
        if char == "X":
            j = i
            while j < len(template) and template[j] == "X":
                j += 1
            parts.append(rf"\d{{1,{j - i}}}")
            i = j
            continue
        if char.isspace() or char in ".-_":
            parts.append(r"[\s._-]*")
        else:
            parts.append(re.escape(char))
        i += 1
    return re.compile(r"(?<![a-z0-9])" + "".join(parts) + r"(?![a-z0-9])", re.I)


def word_to_regex(word: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + re.escape(str(word or "").strip()) + r"(?![a-z0-9])", re.I)


def classify_title(title: Any, rules: dict[str, Any] | None = None, fallback: str = "movies") -> dict[str, Any]:
    rules = normalize_tv_rules(rules) if isinstance(rules, dict) else load_tv_rules()
    title_text = re.sub(r"\s+", " ", str(title or "").strip())
    fallback = str(fallback or "movies").strip().lower()
    if fallback not in {"movies", "tv", "manual"}:
        fallback = "movies"

    for template in rules["series_templates"]:
        try:
            if template_to_regex(template).search(title_text):
                return {"destination": "tv", "matched_type": "template", "matched_rule": template}
        except re.error:
            continue

    for word in rules["series_words"]:
        if word and word_to_regex(word).search(title_text):
            return {"destination": "tv", "matched_type": "word", "matched_rule": word}

    return {"destination": fallback, "matched_type": "", "matched_rule": ""}


def title_has_tv_marker(value: Any) -> bool:
    return classify_title(value, fallback="movies").get("destination") == "tv"


def download_dest_from_title(title: Any, fallback: str = "movies") -> str:
    return str(classify_title(title, fallback=fallback).get("destination") or fallback)
