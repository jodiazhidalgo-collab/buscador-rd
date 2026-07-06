from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from api.btdigg_rd.spoken_title_resolver import (  # noqa: E402
    generate_spoken_variants,
    resolve_spoken_movie_title,
)


def movie_payload(tmdb_id, title, original_title, year, english_title=None, original_language="en"):
    translations = []
    if english_title:
        translations.append({"iso_639_1": "en", "iso_3166_1": "US", "data": {"title": english_title}})
    return {
        "id": tmdb_id,
        "title": title,
        "original_title": original_title,
        "original_language": original_language,
        "release_date": f"{year}-01-01",
        "alternative_titles": {"titles": []},
        "translations": {"translations": translations},
    }


class FakeTmdbClient:
    language = "es-ES"
    region = "ES"

    def __init__(self, movies):
        self.movies = {item["id"]: item for item in movies}
        self.calls = []

    def search_movie(self, query, year=None, language=None):
        self.calls.append(("search", query, year, language))
        folded = query.lower()
        results = []
        for item in self.movies.values():
            aliases = [item.get("title") or "", item.get("original_title") or ""]
            aliases.extend(alt.get("title") or "" for alt in (item.get("alternative_titles") or {}).get("titles") or [])
            if any((alias or "").lower() in folded or folded in (alias or "").lower() for alias in aliases):
                if year and not str(item.get("release_date") or "").startswith(str(year)):
                    continue
                results.append(item)
        return {"results": results}

    def movie_details(self, tmdb_id):
        self.calls.append(("details", tmdb_id))
        return self.movies[int(tmdb_id)]


def test_generates_general_spoken_variants():
    surfer = [item.query for item in generate_spoken_variants("Teesurfer 2025")]
    runner = [item.query for item in generate_spoken_variants("Vlade Runer")]
    thunder = [item.query for item in generate_spoken_variants("Tung der Bolt")]

    assert "the surfer 2025" in surfer
    assert not any("ii025" in item for item in surfer)
    assert "blade runner" in runner
    assert "blade runner 2049" in [item.query for item in generate_spoken_variants("Bladerunner 2049")]
    assert "john wick" in [item.query for item in generate_spoken_variants("John Will")]
    assert "thunderbolts" in thunder
    assert "mortal kombat ii" in [item.query for item in generate_spoken_variants("Mortal Kombat 2")]
    assert "mortal kombat 2" in [item.query for item in generate_spoken_variants("Mortal Kombat II")]
    assert "jurado numero 2" in [item.query for item in generate_spoken_variants("Jurado numero dos")]
    assert "john wick 4" in [item.query for item in generate_spoken_variants("John Wick cuatro")]
    assert "blade runner 2049" in [
        item.query for item in generate_spoken_variants("Blade Runner dos mil cuarenta y nueve")
    ]
    surfer_words = generate_spoken_variants("The Surfer twenty twenty five")
    assert "the surfer 2025" in [item.query for item in surfer_words]
    assert any(item.query == "the surfer" and item.year == 2025 for item in surfer_words)


def test_resolves_spanish_pronounced_english_title_with_year():
    surfer = movie_payload(1, "The Surfer", "The Surfer", 2025)
    client = FakeTmdbClient([surfer])

    result = resolve_spoken_movie_title("Teesurfer 2025", client=client)

    assert result["decision"] == "auto_accept"
    assert result["copy"]["es_with_year"] == "The Surfer (2025)"
    assert any(call[1] == "the surfer 2025" for call in client.calls if call[0] == "search")


def test_resolves_number_that_is_part_of_movie_title_not_release_year():
    blade = movie_payload(2, "Blade Runner 2049", "Blade Runner 2049", 2017)
    client = FakeTmdbClient([blade])

    result = resolve_spoken_movie_title("Vlade Runner 2049", client=client)
    joined_result = resolve_spoken_movie_title("Bladerunner 2049", client=client)

    assert result["decision"] == "auto_accept"
    assert result["copy"]["es_with_year"] == "Blade Runner 2049 (2017)"
    assert joined_result["decision"] == "auto_accept"
    assert joined_result["copy"]["es_with_year"] == "Blade Runner 2049 (2017)"


def test_resolves_short_english_tail_transcription_error():
    wick = movie_payload(10, "John Wick", "John Wick", 2014)
    noisy = movie_payload(11, "What Will You Do Now, John?", "What Will You Do Now, John?", 2019)
    client = FakeTmdbClient([noisy, wick])

    result = resolve_spoken_movie_title("John Will", client=client)

    assert any(call[1] == "john wick" for call in client.calls if call[0] == "search")
    assert result["decision"] == "auto_accept"
    assert result["copy"]["es_with_year"] == "John Wick (2014)"


def test_resolves_spoken_number_words():
    juror = movie_payload(6, "Jurado Nº 2", "Juror #2", 2024)
    juror["alternative_titles"]["titles"].append({"title": "Jurado numero 2"})
    blade = movie_payload(7, "Blade Runner 2049", "Blade Runner 2049", 2017)
    wick = movie_payload(8, "John Wick 4", "John Wick: Chapter 4", 2023)
    surfer = movie_payload(9, "The Surfer", "The Surfer", 2025)
    client = FakeTmdbClient([juror, blade, wick, surfer])

    juror_result = resolve_spoken_movie_title("Jurado numero dos", client=client)
    blade_result = resolve_spoken_movie_title("Blade Runner dos mil cuarenta y nueve", client=client)
    wick_result = resolve_spoken_movie_title("John Wick cuatro", client=client)
    surfer_result = resolve_spoken_movie_title("The Surfer twenty twenty five", client=client)

    assert juror_result["decision"] == "auto_accept"
    assert juror_result["copy"]["es_with_year"] == "Jurado Nº 2 (2024)"
    assert blade_result["decision"] == "auto_accept"
    assert blade_result["copy"]["es_with_year"] == "Blade Runner 2049 (2017)"
    assert wick_result["decision"] == "auto_accept"
    assert wick_result["copy"]["es_with_year"] == "John Wick 4 (2023)"
    assert surfer_result["decision"] == "auto_accept"
    assert surfer_result["copy"]["es_with_year"] == "The Surfer (2025)"


def test_ambiguous_same_title_needs_confirmation_instead_of_guessing():
    first = movie_payload(3, "Los miserables", "Les Misérables", 2012, original_language="fr")
    second = movie_payload(4, "Los Miserables", "Les Misérables", 1998, original_language="fr")
    client = FakeTmdbClient([first, second])

    result = resolve_spoken_movie_title("Los miserables", client=client)

    assert result["decision"] == "needs_confirmation"
    assert len(result["candidates"]) == 2


def test_low_confidence_fragment_does_not_auto_accept():
    random = movie_payload(5, "Home", "Home", 2015)
    client = FakeTmdbClient([random])

    result = resolve_spoken_movie_title("De jom", client=client)

    assert result["decision"] in {"needs_confirmation", "no_match"}
    assert result["safe"] is False


def test_phonetic_variants_are_searched_even_when_original_query_has_many_candidates():
    distractors = [
        movie_payload(100 + index, f"De Batman {index}", f"De Batman {index}", 1990 + index)
        for index in range(8)
    ]
    batman = movie_payload(200, "Batman", "The Batman", 2022)
    client = FakeTmdbClient([*distractors, batman])

    result = resolve_spoken_movie_title("De Batman", client=client)

    assert any(call[1] == "the batman" for call in client.calls if call[0] == "search")
    assert result["decision"] == "auto_accept"
    assert result["copy"]["original_with_year"] == "The Batman (2022)"
