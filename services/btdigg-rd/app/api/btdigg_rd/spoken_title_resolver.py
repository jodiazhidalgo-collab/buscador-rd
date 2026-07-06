from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date
from difflib import SequenceMatcher
from typing import Any, Iterable, Sequence

from .config import (
    TITLE_RESOLVER_HTTP_TIMEOUT_MS,
    TITLE_RESOLVER_LANGUAGE,
    TITLE_RESOLVER_REGION,
    TITLE_RESOLVER_TOTAL_BUDGET_MS,
    title_resolver_token,
)
from .title_resolver.service import TitleResolverError, TitleResolverTokenMissing
from .title_resolver.tmdb_client import TmdbClient, TmdbError, TmdbUnavailable

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - Docker installs it, local fallback keeps tests light.
    fuzz = None


CURRENT_YEAR = date.today().year

_SPANISH_0_TO_99 = {
    0: ["cero"],
    1: ["un", "uno", "una"],
    2: ["dos"],
    3: ["tres"],
    4: ["cuatro"],
    5: ["cinco"],
    6: ["seis"],
    7: ["siete"],
    8: ["ocho"],
    9: ["nueve"],
    10: ["diez"],
    11: ["once"],
    12: ["doce"],
    13: ["trece"],
    14: ["catorce"],
    15: ["quince"],
    16: ["dieciseis"],
    17: ["diecisiete"],
    18: ["dieciocho"],
    19: ["diecinueve"],
    20: ["veinte"],
    21: ["veintiuno", "veinte y uno"],
    22: ["veintidos", "veinte y dos"],
    23: ["veintitres", "veinte y tres"],
    24: ["veinticuatro", "veinte y cuatro"],
    25: ["veinticinco", "veinte y cinco"],
    26: ["veintiseis", "veinte y seis"],
    27: ["veintisiete", "veinte y siete"],
    28: ["veintiocho", "veinte y ocho"],
    29: ["veintinueve", "veinte y nueve"],
}
_SPANISH_TENS = {
    30: "treinta",
    40: "cuarenta",
    50: "cincuenta",
    60: "sesenta",
    70: "setenta",
    80: "ochenta",
    90: "noventa",
}
_ENGLISH_0_TO_99 = {
    0: ["zero"],
    1: ["one"],
    2: ["two"],
    3: ["three"],
    4: ["four"],
    5: ["five"],
    6: ["six"],
    7: ["seven"],
    8: ["eight"],
    9: ["nine"],
    10: ["ten"],
    11: ["eleven"],
    12: ["twelve"],
    13: ["thirteen"],
    14: ["fourteen"],
    15: ["fifteen"],
    16: ["sixteen"],
    17: ["seventeen"],
    18: ["eighteen"],
    19: ["nineteen"],
    20: ["twenty"],
}
_ENGLISH_TENS = {
    20: "twenty",
    30: "thirty",
    40: "forty",
    50: "fifty",
    60: "sixty",
    70: "seventy",
    80: "eighty",
    90: "ninety",
}
_NUMBER_WORD_REPLACEMENTS = None
_JOINED_TITLE_TOKENS = {
    "bladerunner": "blade runner",
    "fastfurious": "fast furious",
    "harrypotter": "harry potter",
    "johnwick": "john wick",
    "jurornumber": "juror number",
    "mortalcombat": "mortal kombat",
    "spiderman": "spider man",
    "starwars": "star wars",
    "thebatman": "the batman",
    "topgun": "top gun",
    "wonderwoman": "wonder woman",
}


