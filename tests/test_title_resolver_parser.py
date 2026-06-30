import unittest
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from api.btdigg_rd.title_resolver.parser import parse_release_name  # noqa: E402


class TitleResolverParserTests(unittest.TestCase):
    def test_movie_release_extracts_title_without_year(self):
        parsed = parse_release_name("Un padre en apuros 4Kwebrip2160.atomohd.li.mkv")

        self.assertEqual(parsed.media_hint, "movies")
        self.assertEqual(parsed.display_title, "Un padre en apuros")

    def test_bilingual_title_candidates(self):
        parsed = parse_release_name("Red One (Codigo Traje Rojo) (2024) cast.mp4")

        self.assertEqual(parsed.year, 2024)
        self.assertIn("Red One", parsed.title_candidates)
        self.assertIn("Codigo Traje Rojo", parsed.title_candidates)

    def test_technical_tokens_are_removed(self):
        parsed = parse_release_name("Snatch.2000.2160p.AMZN.WEB-DL.x265")

        self.assertEqual(parsed.year, 2000)
        self.assertEqual(parsed.display_title, "Snatch")

    def test_btdigg_style_title(self):
        parsed = parse_release_name("Maridos.En.Accion.2026.1080P-Dual-Lat.mkv")

        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.display_title, "Maridos En Accion")

    def test_tv_is_blocked_for_movie_resolver(self):
        parsed = parse_release_name("La reina del flow S03 E53 (2026) NETFLIX.mkv")

        self.assertEqual(parsed.media_hint, "tv")
        self.assertEqual(parsed.category_conflict, "movies_vs_tv")

    def test_manual_generic_is_weak(self):
        parsed = parse_release_name("MY BOOKS")

        self.assertEqual(parsed.media_hint, "manual")
        self.assertEqual(parsed.weak_reason, "manual_or_generic")


if __name__ == "__main__":
    unittest.main()
