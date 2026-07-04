import sys
import unittest
import importlib.util
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


class TitleResolverApiTests(unittest.TestCase):
    def setUp(self):
        self.original = routes.resolve_movie_title
        self.app = create_app().test_client()

    def tearDown(self):
        routes.resolve_movie_title = self.original

    def test_missing_title_is_400(self):
        response = self.app.post("/api/title-resolver/resolve", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error_code"], "missing_title")

    def test_resolved_response(self):
        def fake_resolve(**kwargs):
            return {
                "ok": True,
                "status": "resolved",
                "safe": True,
                "copy": {
                    "es": "Un padre en apuros",
                    "es_with_year": "Un padre en apuros (1996)",
                    "en": "Jingle All the Way",
                    "en_with_year": "Jingle All the Way (1996)",
                },
            }

        routes.resolve_movie_title = fake_resolve
        response = self.app.post("/api/title-resolver/resolve", json={"title": "Un padre en apuros.mkv"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "resolved")

    def test_token_missing_is_503(self):
        def fake_resolve(**kwargs):
            raise TitleResolverTokenMissing("TMDb sin token")

        routes.resolve_movie_title = fake_resolve
        response = self.app.post("/api/title-resolver/resolve", json={"title": "Peli.mkv"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error_code"], "tmdb_token_missing")


if __name__ == "__main__":
    unittest.main()
