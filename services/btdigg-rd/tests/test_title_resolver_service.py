import tempfile
import unittest
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from api.btdigg_rd.title_resolver.cache import TitleResolverCache  # noqa: E402
from api.btdigg_rd.title_resolver.service import resolve_movie_title  # noqa: E402


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

    def __init__(self, search_results, details=None):
        self.search_results = search_results
        self.details = details or {}
        self.calls = []

    def search_movie(self, query, year=None, language=None):
        self.calls.append(("search", query, year, language))
        result = self.search_results(query, year, language) if callable(self.search_results) else self.search_results
        return {"results": result}

    def movie_details(self, tmdb_id):
        self.calls.append(("details", tmdb_id))
        return self.details.get(tmdb_id) or next(item for item in self.search_results if item["id"] == tmdb_id)


class TitleResolverServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = TitleResolverCache(Path(self.tmp.name) / "cache.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolves_spanish_and_original_copy_values(self):
        correct = movie_payload(9279, "Un padre en apuros", "Jingle All the Way", 1996)
        client = FakeTmdbClient([correct], {9279: correct})

        result = resolve_movie_title(
            "Un padre en apuros 4Kwebrip2160.atomohd.li.mkv",
            client=client,
            cache=self.cache,
        )

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["copy"]["es_with_year"], "Un padre en apuros (1996)")
        self.assertEqual(result["copy"]["en_with_year"], "Jingle All the Way (1996)")

    def test_uses_english_translation_instead_of_non_english_original(self):
        correct = movie_payload(
            1,
            "Maridos en acción",
            "남편들",
            2026,
            english_title="Husbands",
            original_language="ko",
        )
        client = FakeTmdbClient([correct], {1: correct})

        result = resolve_movie_title("Maridos en accion 2026.mkv", client=client, cache=self.cache)

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["copy"]["es_with_year"], "Maridos en acción (2026)")
        self.assertEqual(result["copy"]["en_with_year"], "Husbands (2026)")

    def test_prefers_matching_year(self):
        old = movie_payload(11224, "Cenicienta", "Cinderella", 1950)
        current = movie_payload(150689, "Cenicienta", "Cinderella", 2015)
        client = FakeTmdbClient([old, current], {11224: old, 150689: current})

        result = resolve_movie_title("Cenicienta.2015.2160p.mkv", client=client, cache=self.cache)

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["match"]["tmdb_id"], 150689)

    def test_ambiguous_margin_returns_not_sure(self):
        first = movie_payload(1, "El desconocido", "Unknown", 2000)
        second = movie_payload(2, "El desconocido", "Unknown", 2000)
        client = FakeTmdbClient([first, second], {1: first, 2: second})

        result = resolve_movie_title("El desconocido.2000.mkv", client=client, cache=self.cache)

        self.assertEqual(result["status"], "not_sure")
        self.assertFalse(result["safe"])

    def test_cache_avoids_second_tmdb_lookup(self):
        correct = movie_payload(9279, "Un padre en apuros", "Jingle All the Way", 1996)
        client = FakeTmdbClient([correct], {9279: correct})

        first = resolve_movie_title("Un padre en apuros.mkv", client=client, cache=self.cache)
        calls_after_first = len(client.calls)
        second = resolve_movie_title("Un padre en apuros.mkv", client=client, cache=self.cache)

        self.assertEqual(first["match"]["tmdb_id"], second["match"]["tmdb_id"])
        self.assertEqual(len(client.calls), calls_after_first)
        self.assertTrue(second["cache"]["hit"])

    def test_tv_is_not_sure_without_tmdb_call(self):
        client = FakeTmdbClient([])

        result = resolve_movie_title("La reina del flow S03 E53 (2026) NETFLIX.mkv", client=client, cache=self.cache)

        self.assertEqual(result["status"], "not_sure")
        self.assertEqual(client.calls, [])

    def test_voice_strict_short_blocks_ambiguous_words_without_tmdb_call(self):
        client = FakeTmdbClient([movie_payload(1, "Dios", "Dios", 2026)])

        result = resolve_movie_title("Dios", strict_short=True, client=client, cache=self.cache)

        self.assertEqual(result["status"], "not_sure")
        self.assertEqual(result["reason_code"], "short_ambiguous_voice_title")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
