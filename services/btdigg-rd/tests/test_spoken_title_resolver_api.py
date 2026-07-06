from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import api.btdigg_rd.routes as routes  # noqa: E402
from api.btdigg_rd.title_resolver.service import TitleResolverTokenMissing  # noqa: E402

spec = importlib.util.spec_from_file_location("btdigg_app_module", APP_DIR / "app.py")
app_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(app_module)
create_app = app_module.create_app


class SpokenTitleResolverApiTests(unittest.TestCase):
    def setUp(self):
        self.original = routes.resolve_spoken_movie_title
        self.app = create_app().test_client()

    def tearDown(self):
        routes.resolve_spoken_movie_title = self.original

    def test_missing_transcript_is_400(self):
        response = self.app.post("/api/spoken-title-resolver/resolve", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error_code"], "missing_transcript")

    def test_auto_accept_response(self):
        def fake_resolve(**kwargs):
            return {
                "ok": True,
                "status": "resolved",
                "decision": "auto_accept",
                "safe": True,
                "copy": {"es_with_year": "The Surfer (2025)"},
            }

        routes.resolve_spoken_movie_title = fake_resolve
        response = self.app.post("/api/spoken-title-resolver/resolve", json={"transcript": "Teesurfer 2025"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["decision"], "auto_accept")

    def test_token_missing_is_503(self):
        def fake_resolve(**kwargs):
            raise TitleResolverTokenMissing("TMDb sin token")

        routes.resolve_spoken_movie_title = fake_resolve
        response = self.app.post("/api/spoken-title-resolver/resolve", json={"transcript": "Peli"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error_code"], "tmdb_token_missing")


if __name__ == "__main__":
    unittest.main()
