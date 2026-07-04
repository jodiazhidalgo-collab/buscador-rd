from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


KNOWN_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".m4v",
    ".avi",
    ".mov",
    ".wmv",
    ".ts",
    ".m2ts",
    ".mts",
    ".webm",
    ".zip",
    ".rar",
    ".7z",
}

SITE_WORDS = (
    "uindex",
    "wolfmax4k",
    "newpct1",
    "atomohd",
    "pctnew",
    "elitetorrent",
    "todotorrente",
    "pctmix",
    "pctreload",
    "descargas2020",
)

TECH_TOKENS_RE = re.compile(
    r"(?i)\b(?:"
    r"4k|2160p?|1080p?|720p?|576p?|480p?|uhd|hdr|hdr10|dv|dovi|"
    r"bluray|blu-ray|bdrip|bdremux|remux|web[- ]?dl|webrip|hdtv|dvdrip|"
    r"amzn|nf|netflix|hmax|dsnp|itunes|ac3|eac3|dts|dts-hd|truehd|"
    r"x26[45]|h26[45]|hevc|avc|aac|ddp?5?\.?1|castellano|spanish|"
    r"dual|lat|latino|sub[s]?|es-en|multi|proper|repack"
    r")\b"
)

YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
GENERIC_MANUAL_RE = re.compile(
    r"\b(?:book|books|ebook|ebooks|audiobook|course|collection|tutorial|"
    r"software|portable|windows|linux|ubuntu|shell|cli|manual|sample)\b",
    re.I,
)


@dataclass
class ParsedName:
    raw: str
    cleaned: str
    display_title: str
    title_candidates: list[str] = field(default_factory=list)
    year: int | None = None
    media_hint: str = "manual"
    confidence: str = "low"
    season: int | None = None
    episodes: list[int] = field(default_factory=list)
    absolute_episode: int | None = None
    season_pack: int | None = None
    guessit_input: str = ""
    category_conflict: str | None = None
    weak_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_release_name(raw_name: str, explicit_category: str = "movies") -> ParsedName:
    raw = str(raw_name or "").strip()
    explicit = str(explicit_category or "").strip().lower()
    cleaned = _preclean(raw)
    year = _extract_year(cleaned)
    tv = _parse_tv(cleaned)
    title_candidates = _title_candidates(cleaned, year, tv)
    display_title = title_candidates[0] if title_candidates else _title_from_cleaned(cleaned, year, tv)
    weak_reason = _weak_title_reason(cleaned, display_title)
    manual = bool(weak_reason)

    movie_strong = bool(year and not tv["strong"] and not manual)
    tv_strong = bool(tv["strong"] and not manual)
    media_hint = "manual"
    confidence = "low"
    if tv_strong:
        media_hint = "tv"
        confidence = "high"
    elif movie_strong:
        media_hint = "movies"
        confidence = "high"
    elif explicit in {"movies", "tv"} and display_title and not manual:
        media_hint = explicit
        confidence = "medium"

    category_conflict = None
    if explicit == "movies" and tv_strong:
        category_conflict = "movies_vs_tv"
    elif explicit == "tv" and movie_strong:
        category_conflict = "tv_vs_movies"

    return ParsedName(
        raw=raw,
        cleaned=cleaned,
        display_title=display_title,
        title_candidates=title_candidates or ([display_title] if display_title else []),
        year=year,
        media_hint=media_hint,
        confidence=confidence,
        season=tv["season"],
        episodes=tv["episodes"],
        absolute_episode=tv["absolute_episode"],
        season_pack=tv["season_pack"],
        guessit_input=_guessit_input(display_title, year, tv),
        category_conflict=category_conflict,
        weak_reason=weak_reason,
    )


