from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Any, Sequence

from ..config import (
    TITLE_RESOLVER_CACHE_DB,
    TITLE_RESOLVER_HTTP_TIMEOUT_MS,
    TITLE_RESOLVER_LANGUAGE,
    TITLE_RESOLVER_NEGATIVE_TTL_SEC,
    TITLE_RESOLVER_POSITIVE_TTL_SEC,
    TITLE_RESOLVER_REGION,
    TITLE_RESOLVER_TOTAL_BUDGET_MS,
    title_resolver_token,
)
from .cache import TitleResolverCache
from .parser import ParsedName, parse_release_name
from .tmdb_client import TmdbClient, TmdbError, TmdbUnavailable

try:
    from guessit import guessit
except Exception:  # pragma: no cover - runtime dependency is installed in Docker.
    guessit = None


class TitleResolverError(RuntimeError):
    status_code = 500
    error_code = "title_resolver_error"


class TitleResolverTokenMissing(TitleResolverError):
    status_code = 503
    error_code = "tmdb_token_missing"


@dataclass
class ResolverCandidate:
    tmdb_id: int
    title: str
    original_title: str
    english_title: str
    year: int | None
    aliases: list[str] = field(default_factory=list)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_movie_title(
    title: str,
    evidence: Sequence[str] | None = None,
    media_hint: str = "movie",
    client: TmdbClient | None = None,
    cache: TitleResolverCache | None = None,
) -> dict[str, Any]:
    raw_title = str(title or "").strip()
    if not raw_title:
        return _not_sure("empty_title", None)
    if str(media_hint or "movie").strip().lower() not in {"movie", "movies", "pelicula", "peliculas"}:
        return _not_sure("only_movies_supported", None)

    parsed = parse_release_name(raw_title, "movies")
    if parsed.category_conflict or parsed.media_hint == "tv":
        return _not_sure("tv_detected", parsed)
    if parsed.weak_reason:
        return _not_sure(parsed.weak_reason, parsed)

    token = title_resolver_token()
    if not token and client is None:
        raise TitleResolverTokenMissing("TMDb sin token")

    evidence_values = _unique([raw_title, *(evidence or []), parsed.cleaned, parsed.display_title, parsed.guessit_input, *parsed.title_candidates])
    guessed = _best_guess(evidence_values, parsed)
    query = str(guessed.get("title") or parsed.display_title or "").strip()
    if not query:
        return _not_sure("no_usable_query", parsed)

    cache = cache or TitleResolverCache(TITLE_RESOLVER_CACHE_DB)
    cache_key = _cache_key(evidence_values, guessed)
    cached = cache.get(cache_key)
    if cached:
        return cached

    client = client or TmdbClient(
        token,
        TITLE_RESOLVER_LANGUAGE,
        TITLE_RESOLVER_REGION,
        TITLE_RESOLVER_HTTP_TIMEOUT_MS / 1000,
    )
    deadline = time.monotonic() + max(0.5, TITLE_RESOLVER_TOTAL_BUDGET_MS / 1000)
    try:
        candidates = _search_candidates(client, query, guessed, deadline)
    except TmdbUnavailable:
        raise
    except TmdbError as exc:
        raise TitleResolverError(str(exc)) from exc

    if not candidates:
        payload = _not_sure("no_tmdb_candidates", parsed)
        cache.set(cache_key, "not_sure", payload, TITLE_RESOLVER_NEGATIVE_TTL_SEC)
        return payload

    ranked = _rank_candidates(candidates, guessed, evidence_values)
    top = ranked[0]
    second_score = ranked[1].score if len(ranked) > 1 else 0.0
    margin = round(top.score - second_score, 2)
    if top.score < 75 or margin < 12:
        payload = _not_sure("ambiguous_margin", parsed, ranked[:5], top.score, margin)
        cache.set(cache_key, "not_sure", payload, TITLE_RESOLVER_NEGATIVE_TTL_SEC)
        return payload

    payload = _resolved(parsed, top, margin)
    cache.set(cache_key, "resolved", payload, TITLE_RESOLVER_POSITIVE_TTL_SEC)
    return payload


