from __future__ import annotations

import os
import tempfile
import json
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = APP_DIR.parent

BTDIGG_DIR = APP_DIR / "motor" / "btdigg"
DATA = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data"))
HISTORY_DIR = DATA / "history"
HISTORY_FILE = HISTORY_DIR / "btdigg_history.json"
DIAGNOSTICS_DIR = DATA / "diagnostics" / "btdigg"
RD_TEST_DIAGNOSTICS_DIR = DIAGNOSTICS_DIR / "rd_tests"
RD_TEST_EXPORTS_DIR = DIAGNOSTICS_DIR / "_exports" / "rd_tests"
RD_TEST_RETENTION_DAYS = int(os.environ.get("BTDIGG_RD_TEST_RETENTION_DAYS", "14"))
RD_TEST_KEEP_LAST_RUNS = int(os.environ.get("BTDIGG_RD_TEST_KEEP_LAST_RUNS", "200"))
JOB_RUNS_DIR = DATA / "jobs"
JOB_RUN_RETENTION_DAYS = int(os.environ.get("BTDIGG_JOB_RUN_RETENTION_DAYS", "7"))
JOB_RUN_KEEP_LAST_RUNS = int(os.environ.get("BTDIGG_JOB_RUN_KEEP_LAST_RUNS", "100"))
TRACKING_FILE = DATA / "seguimiento_actual.json"

SAFEOUT_FILE = Path(
    os.environ.get(
        "EDITOR_MAESTRO_SAFEOUT",
        str(Path(tempfile.gettempdir()) / "btdigg_rd_safeout.log"),
    )
)
TORRENT_INBOX = Path(os.environ.get("ARR_TORRENT_INBOX", "/watch/torrents/inbox"))

RDT_BASE = os.environ.get("RDT_BASE") or os.environ.get("JW_RDT_BASE") or "http://rdtclient:6500"
RDT_USER = os.environ.get("RDT_USER") or os.environ.get("JW_RDT_USER") or "admin"
RDT_PASS = os.environ.get("RDT_PASS") or os.environ.get("JW_RDT_PASS") or "CAMBIAR_EN_ENTORNO_REAL"

QBIT_BASE = os.environ.get("QBIT_BASE") or "http://qbittorrent:8080"
QBIT_USER = os.environ.get("QBIT_USER") or "admin"
QBIT_PASS = os.environ.get("QBIT_PASS") or "CAMBIAR_EN_ENTORNO_REAL"

REAL_DEBRID_API = os.environ.get("REAL_DEBRID_API") or "https://api.real-debrid.com/rest/1.0"

TITLE_RESOLVER_CACHE_DB = DATA / "title_resolver.sqlite3"
TITLE_RESOLVER_LANGUAGE = os.environ.get("TITLE_RESOLVER_LANGUAGE") or os.environ.get("TMDB_LANGUAGE") or "es-ES"
TITLE_RESOLVER_REGION = os.environ.get("TITLE_RESOLVER_REGION") or os.environ.get("TMDB_REGION") or "ES"
TITLE_RESOLVER_HTTP_TIMEOUT_MS = int(os.environ.get("TITLE_RESOLVER_HTTP_TIMEOUT_MS", "2500"))
TITLE_RESOLVER_TOTAL_BUDGET_MS = int(os.environ.get("TITLE_RESOLVER_TOTAL_BUDGET_MS", "5000"))
TITLE_RESOLVER_POSITIVE_TTL_SEC = int(os.environ.get("TITLE_RESOLVER_POSITIVE_TTL_SEC", str(30 * 24 * 3600)))
TITLE_RESOLVER_NEGATIVE_TTL_SEC = int(os.environ.get("TITLE_RESOLVER_NEGATIVE_TTL_SEC", str(6 * 3600)))


def ensure_runtime_dirs() -> None:
    for path in (
        DATA,
        HISTORY_DIR,
        DIAGNOSTICS_DIR,
        RD_TEST_DIAGNOSTICS_DIR,
        RD_TEST_EXPORTS_DIR,
        JOB_RUNS_DIR,
        BTDIGG_DIR / "exports",
    ):
        path.mkdir(parents=True, exist_ok=True)


def _read_config_value(*keys: str) -> str:
    path = BTDIGG_DIR / "config.json"
    try:
        if not path.exists():
            return ""
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    for key in keys:
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return ""


def title_resolver_token() -> str:
    token = os.environ.get("TMDB_API_TOKEN") or os.environ.get("TITLE_RESOLVER_TMDB_TOKEN") or ""
    token = token.strip()
    if token:
        return token

    token_file = os.environ.get("TMDB_API_TOKEN_FILE") or os.environ.get("TITLE_RESOLVER_TMDB_TOKEN_FILE") or ""
    if token_file:
        try:
            token = Path(token_file).read_text(encoding="utf-8", errors="ignore").strip()
            if token:
                return token
        except Exception:
            pass

    return _read_config_value("tmdb_api_token", "tmdb_token", "TMDB_API_TOKEN")
