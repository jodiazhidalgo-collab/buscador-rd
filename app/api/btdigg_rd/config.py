from __future__ import annotations

import os
import tempfile
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


def ensure_runtime_dirs() -> None:
    for path in (
        DATA,
        HISTORY_DIR,
        DIAGNOSTICS_DIR,
        RD_TEST_DIAGNOSTICS_DIR,
        RD_TEST_EXPORTS_DIR,
        BTDIGG_DIR / "exports",
    ):
        path.mkdir(parents=True, exist_ok=True)