def _preclean(value: str) -> str:
    text = Path(value).name.strip()
    suffix = Path(text).suffix.lower()
    if suffix in KNOWN_EXTENSIONS:
        text = text[: -len(suffix)]
    text = re.sub(r"__\d{8,}$", "", text)
    while True:
        new = re.sub(r"\s*\(\d{1,2}\)\s*$", "", text).strip()
        if new == text:
            break
        text = new
    text = text.replace("`", " ").replace("\u00b4", " ").replace("'", "'")
    text = re.sub(r"[-\u2013\u2014]+", "-", text)
    text = re.sub(r"(?i)\bwww\.[a-z0-9-]+\.(?:com|net|org|li|tv|bz)\s*[-_]*", " ", text)
    text = re.sub(r"(?i)\b[a-z0-9-]+\.(?:com|net|org|li|tv|bz)\b", " ", text)
    for word in SITE_WORDS:
        text = re.sub(rf"(?i)\b{re.escape(word)}\b", " ", text)
    text = re.sub(r"(?i)\b(S\d{1,2}\s*E\d{1,3})[_-](\d{1,3})\b", r"\1-\2", text)
    text = re.sub(r"(?i)\b(\d{1,2}x\d{1,3})[_-](\d{1,3})\b", r"\1-\2", text)
    text = re.sub(r"(?i)\b(cap(?:itulo)?\.?\s*\d{1,4})[_-](\d{1,4})\b", r"\1-\2", text)
    text = re.sub(r"(?i)([a-z])(\d+x\d+)", r"\1 \2", text)
    text = re.sub(r"(?i)\b(temporada|season|capitulo|episode|episodio|cap)\s*([0-9])", r"\1 \2", text)
    text = re.sub(r"(?i)\bT\s*([0-9]{1,2})\b", lambda m: f"T{int(m.group(1)):02d}", text)
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"[\[\]{}]+", " ", text)
    text = re.sub(r"\s*-\s*", " - ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -_.,")


def _extract_year(text: str) -> int | None:
    for match in YEAR_RE.finditer(text):
        year = int(match.group(1))
        if 1900 <= year <= 2099:
            return year
    return None


def _parse_tv(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "strong": False,
        "season": None,
        "episodes": [],
        "absolute_episode": None,
        "season_pack": None,
    }
    season = None
    explicit_season = re.search(r"(?i)\b(?:temporada|season)\s*0?(\d{1,2})\b", text)
    if explicit_season:
        season = int(explicit_season.group(1))
        result["strong"] = True
    sxe = re.search(r"(?i)\bS0?(\d{1,2})\s*E0?(\d{1,3})(?:\s*(?:-|_|E)\s*0?(\d{1,3}))?\b", text)
    if sxe:
        season = int(sxe.group(1))
        result["episodes"] = _episode_list(int(sxe.group(2)), _optional_int(sxe.group(3)))
        result["strong"] = True
    xpat = re.search(r"(?i)\b(\d{1,2})x0?(\d{1,3})(?:\s*(?:-|_)\s*0?(\d{1,3}))?\b", text)
    if xpat:
        season = int(xpat.group(1))
        result["episodes"] = _episode_list(int(xpat.group(2)), _optional_int(xpat.group(3)))
        result["strong"] = True
    cap = re.search(r"(?i)\bcap(?:itulo)?\.?\s*0?(\d{1,4})(?:\s*(?:-|_)\s*0?(\d{1,4}))?\b", text)
    if cap:
        first_raw = cap.group(1)
        if explicit_season:
            result["episodes"] = _episode_list(_episode_part(first_raw), _episode_part(cap.group(2)) if cap.group(2) else None)
        elif len(first_raw) >= 3:
            season = int(first_raw[:-2])
            result["episodes"] = _episode_list(int(first_raw[-2:]), _episode_part(cap.group(2)) if cap.group(2) else None)
        else:
            result["absolute_episode"] = int(first_raw)
        result["strong"] = True
    episode = re.search(r"(?i)\b(?:episode|episodio)\s*0?(\d{1,3})\b", text)
    if episode and not result["episodes"]:
        result["absolute_episode"] = int(episode.group(1))
        result["strong"] = True
    t_pack = re.search(r"(?i)(?:^|\s)T0?(\d{1,2})(?:\b|[- ]|$)", text)
    if t_pack and not result["episodes"]:
        season = int(t_pack.group(1))
        result["season_pack"] = season
        result["strong"] = True
    if season is not None:
        result["season"] = season
    return result


def _episode_list(first: int, second: int | None) -> list[int]:
    if second is None or second == first:
        return [first]
    start, end = sorted((first, second))
    return list(range(start, end + 1))


