from __future__ import annotations

import os
import tempfile
import json
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = APP_DIR.parent

DATA = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data"))
BTDIGG_CODE_DIR = APP_DIR / "motor" / "btdigg"
BTDIGG_RUNTIME_DIR = Path(os.environ.get("BTDIGG_RUNTIME_DIR", DATA / "motor"))
BTDIGG_CONFIG_FILE = Path(os.environ.get("BTDIGG_CONFIG_FILE", BTDIGG_RUNTIME_DIR / "config.json"))
BTDIGG_TOKEN_FILE = Path(os.environ.get("BTDIGG_TOKEN_FILE", BTDIGG_RUNTIME_DIR / "rd_token.txt"))
BTDIGG_EXPORTS_DIR = Path(os.environ.get("BTDIGG_EXPORT_DIR", BTDIGG_RUNTIME_DIR / "exports"))
HISTORY_DIR = DATA / "history"
HISTORY_FILE = HISTORY_DIR / "btdigg_history.json"
DIAGNOSTICS_DIR = DATA / "diagnostics" / "btdigg"
RD_TEST_DIAGNOSTICS_DIR = DIAGNOSTICS_DIR / "rd_tests"
RD_TEST_EXPORTS_DIR = DIAGNOSTICS_DIR / "_exports" / "rd_tests"
RD_TEST_RETENTION_DAYS = int(os.environ.get("BTDIGG_RD_TEST_RETENTION_DAYS", "14"))
RD_TEST_KEEP_LAST_RUNS = int(os.environ.get("BTDIGG_RD_TEST_KEEP_LAST_RUNS", "200"))
VOICE_DIAGNOSTICS_DIR = DIAGNOSTICS_DIR / "voice"
VOICE_DIAGNOSTIC_RETENTION_DAYS = int(os.environ.get("BTDIGG_VOICE_DIAGNOSTIC_RETENTION_DAYS", "3"))
VOICE_DIAGNOSTIC_KEEP_LAST_RUNS = int(os.environ.get("BTDIGG_VOICE_DIAGNOSTIC_KEEP_LAST_RUNS", "80"))
VOICE_TRANSCRIBE_PROVIDER = os.environ.get("BTDIGG_VOICE_TRANSCRIBE_PROVIDER", "auto").strip().lower()
VOICE_TRANSCRIBE_URL = os.environ.get("BTDIGG_VOICE_TRANSCRIBE_URL", "").strip()
VOICE_TRANSCRIBE_TOKEN = os.environ.get("BTDIGG_VOICE_TRANSCRIBE_TOKEN", "").strip()
VOICE_TRANSCRIBE_TIMEOUT_SEC = float(os.environ.get("BTDIGG_VOICE_TRANSCRIBE_TIMEOUT_SEC", "20"))
VOICE_TRANSCRIBE_MAX_AUDIO_MB = float(os.environ.get("BTDIGG_VOICE_TRANSCRIBE_MAX_AUDIO_MB", "8"))
VOICE_OPENAI_API_KEY = (os.environ.get("BTDIGG_VOICE_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
VOICE_OPENAI_BASE_URL = os.environ.get("BTDIGG_VOICE_OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
VOICE_OPENAI_MODEL = os.environ.get("BTDIGG_VOICE_OPENAI_MODEL", "gpt-4o-mini-transcribe").strip()
VOICE_OPENAI_PROMPT = os.environ.get("BTDIGG_VOICE_OPENAI_PROMPT", "").strip()
VOICE_OPENAI_TEMPERATURE = os.environ.get("BTDIGG_VOICE_OPENAI_TEMPERATURE", "0").strip()
JOB_RUNS_DIR = DATA / "jobs"
JOB_RUN_RETENTION_DAYS = int(os.environ.get("BTDIGG_JOB_RUN_RETENTION_DAYS", "7"))
JOB_RUN_KEEP_LAST_RUNS = int(os.environ.get("BTDIGG_JOB_RUN_KEEP_LAST_RUNS", "100"))
TRACKING_FILE = DATA / "seguimiento_actual.json"
UI_STATE_FILE = DATA / "ui_state.json"

SAFEOUT_FILE = Path(
    os.environ.get(
        "EDITOR_MAESTRO_SAFEOUT",
        str(Path(tempfile.gettempdir()) / "btdigg_rd_safeout.log"),
    )
)
TORRENT_INBOX = Path(os.environ.get("ARR_TORRENT_INBOX", "/watch/torrents/inbox"))

RDT_BASE = os.environ.get("RDT_BASE") or os.environ.get("JW_RDT_BASE") or "http://rdtclient:6500"
RDT_USER = os.environ.get("RDT_USER") or os.environ.get("JW_RDT_USER") or ""
RDT_PASS = os.environ.get("RDT_PASS") or os.environ.get("JW_RDT_PASS") or ""

QBIT_BASE = os.environ.get("QBIT_BASE") or "http://qbittorrent:8080"
QBIT_USER = os.environ.get("QBIT_USER") or ""
QBIT_PASS = os.environ.get("QBIT_PASS") or ""

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
        VOICE_DIAGNOSTICS_DIR,
        JOB_RUNS_DIR,
        BTDIGG_RUNTIME_DIR,
        BTDIGG_EXPORTS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _read_config_value(*keys: str) -> str:
    path = BTDIGG_CONFIG_FILE
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