def _best_guess(evidence: Sequence[str], parsed: ParsedName) -> dict[str, Any]:
    guesses: list[tuple[int, dict[str, Any]]] = []
    for index, value in enumerate(evidence):
        item_parsed = parse_release_name(str(value), "movies")
        cleaned = item_parsed.guessit_input or item_parsed.cleaned or str(value)
        guessed: dict[str, Any] = {}
        if guessit:
            try:
                guessed = dict(guessit(cleaned, {"type": "movie"}))
            except Exception:
                guessed = {}
        title = str(guessed.get("title") or item_parsed.display_title or "").strip()
        if not title:
            continue
        guessed["title"] = title
        if item_parsed.year and not guessed.get("year"):
            guessed["year"] = item_parsed.year
        guessed["_title_candidates"] = item_parsed.title_candidates or [title]
        guessed["_display_title"] = item_parsed.display_title
        guessed["_guessit_input"] = cleaned
        quality = 100 - index
        if guessed.get("year"):
            quality += 20
        if item_parsed.confidence == "high":
            quality += 10
        guesses.append((quality, guessed))
    if guesses:
        return max(guesses, key=lambda item: item[0])[1]
    return {
        "title": parsed.display_title,
        "year": parsed.year,
        "_title_candidates": parsed.title_candidates,
        "_display_title": parsed.display_title,
        "_guessit_input": parsed.guessit_input,
    }


def _search_candidates(
    client: TmdbClient,
    query: str,
    guessed: dict[str, Any],
    deadline: float,
) -> list[ResolverCandidate]:
    year = _as_int(guessed.get("year"))
    queries = _unique([query, *[str(v) for v in guessed.get("_title_candidates") or []], str(guessed.get("_display_title") or "")])
    searches: list[tuple[str, int | None, str]] = []
    for search_query in queries:
        searches.append((search_query, year, client.language))
        searches.append((search_query, None, client.language))
        if client.language.lower() != "en-us":
            searches.append((search_query, year, "en-US"))
            searches.append((search_query, None, "en-US"))
    searches = searches[:8]

    raw: dict[int, dict[str, Any]] = {}
    for search_query, search_year, language in searches:
        if time.monotonic() >= deadline:
            break
        payload = client.search_movie(search_query, search_year, language)
        for item in list(payload.get("results") or [])[:10]:
            candidate_id = _as_int(item.get("id"))
            if candidate_id:
                raw.setdefault(candidate_id, dict(item))
        if raw:
            quick = _rank_candidates([_candidate_from_payload(item) for item in raw.values()], guessed, [])
            margin = quick[0].score - (quick[1].score if len(quick) > 1 else 0)
            if quick[0].score >= 75 and margin >= 12:
                break

    initial = _rank_candidates([_candidate_from_payload(item) for item in raw.values()], guessed, [])
    enriched: list[ResolverCandidate] = []
    for candidate in initial[:3]:
        if time.monotonic() >= deadline:
            break
        try:
            enriched.append(_candidate_from_payload(client.movie_details(candidate.tmdb_id)))
        except TmdbUnavailable:
            if not enriched:
                enriched.append(candidate)
            break
    return enriched or initial


def _candidate_from_payload(payload: dict[str, Any]) -> ResolverCandidate:
    english_title = _english_title_from_payload(payload)
    aliases = [str(payload.get("title") or ""), str(payload.get("original_title") or ""), english_title]
    alternatives = payload.get("alternative_titles") or {}
    aliases.extend(str(item.get("title") or "") for item in alternatives.get("titles") or [])
    translations = (payload.get("translations") or {}).get("translations") or []
    for item in translations:
        data = item.get("data") or {}
        if data.get("title"):
            aliases.append(str(data.get("title")))
    return ResolverCandidate(
        tmdb_id=int(payload["id"]),
        title=str(payload.get("title") or payload.get("original_title") or ""),
        original_title=str(payload.get("original_title") or payload.get("title") or ""),
        english_title=english_title,
        year=_year(payload.get("release_date")),
        aliases=_unique(value for value in aliases if value),
    )


def _rank_candidates(
    candidates: Sequence[ResolverCandidate],
    guessed: dict[str, Any],
    evidence: Sequence[str],
) -> list[ResolverCandidate]:
    for candidate in candidates:
        candidate.score, candidate.reasons = _score_candidate(candidate, guessed, evidence)
    return sorted(candidates, key=lambda item: item.score, reverse=True)


