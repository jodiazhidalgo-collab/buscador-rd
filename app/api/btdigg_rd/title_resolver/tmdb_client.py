from __future__ import annotations

from typing import Any

import requests


TMDB_BASE_URL = "https://api.themoviedb.org/3"


class TmdbError(RuntimeError):
    pass


class TmdbUnavailable(TmdbError):
    pass


class TmdbClient:
    def __init__(
        self,
        token: str,
        language: str = "es-ES",
        region: str = "ES",
        timeout_sec: float = 2.5,
        session: requests.Session | None = None,
    ):
        self.token = token.strip()
        self.language = language.strip() or "es-ES"
        self.region = region.strip() or "ES"
        self.timeout_sec = max(0.5, float(timeout_sec or 2.5))
        self.session = session or requests.Session()

    def search_movie(self, query: str, year: int | None = None, language: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "query": query,
            "language": language or self.language,
            "region": self.region,
        }
        if year:
            params["year"] = year
        return self._get("/search/movie", params)

    def movie_details(self, tmdb_id: int) -> dict[str, Any]:
        return self._get(
            f"/movie/{int(tmdb_id)}",
            {"language": self.language, "append_to_response": "translations,alternative_titles"},
        )

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.get(
                f"{TMDB_BASE_URL}{endpoint}",
                params=params,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/json",
                },
                timeout=self.timeout_sec,
            )
        except requests.RequestException as exc:
            raise TmdbUnavailable(f"TMDb no disponible: {exc}") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise TmdbUnavailable(f"TMDb respondio HTTP {response.status_code}")
        if response.status_code >= 400:
            raise TmdbError(f"TMDb rechazo la consulta: HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise TmdbUnavailable("TMDb devolvio JSON invalido") from exc
        return data if isinstance(data, dict) else {}