def _episode_part(value: str | None) -> int:
    digits = str(value or "0")
    return int(digits[-2:]) if len(digits) >= 3 else int(digits)


def _optional_int(value: str | None) -> int | None:
    return int(value) if value else None


def _title_candidates(cleaned: str, year: int | None, tv: dict[str, Any]) -> list[str]:
    title = _title_from_cleaned(cleaned, year, tv)
    candidates: list[str] = []
    if not title:
        return candidates
    outer, inner = _split_parenthesized_title(title)
    for value in (outer, inner, title):
        _append_unique(candidates, value)
    return candidates


def _split_parenthesized_title(title: str) -> tuple[str, str]:
    match = re.match(r"^(.*?)\s*\(([^()]+)\)\s*$", title)
    if not match:
        return title, ""
    outer = match.group(1).strip()
    inner = match.group(2).strip()
    if YEAR_RE.fullmatch(inner):
        return outer, ""
    return outer, inner


def _title_from_cleaned(cleaned: str, year: int | None, tv: dict[str, Any]) -> str:
    text = cleaned
    if year:
        text = re.sub(rf"\s*[\[(]\s*{year}\s*[\])]\s*", " ", text, count=1)
        text = re.sub(rf"(?<!\d){year}(?!\d)", " ", text, count=1)
    text = re.sub(r"\(\s*\)", " ", text)
    text = _remove_tv_tokens(text)
    text = re.sub(r"(?i)\b(?:4k)?web(?:rip|dl)\d{3,4}p?\b", " ", text)
    marker = TECH_TOKENS_RE.search(text)
    if marker:
        text = text[: marker.start()]
    text = re.sub(r"(?i)\b(?:cast|latino|lat|spanish|espanol|espa\u00f1ol)\b", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -_.,")


def _remove_tv_tokens(text: str) -> str:
    text = re.sub(r"(?i)\bS0?\d{1,2}\s*E0?\d{1,3}(?:\s*(?:-|_|E)\s*0?\d{1,3})?\b", " ", text)
    text = re.sub(r"(?i)\b\d{1,2}x0?\d{1,3}(?:\s*(?:-|_)\s*0?\d{1,3})?\b", " ", text)
    text = re.sub(r"(?i)\b(?:temporada|season)\s*0?\d{1,2}\b", " ", text)
    text = re.sub(r"(?i)(?:^|\s)T0?\d{1,2}(?:\b|[- ]|$)", " ", text)
    text = re.sub(r"(?i)\bcap(?:itulo)?\.?\s*0?\d{1,4}(?:\s*(?:-|_)\s*0?\d{1,4})?\b", " ", text)
    text = re.sub(r"(?i)\b(?:episode|episodio)\s*0?\d{1,3}\b", " ", text)
    text = re.sub(r"(?i)\b(?:completa|complete|extras)\b", " ", text)
    return text


def _guessit_input(title: str, year: int | None, tv: dict[str, Any]) -> str:
    parts = [title]
    if year:
        parts.append(str(year))
    season = tv.get("season")
    episodes = tv.get("episodes") or []
    if season and episodes:
        parts.append(f"S{int(season):02d}E{int(episodes[0]):02d}")
    elif season:
        parts.append(f"Season {int(season)}")
    elif tv.get("absolute_episode"):
        parts.append(f"Episode {int(tv['absolute_episode'])}")
    return " ".join(part for part in parts if part).strip()


def _weak_title_reason(cleaned: str, title: str) -> str:
    folded = _fold(f"{cleaned} {title}")
    if not title:
        return "no_usable_title"
    if GENERIC_MANUAL_RE.search(folded):
        return "manual_or_generic"
    if folded in {"my books", "wasabi", "doraemon", "bluey", "la reina del flow"}:
        return "generic_title"
    tokens = folded.split()
    if len(tokens) < 1:
        return "too_short"
    if len("".join(tokens)) < 3:
        return "too_short"
    return ""


def _append_unique(values: list[str], value: str) -> None:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" -_.,")
    if not text:
        return
    key = _fold(text)
    if key and key not in {_fold(item) for item in values}:
        values.append(text)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text.casefold()))