def _score_candidate(
    candidate: ResolverCandidate,
    guessed: dict[str, Any],
    evidence: Sequence[str],
) -> tuple[float, list[str]]:
    query = str(guessed.get("title") or "")
    query_norm = _normalize_title(query)
    aliases = [_normalize_title(value) for value in candidate.aliases if value]
    ratios = [SequenceMatcher(None, query_norm, alias).ratio() for alias in aliases]
    ratio = max(ratios or [0.0])
    exact = query_norm in aliases
    tokens = set(query_norm.split())
    token_overlap = max(
        (
            len(tokens & set(alias.split())) / max(1, len(tokens | set(alias.split())))
            for alias in aliases
        ),
        default=0.0,
    )
    score = (35 if exact else 0) + ratio * 20 + token_overlap * 5
    reasons = [f"titulo ratio={ratio:.2f}", f"tokens={token_overlap:.2f}"]
    if exact:
        reasons.append("titulo exacto")

    title_candidates = [
        _normalize_title(str(value))
        for value in guessed.get("_title_candidates") or []
        if str(value or "").strip()
    ]
    candidate_ratios = [
        SequenceMatcher(None, candidate_title, alias).ratio()
        for candidate_title in title_candidates
        for alias in aliases
    ]
    best_candidate_ratio = max(candidate_ratios or [0.0])
    if any(candidate_title in aliases for candidate_title in title_candidates):
        score += 20
        reasons.append("alias del parser exacto")
    elif best_candidate_ratio >= 0.86:
        score += 12
        reasons.append("alias del parser cercano")

    guessed_year = _as_int(guessed.get("year"))
    if guessed_year and candidate.year:
        difference = abs(guessed_year - candidate.year)
        if difference == 0:
            score += 20
            reasons.append("ano exacto")
        elif difference == 1:
            score += 8
            reasons.append("ano +/-1")
        else:
            score -= 25
            reasons.append("ano contradictorio")

    score += 10
    reasons.append("categoria correcta")
    if evidence and any(_normalize_title(parse_release_name(value, "movies").display_title) in aliases for value in evidence):
        score += 15
        reasons.append("evidencia de origen")
    return round(score, 2), reasons


def _resolved(parsed: ParsedName, candidate: ResolverCandidate, margin: float) -> dict[str, Any]:
    title_es = candidate.title or candidate.original_title
    title_en = candidate.english_title or candidate.original_title or candidate.title
    year = candidate.year or parsed.year
    return {
        "ok": True,
        "status": "resolved",
        "safe": True,
        "parser": parsed.to_dict(),
        "match": {
            "tmdb_id": candidate.tmdb_id,
            "score": candidate.score,
            "margin": margin,
            "year": year,
            "title_es": title_es,
            "title_english": title_en,
            "title_original": candidate.original_title or candidate.title,
            "aliases": candidate.aliases[:20],
            "reasons": candidate.reasons,
        },
        "copy": {
            "es": title_es,
            "es_with_year": _with_year(title_es, year),
            "english": title_en,
            "english_with_year": _with_year(title_en, year),
            "en": title_en,
            "en_with_year": _with_year(title_en, year),
            "original": candidate.original_title or candidate.title,
            "original_with_year": _with_year(candidate.original_title or candidate.title, year),
        },
        "cache": {"hit": False},
    }


def _not_sure(
    reason_code: str,
    parsed: ParsedName | None,
    candidates: Sequence[ResolverCandidate] | None = None,
    score: float | None = None,
    margin: float | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "status": "not_sure",
        "safe": False,
        "reason_code": reason_code,
        "parser": parsed.to_dict() if parsed else {},
        "cache": {"hit": False},
    }
    if candidates:
        payload["candidates"] = [candidate.to_dict() for candidate in candidates]
    if score is not None:
        payload["score"] = score
    if margin is not None:
        payload["margin"] = margin
    return payload


def _with_year(title: str, year: int | None) -> str:
    clean = str(title or "").strip()
    return f"{clean} ({year})" if clean and year else clean


def _cache_key(evidence: Sequence[str], guessed: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "media_type": "movie",
            "evidence": list(evidence),
            "guess": _json_safe(guessed),
            "language": TITLE_RESOLVER_LANGUAGE,
            "region": TITLE_RESOLVER_REGION,
            "output": "english-v1",
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_json_safe(v) for v in value]
        return str(value)


def _year(value: Any) -> int | None:
    text = str(value or "")
    match = re.match(r"((?:19|20)\d{2})", text)
    return int(match.group(1)) if match else None


def _english_title_from_payload(payload: dict[str, Any]) -> str:
    translations = (payload.get("translations") or {}).get("translations") or []
    english: list[tuple[int, str]] = []
    for item in translations:
        if str(item.get("iso_639_1") or "").lower() != "en":
            continue
        data = item.get("data") or {}
        title = str(data.get("title") or "").strip()
        if not title:
            continue
        country = str(item.get("iso_3166_1") or "").upper()
        priority = 3 if country == "US" else 2 if country == "GB" else 1
        english.append((priority, title))
    if english:
        return max(english, key=lambda value: value[0])[1]
    if str(payload.get("original_language") or "").lower() == "en":
        return str(payload.get("original_title") or payload.get("title") or "").strip()
    return ""


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def _unique(values: Sequence[str] | Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = _normalize_title(text)
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text.casefold()))