@dataclass
class SpokenVariant:
    query: str
    reason: str
    year: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SpokenCandidate:
    tmdb_id: int
    title: str
    original_title: str
    english_title: str
    year: int | None
    aliases: list[str] = field(default_factory=list)
    searched_queries: list[str] = field(default_factory=list)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_spoken_movie_title(
    transcript: str,
    locale: str = "es-ES",
    region: str | None = "ES",
    client: TmdbClient | None = None,
) -> dict[str, Any]:
    raw = str(transcript or "").strip()
    normalized = normalize_spoken_title(raw)
    if not normalized:
        return _payload("no_match", raw, normalized, "empty_transcript")

    variants = generate_spoken_variants(normalized)
    if not variants:
        return _payload("no_match", raw, normalized, "no_variants")

    token = title_resolver_token()
    if not token and client is None:
        raise TitleResolverTokenMissing("TMDb sin token")
    client = client or TmdbClient(
        token,
        locale or TITLE_RESOLVER_LANGUAGE,
        region or TITLE_RESOLVER_REGION,
        TITLE_RESOLVER_HTTP_TIMEOUT_MS / 1000,
    )

    deadline = time.monotonic() + max(0.5, TITLE_RESOLVER_TOTAL_BUDGET_MS / 1000)
    try:
        candidates = _collect_candidates(client, variants, deadline)
    except TmdbUnavailable:
        raise
    except TmdbError as exc:
        raise TitleResolverError(str(exc)) from exc

    if not candidates:
        return _payload("no_match", raw, normalized, "no_tmdb_candidates", variants=variants)

    ranked = rank_spoken_candidates(normalized, variants, list(candidates.values()))
    top = ranked[0]
    second_score = ranked[1].score if len(ranked) > 1 else 0.0
    margin = round(top.score - second_score, 2)
    decision = _decision(top, ranked, margin)
    reason = "high_confidence" if decision == "auto_accept" else "needs_confirmation" if decision == "needs_confirmation" else "low_confidence"
    return _payload(
        decision,
        raw,
        normalized,
        reason,
        variants=variants,
        candidates=ranked[:5],
        best=top,
        score=top.score,
        margin=margin,
    )


def normalize_spoken_title(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\u00ba", "o").replace("\u00aa", "a")
    text = text.strip(" \t\r\n\"'")
    return text


def generate_spoken_variants(value: str) -> list[SpokenVariant]:
    base = normalize_spoken_title(value)
    if not base:
        return []
    variants: list[SpokenVariant] = []
    _append_variant(variants, base, "original")

    folded = _fold_keep_numbers(base)
    stripped_year = _strip_release_year_query(folded)
    release_year = _extract_release_year_hint(folded)
    if stripped_year and stripped_year != folded:
        _append_variant(variants, stripped_year, "without_release_year", release_year)

    for query, reason in _phonetic_queries(folded):
        _append_variant(variants, query, reason, release_year)
        stripped = _strip_release_year_query(query)
        if stripped and stripped != query:
            _append_variant(variants, stripped, f"{reason}_without_year", release_year)

    for query in _word_number_queries(folded):
        query_year = release_year or _extract_release_year_hint(query)
        _append_variant(variants, query, "spoken_number", query_year)
        stripped = _strip_release_year_query(query)
        if stripped and stripped != query:
            _append_variant(variants, stripped, "spoken_number_without_year", query_year)
        for numeric_query in _numeric_queries(query):
            _append_variant(variants, numeric_query, "spoken_number_normalized", query_year)

    for query in _numeric_queries(folded):
        _append_variant(variants, query, "numeric_normalized", release_year)

    return variants[:14]


def rank_spoken_candidates(
    normalized_input: str,
    variants: Sequence[SpokenVariant],
    candidates: Sequence[SpokenCandidate],
) -> list[SpokenCandidate]:
    input_values = _unique([normalized_input, *[variant.query for variant in variants]])
    release_years = {variant.year for variant in variants if variant.year}
    input_numbers = _number_tokens(input_values)
    for candidate in candidates:
        candidate.score, candidate.reasons = _score_candidate(candidate, input_values, input_numbers, release_years)
    return sorted(candidates, key=lambda item: item.score, reverse=True)


def _collect_candidates(
    client: TmdbClient,
    variants: Sequence[SpokenVariant],
    deadline: float,
) -> dict[int, SpokenCandidate]:
    by_id: dict[int, SpokenCandidate] = {}
    for variant in variants:
        if time.monotonic() >= deadline:
            break
        searches: list[tuple[str, int | None, str]] = [
            (variant.query, None, client.language),
            (variant.query, variant.year, client.language),
        ]
        if client.language.lower() != "en-us":
            searches.append((variant.query, None, "en-US"))
            searches.append((variant.query, variant.year, "en-US"))
        for query, year, language in searches:
            if time.monotonic() >= deadline:
                break
            if not query:
                continue
            payload = client.search_movie(query, year, language)
            for item in list(payload.get("results") or [])[:8]:
                tmdb_id = _as_int(item.get("id"))
                if not tmdb_id:
                    continue
                candidate = by_id.get(tmdb_id) or _candidate_from_payload(item)
                if query not in candidate.searched_queries:
                    candidate.searched_queries.append(query)
                by_id[tmdb_id] = candidate
    initial = sorted(by_id.values(), key=lambda item: len(item.searched_queries), reverse=True)[:5]
    for candidate in initial:
        if time.monotonic() >= deadline:
            break
        try:
            enriched = _candidate_from_payload(client.movie_details(candidate.tmdb_id))
        except TmdbUnavailable:
            break
        except Exception:
            continue
        enriched.searched_queries = candidate.searched_queries
        by_id[candidate.tmdb_id] = enriched
    return by_id


def _candidate_from_payload(payload: dict[str, Any]) -> SpokenCandidate:
    english_title = _english_title_from_payload(payload)
    aliases = [str(payload.get("title") or ""), str(payload.get("original_title") or ""), english_title]
    alternatives = payload.get("alternative_titles") or {}
    aliases.extend(str(item.get("title") or "") for item in alternatives.get("titles") or [])
    translations = (payload.get("translations") or {}).get("translations") or []
    for item in translations:
        data = item.get("data") or {}
        if data.get("title"):
            aliases.append(str(data.get("title")))
    return SpokenCandidate(
        tmdb_id=int(payload["id"]),
        title=str(payload.get("title") or payload.get("original_title") or ""),
        original_title=str(payload.get("original_title") or payload.get("title") or ""),
        english_title=english_title,
        year=_year(payload.get("release_date")),
        aliases=_unique(value for value in aliases if value),
    )


def _score_candidate(
    candidate: SpokenCandidate,
    input_values: Sequence[str],
    input_numbers: set[str],
    release_years: set[int],
) -> tuple[float, list[str]]:
    aliases = _unique([candidate.title, candidate.original_title, candidate.english_title, *candidate.aliases])
    text_score = max((_text_similarity(value, alias) for value in input_values for alias in aliases), default=0.0)
    folded_aliases = [_fold_keep_numbers(alias) for alias in aliases]
    exact_alias = any(_fold_keep_numbers(value) in folded_aliases for value in input_values)
    candidate_numbers = _number_tokens(aliases)
    query_consensus = min(10.0, max(0, len(candidate.searched_queries) - 1) * 3.0)
    year_bonus = 0.0
    if release_years and candidate.year in release_years:
        year_bonus = 10.0
    number_bonus = 0.0
    if input_numbers and input_numbers & candidate_numbers:
        number_bonus = 12.0
    elif input_numbers and not candidate_numbers:
        number_bonus = -12.0

    score = text_score * 0.78 + query_consensus + year_bonus + number_bonus
    if exact_alias:
        score += 12.0
    score = max(0.0, min(100.0, score))
    reasons = [
        f"text={text_score:.1f}",
        f"queries={len(candidate.searched_queries)}",
    ]
    if exact_alias:
        reasons.append("alias exacto")
    if year_bonus:
        reasons.append("ano compatible")
    if number_bonus > 0:
        reasons.append("numero compatible")
    if number_bonus < 0:
        reasons.append("numero no encontrado en candidato")
    return round(score, 2), reasons


def _decision(top: SpokenCandidate, ranked: Sequence[SpokenCandidate], margin: float) -> str:
    if len(ranked) > 1 and margin < 6:
        return "needs_confirmation"
    if top.score >= 88 and (margin >= 6 or len(top.searched_queries) >= 2 or "alias exacto" in top.reasons):
        return "auto_accept"
    if top.score >= 45:
        return "needs_confirmation"
    return "no_match"


def _payload(
    decision: str,
    raw: str,
    normalized: str,
    reason: str,
    variants: Sequence[SpokenVariant] | None = None,
    candidates: Sequence[SpokenCandidate] | None = None,
    best: SpokenCandidate | None = None,
    score: float | None = None,
    margin: float | None = None,
) -> dict[str, Any]:
    status = "resolved" if decision == "auto_accept" else "choices" if decision == "needs_confirmation" else "not_sure"
    payload: dict[str, Any] = {
        "ok": True,
        "status": status,
        "decision": decision,
        "safe": decision == "auto_accept",
        "reason_code": reason,
        "normalized_input": normalized,
        "variants": [variant.to_dict() for variant in variants or []],
        "candidates": [candidate.to_dict() for candidate in candidates or []],
    }
    if score is not None:
        payload["score"] = score
    if margin is not None:
        payload["margin"] = margin
    if best:
        payload["best_candidate"] = best.to_dict()
        payload["match"] = {
            "tmdb_id": best.tmdb_id,
            "score": best.score,
            "margin": margin,
            "year": best.year,
            "title_es": best.title or best.original_title,
            "title_english": best.english_title or best.original_title or best.title,
            "title_original": best.original_title or best.title,
            "aliases": best.aliases[:20],
            "reasons": best.reasons,
        }
        payload["copy"] = {
            "es": best.title or best.original_title,
            "es_with_year": _with_year(best.title or best.original_title, best.year),
            "english": best.english_title or best.original_title or best.title,
            "english_with_year": _with_year(best.english_title or best.original_title or best.title, best.year),
            "en": best.english_title or best.original_title or best.title,
            "en_with_year": _with_year(best.english_title or best.original_title or best.title, best.year),
            "original": best.original_title or best.title,
            "original_with_year": _with_year(best.original_title or best.title, best.year),
        }
    return payload


def _phonetic_queries(value: str) -> list[tuple[str, str]]:
    tokens = value.split()
    out: list[tuple[str, str]] = []
    if not tokens:
        return out
    if tokens[0] in {"te", "de", "di", "ti"} and len(tokens) > 1:
        out.append((" ".join(["the", *tokens[1:]]), "spanish_the"))
    if tokens[0].startswith("tee") and len(tokens[0]) > 4:
        out.append((" ".join(["the", tokens[0][3:], *tokens[1:]]), "attached_spanish_the"))
    if len(tokens) >= 2 and tokens[0] in {"tung", "tan", "dan", "ton"} and tokens[1] in {"der", "de"}:
        rest = tokens[2:]
        out.append((" ".join(["thunder", *rest]), "spanish_thunder"))
        if rest:
            out.append((" ".join(["thunder" + rest[0], *rest[1:]]), "joined_spanish_thunder"))
            out.append((" ".join(["thunder" + rest[0] + "s", *rest[1:]]), "plural_spanish_thunder"))
    converted_tokens: list[list[str]] = []
    for token in tokens:
        options = [token]
        if token.startswith("v") and len(token) > 3:
            options.append("b" + token[1:])
        if token.endswith("runer"):
            options.append(token[:-5] + "runner")
        if token in _JOINED_TITLE_TOKENS:
            options.append(_JOINED_TITLE_TOKENS[token])
        if token == "togeter":
            options.append("together")
        converted_tokens.append(_unique(options))
    for built in _limited_token_combinations(converted_tokens, limit=6):
        query = " ".join(built)
        if query != value:
            out.append((query, "phonetic_tokens"))
    return out


def _numeric_queries(value: str) -> list[str]:
    variants = {value}
    variants.add(re.sub(r"\bnum(?:ero)?\s+(\d+)\b", r"#\1", value))
    variants.add(re.sub(r"\bn\s+(\d+)\b", r"#\1", value))
    roman_to_number = {"ii": "2", "iii": "3", "iv": "4"}
    number_to_roman = {number: roman for roman, number in roman_to_number.items()}
    variants.add(_replace_token_values(value, roman_to_number))
    variants.add(_replace_token_values(value, number_to_roman))
    return [item for item in variants if item and item != value]


def _word_number_queries(value: str) -> list[str]:
    converted = _replace_number_words(value)
    return [converted] if converted and converted != value else []


def _replace_number_words(value: str) -> str:
    converted = f" {value} "
    for phrase, number in _number_word_replacements():
        converted = re.sub(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", f" {number} ", converted)
    return re.sub(r"\s+", " ", converted).strip()


def _number_word_replacements() -> list[tuple[str, str]]:
    global _NUMBER_WORD_REPLACEMENTS
    if _NUMBER_WORD_REPLACEMENTS is not None:
        return _NUMBER_WORD_REPLACEMENTS

    replacements: dict[str, str] = {}
    for number, phrases in _number_phrases_0_to_99("es").items():
        for phrase in phrases:
            replacements[phrase] = str(number)
    for number, phrases in _number_phrases_0_to_99("en").items():
        for phrase in phrases:
            replacements[phrase] = str(number)

    spanish_under_100 = _number_phrases_0_to_99("es")
    english_under_100 = _number_phrases_0_to_99("en")
    for number in range(1, 100):
        for phrase in spanish_under_100[number]:
            replacements[f"mil novecientos {phrase}"] = str(1900 + number)
            replacements[f"diecinueve {phrase}"] = str(1900 + number)
            replacements[f"dos mil {phrase}"] = str(2000 + number)
            if number >= 10:
                replacements[f"veinte {phrase}"] = str(2000 + number)
        for phrase in english_under_100[number]:
            replacements[f"nineteen {phrase}"] = str(1900 + number)
            replacements[f"two thousand {phrase}"] = str(2000 + number)
            if number >= 10:
                replacements[f"twenty {phrase}"] = str(2000 + number)
    replacements["mil novecientos"] = "1900"
    replacements["dos mil"] = "2000"
    replacements["two thousand"] = "2000"

    _NUMBER_WORD_REPLACEMENTS = sorted(replacements.items(), key=lambda item: len(item[0].split()), reverse=True)
    return _NUMBER_WORD_REPLACEMENTS


def _number_phrases_0_to_99(language: str) -> dict[int, list[str]]:
    if language == "es":
        phrases = {number: list(values) for number, values in _SPANISH_0_TO_99.items()}
        for ten, word in _SPANISH_TENS.items():
            phrases[ten] = [word]
            for unit in range(1, 10):
                phrases[ten + unit] = [f"{word} y {_SPANISH_0_TO_99[unit][0]}"]
        return phrases

    phrases = {number: list(values) for number, values in _ENGLISH_0_TO_99.items()}
    for ten, word in _ENGLISH_TENS.items():
        phrases[ten] = [word]
        for unit in range(1, 10):
            phrases[ten + unit] = [f"{word} {_ENGLISH_0_TO_99[unit][0]}"]
    return phrases


def _replace_token_values(value: str, replacements: dict[str, str]) -> str:
    if not replacements:
        return value
    pattern = re.compile(r"\b(" + "|".join(re.escape(key) for key in replacements) + r")\b")
    return pattern.sub(lambda match: replacements[match.group(1)], value)


def _limited_token_combinations(values: Sequence[Sequence[str]], limit: int) -> list[list[str]]:
    combos: list[list[str]] = [[]]
    for options in values:
        next_combos: list[list[str]] = []
        for prefix in combos:
            for option in options:
                next_combos.append([*prefix, option])
                if len(next_combos) >= limit:
                    break
            if len(next_combos) >= limit:
                break
        combos = next_combos
    return combos


def _append_variant(values: list[SpokenVariant], query: str, reason: str, year: int | None = None) -> None:
    clean = _display_query(query)
    if not clean:
        return
    key = _fold_keep_numbers(clean)
    if key and key not in {_fold_keep_numbers(item.query) for item in values}:
        values.append(SpokenVariant(query=clean, reason=reason, year=year))


def _strip_release_year_query(value: str) -> str:
    year = _extract_release_year_hint(value)
    if not year:
        return value
    return re.sub(rf"\b{year}\b", " ", value, count=1).strip()


def _extract_release_year_hint(value: str) -> int | None:
    for match in re.finditer(r"\b((?:19|20)\d{2})\b", value):
        year = int(match.group(1))
        if 1900 <= year <= CURRENT_YEAR + 2:
            return year
    return None


def _text_similarity(left: str, right: str) -> float:
    a = _fold_keep_numbers(left)
    b = _fold_keep_numbers(right)
    if not a or not b:
        return 0.0
    if fuzz:
        return max(
            float(fuzz.ratio(a, b)),
            float(fuzz.partial_ratio(a, b)),
            float(fuzz.token_sort_ratio(a, b)),
            float(fuzz.token_set_ratio(a, b)),
        )
    return SequenceMatcher(None, a, b).ratio() * 100.0


def _number_tokens(values: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for value in values:
        out.update(re.findall(r"\b\d+\b", _fold_keep_numbers(value)))
    return out


def _display_query(value: str) -> str:
    folded = _fold_keep_numbers(value)
    return re.sub(r"\s+", " ", folded).strip()


def _fold_keep_numbers(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = ascii_text.casefold().replace("º", "o")
    ascii_text = ascii_text.replace("#", " # ")
    return " ".join(re.findall(r"[a-z0-9#]+", ascii_text))


def _unique(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = _fold_keep_numbers(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


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


def _year(value: Any) -> int | None:
    match = re.match(r"((?:19|20)\d{2})", str(value or ""))
    return int(match.group(1)) if match else None


def _with_year(title: str, year: int | None) -> str:
    clean = str(title or "").strip()
    return f"{clean} ({year})" if clean and year else clean


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None
