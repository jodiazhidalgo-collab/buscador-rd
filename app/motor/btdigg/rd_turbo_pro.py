#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
RD Turbo Pro v2.4
Motor local: BTDigg / magnet / Real-Debrid / JDownloader.

Carpeta recomendada: C:\RD_Turbo_Pro
Token: rd_token.txt
"""

import os
import re
import sys
import tempfile
import socket
import hashlib
import json
import time
import html
import base64
import collections
import queue
import subprocess
import threading
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, parse_qs, urlencode, urljoin
from urllib.request import Request, urlopen, build_opener, HTTPCookieProcessor
import http.cookiejar
from urllib.error import HTTPError, URLError
from contextlib import contextmanager

_MOTOR_DIR = Path(__file__).resolve().parent
if str(_MOTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_MOTOR_DIR))

from _motor_exports import export_results_impl
from _motor_qbt_probe import qbt_probe_one_impl
from _motor_rd_retry import rd_call_with_retry_impl

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "config.json"
TOKEN_FILE = APP_DIR / "rd_token.txt"
LOG_DIR = Path(os.environ.get("BTDIGG_LEGACY_LOG_DIR", str(Path(tempfile.gettempdir()) / "btdigg_rd_legacy_logs")))
LAST_LINKS_FILE = Path(os.environ.get("BTDIGG_LAST_LINKS_FILE", str(APP_DIR / "last_links.txt")))
EXPORT_DIR = Path(os.environ.get("BTDIGG_EXPORT_DIR", str(APP_DIR / "exports")))
CANCEL_FILE = Path(os.environ["BTDIGG_CANCEL_FILE"]) if os.environ.get("BTDIGG_CANCEL_FILE") else None
_CANCEL_LOCAL = threading.local()
LEGACY_MOTOR_LOGS = str(os.environ.get("BTDIGG_LEGACY_MOTOR_LOGS", "")).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}

if LEGACY_MOTOR_LOGS:
    LOG_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

RUN_STAMP = time.strftime("%Y-%m-%d_%H-%M-%S")
RUN_LOG_FILE = LOG_DIR / f"legacy_motor_{RUN_STAMP}.log"
DIAG_FILE = LOG_DIR / "legacy_motor_diagnostic.txt"
STEP2_DIAG_FILE = LOG_DIR / "legacy_step2_events.jsonl"
DIAG_EVENTS = []
CURRENT_QUERY = ""
CURRENT_MIN_SIZE_GB = 0.0
LAST_QBIT_EXTRAS = []
RD_EXISTING_TORRENTS_CACHE = None
DIAG_LOCK = threading.RLock()
RD_EXISTING_LOCK = threading.RLock()
RD_RUNTIME_LOCK = threading.RLock()
RD_RUNTIME = None
RD_RATE_LIMITER = None
RD_RATE_LIMITER_KEY = None
RD_ENDPOINT_PACER = None
RD_ENDPOINT_PACER_KEY = None
RD_INSTANT_DISABLED_UNTIL = 0.0


class UserCancelled(BaseException):
    """Cancelacion cooperativa pedida desde la web."""


def cancel_requested():
    if not CANCEL_FILE:
        return False
    try:
        if not CANCEL_FILE.exists():
            return False
        text = CANCEL_FILE.read_text(encoding="utf-8", errors="ignore").lower()
    except Exception:
        return False
    return '"cancel_requested": true' in text or "cancel_requested=true" in text or text.strip() in {"1", "true", "cancel"}


def _cancel_disabled():
    return int(getattr(_CANCEL_LOCAL, "disabled", 0) or 0) > 0


def cancel_checkpoint(where=""):
    if _cancel_disabled():
        return
    if cancel_requested():
        try:
            diag("job_cancel_checkpoint", where=str(where or "")[:120])
        except Exception:
            pass
        raise UserCancelled(str(where or "cancelled"))


def sleep_interruptible(seconds, step=0.25, where="sleep"):
    end = time.monotonic() + max(0.0, float(seconds or 0.0))
    while True:
        cancel_checkpoint(where)
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(max(0.01, float(step or 0.25)), remaining))


@contextmanager
def non_cancelable_cleanup():
    current = int(getattr(_CANCEL_LOCAL, "disabled", 0) or 0)
    _CANCEL_LOCAL.disabled = current + 1
    try:
        yield
    finally:
        _CANCEL_LOCAL.disabled = current


def run_capture_interruptible(cmd, timeout, where):
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    deadline = time.monotonic() + max(1.0, float(timeout or 1.0))
    try:
        while True:
            try:
                out, err = process.communicate(timeout=0.25)
                return process.returncode, out, err
            except subprocess.TimeoutExpired:
                cancel_checkpoint(where)
                if time.monotonic() >= deadline:
                    process.kill()
                    out, err = process.communicate()
                    raise subprocess.TimeoutExpired(cmd, timeout, output=out, stderr=err)
    except UserCancelled:
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        raise

DEFAULT_CONFIG = {
    "version": "2.4",
    "real_debrid_api_base": "https://api.real-debrid.com/rest/1.0",
    "default_mode": 0,
    "default_pages": "1-5",
    "quick_test_default_pages": "1",
    "safe_max_pages_when_zero": 30,
    "browser_preferred": "edge",
    "browser_debug_port": 9227,
    "browser_wait_after_load_sec": 5,
    "browser_delay_between_pages_sec": 2,
    "browser_close_when_done": False,
    "max_results_to_show": 30,
    "hide_non_working_results": True,
    "rd_fast_mode_enabled": True,
    "rd_verify_queue_enabled": True,
    "rd_api_rate_limit_per_min": 235,
    "rd_api_rate_limit_burst": 4,
    "rd_api_429_cooldown_sec": 3.0,
    "rd_mass_429_cooldown_sec": 10.0,
    "rd_mass_429_groups_threshold": 3,
    "rd_mass_429_total_threshold": 5,
    "rd_mass_429_window_sec": 20.0,
    "rd_429_retry_attempts": 6,
    "rd_endpoint_pacer_enabled": True,
    "rd_endpoint_adaptive_429_enabled": True,
    "rd_addmagnet_min_interval_sec": 1.0,
    "rd_selectfiles_min_interval_sec": 0.75,
    "rd_delete_min_interval_sec": 0.65,
    "rd_info_min_interval_sec": 0.10,
    "rd_activecount_min_interval_sec": 0.80,
    "rd_torrents_list_min_interval_sec": 0.80,
    "rd_other_min_interval_sec": 0.10,
    "rd_addmagnet_max_concurrent": 1,
    "rd_selectfiles_max_concurrent": 1,
    "rd_delete_max_concurrent": 1,
    "rd_info_max_concurrent": 4,
    "rd_activecount_max_concurrent": 1,
    "rd_torrents_list_max_concurrent": 1,
    "rd_other_max_concurrent": 2,
    "rd_endpoint_429_cooldown_sec": 6.0,
    "rd_endpoint_429_min_interval_multiplier": 1.35,
    "rd_endpoint_429_min_interval_max_sec": 2.50,
    "rd_endpoint_recover_after_sec": 60.0,
    "rd_endpoint_recover_multiplier": 0.90,
    "rd_fast_discard_enabled": True,
    "rd_fast_discard_message_match_enabled": True,
    "rd_fast_discard_zero_progress_enabled": True,
    "rd_fast_discard_dead_status_enabled": True,
    "rd_diag_rate_wait_throttle_sec": 5.0,
    "rd_diag_api_call_count_enabled": False,
    "rd_diag_rate_wait_summary_enabled": True,
    "rd_active_slots_enabled": True,
    "rd_active_slots_refresh_sec": 2.0,
    "rd_active_slots_wait_sec": 0.35,
    "rd_active_slots_release_on_downloaded": True,
    "rd_existing_preload_enabled": True,
    "rd_existing_index_by_hash": True,
    "rd_existing_info_cache_enabled": True,
    "rd_existing_active_limit_on_33": 500,
    "rd_retry_21_wait_sec": 1.5,
    "rd_retry_33_resolve_existing": True,
    "rd_instant_disabled_cache_ttl_sec": 900,
    "rd_delete_retry_attempts": 5,
    "rd_delete_retry_base_sec": 0.8,
    "rd_delete_retry_max_sec": 4.0,
    "rd_final_cleanup_enabled": True,
    "rd_cleanup_final_skip_already_deleted": True,
    "rd_final_cleanup_attempts": 3,
    "rd_final_cleanup_wait_sec": 1.5,
    "rd_post_select_extra_poll_enabled": True,
    "rd_post_select_poll_sec": 0.25,
    "verify_candidates_when_api_off": True,
    "verify_instant_results_with_addmagnet": True,
    "verify_max_candidates": 60,
    "rd_verify_parallel_workers": 60,
    "rd_temp_error_retries": 2,
    "rd_temp_error_retry_sec": 1.0,
    "torrent_candidate_probe_enabled": True,
    "torrent_candidate_probe_max": 40,
    "torrent_candidate_probe_timeout_sec": 12,
    "verify_wait_attempts": 1,
    "verify_wait_sec": 0.25,
    "cleanup_failed_verifications": True,
    "cleanup_unselected_verified": True,
    "qbit_probe_enabled": True,
    "qbit_probe_only_non_rd_working": True,
    "qbit_host": "http://qbittorrent:8080",
    "qbit_user": "admin",
    "qbit_pass": "CAMBIAR_EN_ENTORNO_REAL",
    "qbit_probe_save_path": "/data/downloads/torrents/incomplete/rd_turbo_probe",
    "qbit_probe_category": "manual",
    "qbit_probe_max_candidates": 15,
    "qbit_probe_parallel_workers": 4,
    "qbit_probe_wait_sec": 16,
    "qbit_probe_poll_sec": 2,
    "qbit_delete_probe_after": True,
    "qbit_show_metadata_only": False,
    "qbit_require_same_file_match": True,
    "qbit_same_file_min_ratio": 1.0,
    "qbit_show_irrelevant_skipped": False,
    "strict_query_prefilter": True,
    "strict_query_prefilter_min_ratio": 1.0,
    "strict_query_prefilter_keep_discarded_in_exports": True,
    "rd_rescue_enabled": True,
    "rd_rescue_max_candidates": 5,
    "rd_rescue_only_if_no_rd_ok": True,
    "rd_rescue_min_title_ratio": 0.5,
    "rd_check_existing_torrents": True,
    "rd_existing_torrents_limit": 1000,
    "screen_hide_qbit_not_working": True,
    "pack_auto_select_best_file": True,
    "pack_only_video_files": True,
    "pack_min_video_gb": 0.3,
    "pack_query_match_min_ratio": 0.55,
    "pack_hard_skip_without_match": True,
    "pack_allow_title_single_video_fallback": True,
    "pack_title_fallback_min_video_gb": 1.0,
    "quality_min_size_tolerance_gb": 1.0,
    "quality_min_size_tolerance_pct": 0.05,
    "quality_min_size_tolerance_max_gb": 3.0,
    "quality_mode_extra_btdigg_enabled": True,
    "quality_mode_extra_btdigg_terms": ["2160p"],
    "quality_mode_extra_btdigg_pages": "1",
    "request_timeout_sec": 20,
    "delay_between_rd_checks_sec": 0.0,
    "delay_between_btdigg_pages_sec": 7,
    "delay_after_btdigg_429_sec": 8,
    "stop_btdigg_on_429": False,
    "jdownloader_clipboard_mode": True,
    "write_last_links_txt": True,
    "write_exports": True,
    "diagnostic_rd_items": True,
    "btdigg_url_templates": [
        "https://en.btdig.com/search?q={query_quote}&p={page0}",
        "https://btdig.com/search?q={query_quote}&p={page0}",
        "https://en.btdig.com/search?order=0&q={query_quote}&p={page0}",
        "https://btdig.com/search?order=0&q={query_quote}&p={page0}"
    ],
    "authorized_search_url_template": "",
    "direct_link_extensions": [
        ".torrent",
        ".zip", ".rar", ".7z", ".tar", ".gz",
        ".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".m2ts",
        ".iso", ".exe", ".msi", ".pdf"
    ],
    "direct_link_min_size_mb": 1,
    "direct_link_max_candidates": 80,
    "direct_link_check_timeout_sec": 12,
    "authorized_site_max_detail_pages": 12,
    "authorized_site_download_clicks_max": 4,
    "authorized_site_download_wait_sec": 4,
    "authorized_site_link_hops_max": 3,
    "authorized_site_search_paths": [
        "?s={query}",
        "?search={query}",
        "search/{query}/",
        "buscar/{query}/"
    ],
    "authorized_site_browser_fallback": True,
    "torznab_enabled": False,
    "torznab_url": "",
    "torznab_api_key": "",
    "torznab_categories": "",
    "torznab_min_seeders": 1,
    "torznab_max_results": 30,
    "language_good": ["castellano", "espanol", "español", "spanish", "spain", "esp", "es-en", "es_en", "dual", "cast", "spa"],
    "language_bad": ["latino", "latin", "vose", "subtitulado"],
    "quality_weights": {
        "2160p": 35, "4k": 35, "uhd": 32,
        "remux": 30, "bdremux": 35,
        "bluray": 24, "blu-ray": 24,
        "1080p": 22, "web-dl": 16, "webrip": 12,
        "h265": 10, "x265": 10, "hevc": 10,
        "hdr": 8, "dv": 7, "720p": 5, "10bit": 8, "10bits": 8, "dts": 5, "truehd": 8, "atmos": 8,
    },
    "bad_words": [
        "cam", "camrip", "ts", "telesync", "screener", "hdcam", "hdts", "workprint",
        "telecine", "hdtc", "dvdscr", "dvdscreener", "bdscr", "webscr", "webscreener",
        "pdvd", "predvdrip", "pre-dvd",
    ],
    "min_size_gb": 0.3,
    "max_size_gb": 120,
}

def load_config():
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    merged = DEFAULT_CONFIG.copy()
    merged.update(data)
    return merged

CONFIG = load_config()
if str(os.environ.get("BTDIGG_DISABLE_EXPORTS", "")).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}:
    CONFIG["write_exports"] = False
if str(os.environ.get("BTDIGG_DISABLE_LAST_LINKS", "")).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}:
    CONFIG["write_last_links_txt"] = False


class RDAPIError(RuntimeError):
    def __init__(self, method, path, status_code, body_text="", payload=None):
        self.method = str(method or "").upper()
        self.path = str(path or "")
        self.status_code = int(status_code or 0)
        self.body_text = str(body_text or "")
        self.payload = payload if isinstance(payload, dict) else {}
        self.error = str(self.payload.get("error") or "")
        self.error_code = self.payload.get("error_code")
        try:
            self.error_code = int(self.error_code) if self.error_code is not None else None
        except Exception:
            pass
        super().__init__(self.__str__())

    def __str__(self):
        detail = self.body_text[:500]
        if self.error_code is not None or self.error:
            extra = f" [{self.error_code} {self.error}]".strip()
            return f"Real-Debrid HTTP {self.status_code}: {extra} {detail}".strip()
        return f"Real-Debrid HTTP {self.status_code}: {detail}"

    @property
    def is_429(self):
        return self.status_code == 429 or self.error_code == 34

    @property
    def is_active_limit(self):
        return self.error_code == 21

    @property
    def is_already_active(self):
        return self.error_code == 33

    @property
    def is_infringing(self):
        return self.status_code == 451 or self.error_code == 35

    @property
    def is_disabled_endpoint(self):
        return self.error_code == 37

    @property
    def is_temp(self):
        return self.status_code in (429, 502, 503, 504) or self.error_code in (34,)


def _rd_path_group(path):
    text = str(path or "")
    text = re.sub(r"/torrents/info/[^/?]+", "/torrents/info/:id", text)
    text = re.sub(r"/torrents/delete/[^/?]+", "/torrents/delete/:id", text)
    text = re.sub(r"/torrents/selectFiles/[^/?]+", "/torrents/selectFiles/:id", text)
    text = re.sub(r"/torrents/instantAvailability/[^/?]+", "/torrents/instantAvailability/:hash", text)
    return text.split("?", 1)[0]


class RDRateLimiter:
    def __init__(self, per_min=235, burst=4, cooldown_sec=3.0):
        self.per_min = max(1, int(per_min or 235))
        self.burst = max(1, int(burst or 4))
        self.cooldown_sec = max(0.0, float(cooldown_sec or 0.0))
        self.lock = threading.Condition()
        self.events = collections.deque()
        self.cooldown_until = 0.0
        self.max_window = 0
        self.max_burst = 0
        self.api_calls_total = 0
        self.api_calls_by_method = collections.Counter()
        self.api_calls_by_path_group = collections.Counter()
        self.waits_total = 0
        self.waits_by_reason = collections.Counter()
        self.wait_seconds_total = 0.0
        self.max_wait_sec = 0.0
        self.cooldowns_429 = 0
        self.last_wait_diag = 0.0

    def _record_api_call(self, method, path, window_count, burst_count):
        self.api_calls_total += 1
        self.api_calls_by_method[method] += 1
        self.api_calls_by_path_group[_rd_path_group(path)] += 1
        self.max_window = max(self.max_window, window_count)
        self.max_burst = max(self.max_burst, burst_count)
        if CONFIG.get("rd_diag_api_call_count_enabled", False):
            diag(
                "rd_api_call_count",
                method=method,
                path=_rd_path_group(path),
                window_count=window_count,
                per_min=self.per_min,
                burst_count=burst_count,
                burst=self.burst,
                max_window=self.max_window,
            )

    def _record_wait(self, reason, wait_sec, method, path):
        self.waits_total += 1
        self.waits_by_reason[reason] += 1
        self.wait_seconds_total += max(0.0, float(wait_sec or 0.0))
        self.max_wait_sec = max(self.max_wait_sec, max(0.0, float(wait_sec or 0.0)))
        now = time.monotonic()
        throttle = max(0.5, float(CONFIG.get("rd_diag_rate_wait_throttle_sec", 5.0) or 5.0))
        should_diag = (now - self.last_wait_diag) >= throttle
        if should_diag:
            self.last_wait_diag = now
            diag(
                "rd_rate_wait",
                why=reason,
                wait_sec=round(wait_sec, 3),
                method=method,
                path=_rd_path_group(path),
                waits_total=self.waits_total,
                wait_seconds_total=round(self.wait_seconds_total, 3),
                max_wait_sec=round(self.max_wait_sec, 3),
            )

    def snapshot(self):
        with self.lock:
            return {
                "api_calls_total": self.api_calls_total,
                "api_calls_by_method": dict(self.api_calls_by_method),
                "api_calls_by_path_group": dict(self.api_calls_by_path_group),
                "waits_total": self.waits_total,
                "waits_by_reason": dict(self.waits_by_reason),
                "wait_seconds_total": round(self.wait_seconds_total, 3),
                "max_wait_sec": round(self.max_wait_sec, 3),
                "max_window_count": self.max_window,
                "max_burst_count": self.max_burst,
                "cooldowns_429": self.cooldowns_429,
                "per_min": self.per_min,
                "burst": self.burst,
            }

    def acquire(self, method, path):
        method = str(method or "").upper()
        path = str(path or "")
        with self.lock:
            while True:
                cancel_checkpoint("rd_rate_limiter")
                now = time.monotonic()
                if now < self.cooldown_until:
                    wait_sec = self.cooldown_until - now
                    self._record_wait("429_cooldown", wait_sec, method, path)
                    self.lock.wait(timeout=min(wait_sec, 2.0))
                    cancel_checkpoint("rd_rate_limiter.cooldown")
                    continue

                while self.events and (now - self.events[0]) >= 60.0:
                    self.events.popleft()

                minute_full = len(self.events) >= self.per_min
                burst_events = [t for t in self.events if now - t < 1.0]
                burst_full = len(burst_events) >= self.burst

                if not minute_full and not burst_full:
                    self.events.append(now)
                    self._record_api_call(method, path, len(self.events), len(burst_events) + 1)
                    return

                waits = []
                if minute_full and self.events:
                    waits.append(max(0.05, 60.0 - (now - self.events[0])))
                if burst_full and burst_events:
                    waits.append(max(0.05, 1.0 - (now - burst_events[0])))
                wait_sec = min(waits) if waits else 0.05
                self._record_wait("minute" if minute_full else "burst", wait_sec, method, path)
                self.lock.wait(timeout=min(wait_sec, 2.0))
                cancel_checkpoint("rd_rate_limiter.wait")

    def notify_429(self, err, cooldown_override=None):
        with self.lock:
            cooldown_sec = self.cooldown_sec if cooldown_override is None else max(0.0, float(cooldown_override or 0.0))
            self.cooldown_until = max(self.cooldown_until, time.monotonic() + cooldown_sec)
            self.cooldowns_429 += 1
            diag("rd_rate_429_cooldown", cooldown_sec=cooldown_sec, path=getattr(err, "path", ""), code=getattr(err, "status_code", 0), error_code=getattr(err, "error_code", None))
            self.lock.notify_all()


def get_rd_rate_limiter():
    global RD_RATE_LIMITER, RD_RATE_LIMITER_KEY
    if not CONFIG.get("rd_fast_mode_enabled", True):
        return None
    per_min = max(1, int(CONFIG.get("rd_api_rate_limit_per_min", 235) or 235))
    burst = max(1, int(CONFIG.get("rd_api_rate_limit_burst", 4) or 4))
    cooldown = max(0.0, float(CONFIG.get("rd_api_429_cooldown_sec", 3.0) or 3.0))
    key = (per_min, burst, cooldown)
    with RD_RUNTIME_LOCK:
        if RD_RATE_LIMITER is None or RD_RATE_LIMITER_KEY != key:
            RD_RATE_LIMITER = RDRateLimiter(per_min=per_min, burst=burst, cooldown_sec=cooldown)
            RD_RATE_LIMITER_KEY = key
        return RD_RATE_LIMITER


def _rd_endpoint_group(method, path):
    method = str(method or "").upper()
    p = str(path or "").split("?", 1)[0]
    if method == "POST" and p == "/torrents/addMagnet":
        return "addMagnet"
    if method == "POST" and p.startswith("/torrents/selectFiles/"):
        return "selectFiles"
    if method == "DELETE" and p.startswith("/torrents/delete/"):
        return "delete"
    if method == "GET" and p.startswith("/torrents/info/"):
        return "info"
    if method == "GET" and p == "/torrents/activeCount":
        return "activeCount"
    if method == "GET" and p == "/torrents":
        return "list"
    return "other"


class RDEndpointPacer:
    GROUPS = ("addMagnet", "selectFiles", "delete", "info", "activeCount", "list", "other")

    def __init__(self):
        self.enabled = bool(CONFIG.get("rd_endpoint_pacer_enabled", True))
        self.adaptive = bool(CONFIG.get("rd_endpoint_adaptive_429_enabled", True))
        self.lock = threading.Condition()
        self.recent_429 = collections.deque()
        self.calls_by_group = collections.Counter()
        self.waits_by_group = collections.Counter()
        self.wait_seconds_by_group = collections.Counter()
        self.http_429_by_group = collections.Counter()
        self.cooldowns_by_group = collections.Counter()
        self.max_concurrent_by_group = collections.Counter()
        self.last_wait_diag_by_group = {}
        self.last_recover_diag_by_group = {}
        self.state = {}
        for group in self.GROUPS:
            base_interval = self._cfg_float(group, "min_interval_sec", 0.10)
            self.state[group] = {
                "base_interval": base_interval,
                "min_interval": base_interval,
                "max_concurrent": self._cfg_int(group, "max_concurrent", 1 if group != "info" else 4),
                "inflight": 0,
                "next_allowed_at": 0.0,
                "cooldown_until": 0.0,
                "last_429": 0.0,
            }

    def _cfg_prefix(self, group):
        return {
            "addMagnet": "rd_addmagnet",
            "selectFiles": "rd_selectfiles",
            "delete": "rd_delete",
            "info": "rd_info",
            "activeCount": "rd_activecount",
            "list": "rd_torrents_list",
            "other": "rd_other",
        }.get(group, "rd_other")

    def _cfg_float(self, group, suffix, default):
        return max(0.0, float(CONFIG.get(f"{self._cfg_prefix(group)}_{suffix}", default) or default))

    def _cfg_int(self, group, suffix, default):
        return max(1, int(CONFIG.get(f"{self._cfg_prefix(group)}_{suffix}", default) or default))

    def _trim_recent(self, now):
        window = max(1.0, float(CONFIG.get("rd_mass_429_window_sec", 20.0) or 20.0))
        while self.recent_429 and now - self.recent_429[0][0] > window:
            self.recent_429.popleft()

    def _massive_429(self, now):
        self._trim_recent(now)
        groups = {group for _ts, group in self.recent_429}
        group_threshold = max(1, int(CONFIG.get("rd_mass_429_groups_threshold", 3) or 3))
        total_threshold = max(1, int(CONFIG.get("rd_mass_429_total_threshold", 5) or 5))
        return len(groups) >= group_threshold or len(self.recent_429) >= total_threshold

    def _maybe_recover_locked(self, group, now):
        st = self.state[group]
        last_429 = float(st.get("last_429") or 0.0)
        if not self.adaptive or not last_429:
            return
        recover_after = max(1.0, float(CONFIG.get("rd_endpoint_recover_after_sec", 60.0) or 60.0))
        if now - last_429 < recover_after:
            return
        base_interval = float(st["base_interval"])
        current = float(st["min_interval"])
        if current <= base_interval:
            return
        multiplier = max(0.01, min(1.0, float(CONFIG.get("rd_endpoint_recover_multiplier", 0.90) or 0.90)))
        new_interval = max(base_interval, current * multiplier)
        if round(new_interval, 3) == round(current, 3):
            return
        st["min_interval"] = new_interval
        last_diag = self.last_recover_diag_by_group.get(group, 0.0)
        if now - last_diag >= 5.0:
            self.last_recover_diag_by_group[group] = now
            diag("rd_endpoint_recover", group=group, min_interval=round(new_interval, 3), base_interval=round(base_interval, 3))

    def _record_wait_locked(self, group, wait_sec, method, path, why):
        self.waits_by_group[group] += 1
        self.wait_seconds_by_group[group] += max(0.0, float(wait_sec or 0.0))
        now = time.monotonic()
        throttle = max(0.5, float(CONFIG.get("rd_diag_rate_wait_throttle_sec", 5.0) or 5.0))
        last = self.last_wait_diag_by_group.get(group, 0.0)
        if now - last >= throttle:
            self.last_wait_diag_by_group[group] = now
            diag(
                "rd_endpoint_pace_wait",
                group=group,
                why=why,
                wait_sec=round(wait_sec, 3),
                method=str(method or "").upper(),
                path=_rd_path_group(path),
                waits_total=int(self.waits_by_group[group]),
                wait_seconds_total=round(float(self.wait_seconds_by_group[group]), 3),
            )

    def acquire(self, method, path):
        if not self.enabled:
            return ""
        method = str(method or "").upper()
        group = _rd_endpoint_group(method, path)
        with self.lock:
            while True:
                cancel_checkpoint("rd_endpoint_pacer")
                now = time.monotonic()
                self._maybe_recover_locked(group, now)
                st = self.state[group]
                waits = []
                reasons = []
                if now < st["cooldown_until"]:
                    waits.append(st["cooldown_until"] - now)
                    reasons.append("429_group_cooldown")
                if int(st["inflight"]) >= int(st["max_concurrent"]):
                    waits.append(0.05)
                    reasons.append("max_concurrent")
                if now < st["next_allowed_at"]:
                    waits.append(st["next_allowed_at"] - now)
                    reasons.append("min_interval")
                if not waits:
                    st["inflight"] = int(st["inflight"]) + 1
                    self.max_concurrent_by_group[group] = max(int(self.max_concurrent_by_group[group]), int(st["inflight"]))
                    st["next_allowed_at"] = max(float(st["next_allowed_at"]), now) + float(st["min_interval"])
                    self.calls_by_group[group] += 1
                    return group
                wait_sec = max(0.01, min(waits))
                self._record_wait_locked(group, wait_sec, method, path, ",".join(reasons))
                self.lock.wait(timeout=min(wait_sec, 1.0))
                cancel_checkpoint("rd_endpoint_pacer.wait")

    def release(self, group):
        if not self.enabled or not group:
            return
        with self.lock:
            if group in self.state:
                self.state[group]["inflight"] = max(0, int(self.state[group]["inflight"]) - 1)
            self.lock.notify_all()

    def notify_429(self, err):
        if not self.enabled:
            return False
        method = getattr(err, "method", "")
        path = getattr(err, "path", "")
        group = _rd_endpoint_group(method, path)
        with self.lock:
            now = time.monotonic()
            st = self.state[group]
            self.http_429_by_group[group] += 1
            self.cooldowns_by_group[group] += 1
            st["last_429"] = now
            if self.adaptive:
                multiplier = max(1.0, float(CONFIG.get("rd_endpoint_429_min_interval_multiplier", 1.35) or 1.35))
                max_interval = max(float(st["base_interval"]), float(CONFIG.get("rd_endpoint_429_min_interval_max_sec", 2.50) or 2.50))
                st["min_interval"] = min(max_interval, max(float(st["min_interval"]), float(st["min_interval"]) * multiplier))
            cooldown_sec = max(0.0, float(CONFIG.get("rd_endpoint_429_cooldown_sec", 6.0) or 6.0))
            st["cooldown_until"] = max(float(st["cooldown_until"]), now + cooldown_sec)
            self.recent_429.append((now, group))
            massive = self._massive_429(now)
            diag(
                "rd_endpoint_429_backoff",
                group=group,
                min_interval=round(float(st["min_interval"]), 3),
                cooldown_sec=cooldown_sec,
                massive=bool(massive),
                code=getattr(err, "status_code", 0),
                error_code=getattr(err, "error_code", None),
            )
            self.lock.notify_all()
            return massive

    def summary(self):
        with self.lock:
            return {
                "calls_by_group": dict(self.calls_by_group),
                "waits_by_group": dict(self.waits_by_group),
                "wait_seconds_by_group": {k: round(float(v), 3) for k, v in self.wait_seconds_by_group.items()},
                "max_concurrent_by_group": dict(self.max_concurrent_by_group),
                "429_by_group": dict(self.http_429_by_group),
                "interval_final_by_group": {k: round(float(v["min_interval"]), 3) for k, v in self.state.items()},
                "cooldowns_by_group": dict(self.cooldowns_by_group),
            }


def get_rd_endpoint_pacer():
    global RD_ENDPOINT_PACER, RD_ENDPOINT_PACER_KEY
    if not CONFIG.get("rd_endpoint_pacer_enabled", True):
        return None
    key = (
        bool(CONFIG.get("rd_endpoint_pacer_enabled", True)),
        bool(CONFIG.get("rd_endpoint_adaptive_429_enabled", True)),
        float(CONFIG.get("rd_addmagnet_min_interval_sec", 1.0) or 1.0),
        float(CONFIG.get("rd_selectfiles_min_interval_sec", 0.75) or 0.75),
        float(CONFIG.get("rd_delete_min_interval_sec", 0.65) or 0.65),
        float(CONFIG.get("rd_info_min_interval_sec", 0.10) or 0.10),
        int(CONFIG.get("rd_addmagnet_max_concurrent", 1) or 1),
        int(CONFIG.get("rd_selectfiles_max_concurrent", 1) or 1),
        int(CONFIG.get("rd_delete_max_concurrent", 1) or 1),
        int(CONFIG.get("rd_info_max_concurrent", 4) or 4),
    )
    with RD_RUNTIME_LOCK:
        if RD_ENDPOINT_PACER is None or RD_ENDPOINT_PACER_KEY != key:
            RD_ENDPOINT_PACER = RDEndpointPacer()
            RD_ENDPOINT_PACER_KEY = key
        return RD_ENDPOINT_PACER


def rd_emit_endpoint_pacer_summary(label=""):
    with RD_RUNTIME_LOCK:
        pacer = RD_ENDPOINT_PACER
    if pacer and CONFIG.get("rd_endpoint_pacer_enabled", True):
        diag("rd_endpoint_pacer_summary", label=label, **pacer.summary())


class RDActiveSlotsController:
    def __init__(self, token):
        self.token = token
        self.enabled = bool(CONFIG.get("rd_active_slots_enabled", True))
        self.lock = threading.RLock()
        self.limit = 0
        self.nb = 0
        self.last_refresh = 0.0
        self.inflight_adds = 0
        self.delta_since_refresh = 0
        self.max_inflight_adds = 0

    def refresh(self, force=False):
        if not self.enabled:
            return
        now = time.monotonic()
        refresh_sec = float(CONFIG.get("rd_active_slots_refresh_sec", 2.0) or 2.0)
        with self.lock:
            if not force and self.last_refresh and (now - self.last_refresh) < refresh_sec:
                return
        data = rd_call_with_retry("GET", "/torrents/activeCount", self.token, op_name="activeCount", attempts=3, retry_context=get_rd_runtime())
        with self.lock:
            self.nb = int((data or {}).get("nb") or 0) if isinstance(data, dict) else 0
            self.limit = int((data or {}).get("limit") or 0) if isinstance(data, dict) else 0
            self.last_refresh = time.monotonic()
            self.delta_since_refresh = 0
            free = max(0, self.limit - self.nb) if self.limit else 0
        diag("rd_slots_refresh", nb=self.nb, limit=self.limit, free=free)

    def snapshot(self):
        with self.lock:
            used = self.nb + self.inflight_adds + self.delta_since_refresh
            free = max(0, self.limit - used) if self.limit else 0
            return {
                "nb": self.nb,
                "limit": self.limit,
                "free": free,
                "inflight_adds": self.inflight_adds,
                "delta_since_refresh": self.delta_since_refresh,
                "max_inflight_adds": self.max_inflight_adds,
            }

    def try_reserve_for_add(self):
        if not self.enabled:
            return True
        with self.lock:
            if not self.limit:
                self.inflight_adds += 1
                self.max_inflight_adds = max(self.max_inflight_adds, self.inflight_adds)
                diag("rd_slots_reserve", nb=self.nb, limit=self.limit, free_before=-1, inflight_adds=self.inflight_adds)
                return True
            used = self.nb + self.inflight_adds + self.delta_since_refresh
            free = self.limit - used
            if free > 0:
                self.inflight_adds += 1
                self.max_inflight_adds = max(self.max_inflight_adds, self.inflight_adds)
                diag("rd_slots_reserve", nb=self.nb, limit=self.limit, free_before=free, inflight_adds=self.inflight_adds)
                return True
            diag("rd_slots_wait", nb=self.nb, limit=self.limit, inflight_adds=self.inflight_adds, delta_since_refresh=self.delta_since_refresh)
            return False

    def on_add_success(self):
        if not self.enabled:
            return
        with self.lock:
            self.inflight_adds = max(0, self.inflight_adds - 1)
            self.delta_since_refresh += 1

    def on_add_failure(self):
        if not self.enabled:
            return
        with self.lock:
            self.inflight_adds = max(0, self.inflight_adds - 1)

    def on_release(self):
        if not self.enabled:
            return
        with self.lock:
            if self.delta_since_refresh > 0:
                self.delta_since_refresh -= 1
            snap = self.snapshot()
        diag("rd_slots_release", **snap)


class RDExistingIndex:
    def __init__(self, token):
        self.token = token
        self.lock = threading.RLock()
        self.loaded = False
        self.items = []
        self.by_hash = {}
        self.info_cache = {}
        self.preload_count = 0

    def _add_items(self, items, replace=False):
        if replace:
            self.items = []
            self.by_hash = {}
        for item in items or []:
            if not isinstance(item, dict):
                continue
            self.items.append(item)
            h = str(item.get("hash") or "").lower()
            if h:
                self.by_hash.setdefault(h, []).append(item)

    def preload(self, force=False):
        with self.lock:
            if self.loaded and not force:
                return
            limit = max(10, int(CONFIG.get("rd_existing_torrents_limit", 1000) or 1000))
        data = rd_call_with_retry("GET", f"/torrents?limit={limit}", self.token, op_name="existing_preload", attempts=3, retry_context=get_rd_runtime())
        rows = data if isinstance(data, list) else []
        with self.lock:
            self.preload_count += 1
            self._add_items(rows, replace=True)
            self.loaded = True
            total = len(self.items)
            hashes = len(self.by_hash)
        diag("rd_existing_preload_done", total=total, hashes=hashes, limit=limit, preload_count=self.preload_count)

    def refresh_active_only(self):
        limit = max(10, int(CONFIG.get("rd_existing_active_limit_on_33", 500) or 500))
        data = rd_call_with_retry("GET", f"/torrents?filter=active&limit={limit}", self.token, op_name="existing_active", attempts=3, retry_context=get_rd_runtime())
        rows = data if isinstance(data, list) else []
        with self.lock:
            self._add_items(rows, replace=False)
            total = len(self.items)
            hashes = len(self.by_hash)
        diag("rd_existing_active_refresh", total=total, hashes=hashes, limit=limit, active_rows=len(rows))

    def get_info_cached(self, tid):
        tid = str(tid or "").strip()
        if not tid:
            return {}
        with self.lock:
            if tid in self.info_cache:
                return self.info_cache[tid]
        info = rd_call_with_retry("GET", f"/torrents/info/{tid}", self.token, op_name="existing_info", attempts=3, retry_context=get_rd_runtime())
        with self.lock:
            if CONFIG.get("rd_existing_info_cache_enabled", True):
                self.info_cache[tid] = info
        return info

    def items_for_hash(self, h):
        self.preload()
        with self.lock:
            return list(self.by_hash.get(str(h or "").lower(), []))

    def find_downloaded_by_hash(self, h, terms=None):
        best = None
        for item in self.items_for_hash(h):
            if str(item.get("status") or "") != "downloaded" or not (item.get("links") or []):
                continue
            tid = str(item.get("id") or "")
            if not tid:
                continue
            try:
                info = self.get_info_cached(tid)
            except Exception as e:
                diag("rd_existing_info_error", id=tid, hash=h, error=str(e)[:300])
                continue
            score, path, gb, reason = _rd_existing_info_score(info, terms=terms)
            if score < 0:
                continue
            candidate = (score, item, info, path, gb, reason)
            if best is None or candidate[0] > best[0]:
                best = candidate
        return best

    def find_any_by_hash(self, h):
        for item in self.items_for_hash(h):
            tid = str(item.get("id") or "")
            if not tid:
                continue
            try:
                info = self.get_info_cached(tid)
            except Exception as e:
                diag("rd_existing_info_error", id=tid, hash=h, error=str(e)[:300])
                continue
            return item, info
        return None


@dataclass(order=True)
class RDVerifyTask:
    next_at: float
    seq: int
    candidate: object = field(compare=False)
    stage: str = field(default="PRECHECK_EXISTING", compare=False)
    tid: str = field(default="", compare=False)
    selected_once: bool = field(default=False, compare=False)
    poll_count: int = field(default=0, compare=False)
    temp_retries: int = field(default=0, compare=False)
    slot_reserved: bool = field(default=False, compare=False)


@dataclass
class RDTaskResult:
    task: RDVerifyTask
    done: bool = False


@dataclass
class RDVerifyBatchContext:
    token: str
    batch: list
    slots: RDActiveSlotsController
    existing: RDExistingIndex
    terms: list
    started: float = field(default_factory=time.monotonic)
    lock: object = field(default_factory=threading.RLock)
    temp_ids: set = field(default_factory=set)
    temp_meta: dict = field(default_factory=dict)
    ok_ids: set = field(default_factory=set)
    existing_ids: set = field(default_factory=set)
    failed_ids: set = field(default_factory=set)
    cleanup_pending: dict = field(default_factory=dict)
    cleanup_deleted: set = field(default_factory=set)
    cleanup_missing: set = field(default_factory=set)
    cleanup_leftover: set = field(default_factory=set)
    cleanup_released_ids: set = field(default_factory=set)
    rd_retry_429_count: int = 0
    rd_retry_temp_count: int = 0
    rd_retry_21_count: int = 0
    rd_retry_33_count: int = 0
    rd_error_terminal_count: int = 0
    delete_retries: int = 0

    def bump(self, name, amount=1):
        with self.lock:
            setattr(self, name, int(getattr(self, name, 0) or 0) + int(amount or 0))

    def record_temp(self, tid, reason="", result=None):
        tid = str(tid or "").strip()
        if not tid:
            return
        with self.lock:
            self.temp_ids.add(tid)
            meta = self.temp_meta.setdefault(tid, {})
            if reason:
                meta["reason"] = reason
            if result is not None:
                meta["title"] = getattr(result, "title", "")[:180]
                meta["hash"] = getattr(result, "hash", "")

    def record_ok(self, tid):
        tid = str(tid or "").strip()
        if tid:
            with self.lock:
                self.ok_ids.add(tid)
                self.cleanup_pending.pop(tid, None)

    def record_existing(self, tid):
        tid = str(tid or "").strip()
        if tid:
            with self.lock:
                self.existing_ids.add(tid)

    def record_failed(self, tid, why=""):
        tid = str(tid or "").strip()
        if tid:
            with self.lock:
                if tid not in self.ok_ids and tid not in self.existing_ids:
                    self.failed_ids.add(tid)
                    self.cleanup_pending.setdefault(tid, {"why": why or "failed", "release_slot": True})

    def record_cleanup_pending(self, tid, why="", release_slot=False):
        tid = str(tid or "").strip()
        if tid:
            with self.lock:
                if tid not in self.ok_ids and tid not in self.existing_ids:
                    self.cleanup_pending[tid] = {"why": why or "delete_failed", "release_slot": bool(release_slot)}

    def record_cleanup_done(self, tid, state="deleted"):
        tid = str(tid or "").strip()
        if not tid:
            return
        with self.lock:
            self.cleanup_pending.pop(tid, None)
            if state == "missing":
                self.cleanup_missing.add(tid)
            else:
                self.cleanup_deleted.add(tid)
            self.cleanup_leftover.discard(tid)

    def mark_released(self, tid):
        tid = str(tid or "").strip()
        if tid:
            with self.lock:
                if tid in self.cleanup_released_ids:
                    return False
                self.cleanup_released_ids.add(tid)
                return True
        return False

    def snapshot(self):
        with self.lock:
            return {
                "temp_ids": len(self.temp_ids),
                "ok_ids": len(self.ok_ids),
                "existing_ids": len(self.existing_ids),
                "failed_ids": len(self.failed_ids),
                "cleanup_pending": len(self.cleanup_pending),
                "cleanup_deleted": len(self.cleanup_deleted),
                "cleanup_missing": len(self.cleanup_missing),
                "cleanup_leftover": len(self.cleanup_leftover),
                "rd_retry_429_count": self.rd_retry_429_count,
                "rd_retry_temp_count": self.rd_retry_temp_count,
                "rd_retry_21_count": self.rd_retry_21_count,
                "rd_retry_33_count": self.rd_retry_33_count,
                "rd_error_terminal_count": self.rd_error_terminal_count,
                "delete_retries": self.delete_retries,
            }


def set_rd_runtime(ctx):
    global RD_RUNTIME
    with RD_RUNTIME_LOCK:
        RD_RUNTIME = ctx


def get_rd_runtime():
    with RD_RUNTIME_LOCK:
        return RD_RUNTIME


def clear_rd_runtime():
    global RD_RUNTIME
    with RD_RUNTIME_LOCK:
        RD_RUNTIME = None


def save_config():
    try:
        ordered = DEFAULT_CONFIG.copy()
        ordered.update(CONFIG)
        CONFIG_FILE.write_text(json.dumps(ordered, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        log(f"save_config error: {e}")
        return False

def log(msg):
    if not LEGACY_MOTOR_LOGS:
        return
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    try:
        with (LOG_DIR / "legacy_motor.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        with RUN_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def _bb_clean(value):
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:40]:
            key = str(k)
            low = key.lower()
            if any(x in low for x in ("token", "pass", "password", "authorization", "auth", "apikey", "api_key")):
                out[key] = "***"
            elif any(x in low for x in ("magnet", "link", "url", "unrestricted", "download_url")):
                if isinstance(v, str) and v.strip():
                    out[key] = "***"
                elif isinstance(v, (list, tuple, set)):
                    out[key] = ["***" for _ in list(v)[:40]]
                else:
                    out[key] = _bb_clean(v)
            else:
                out[key] = _bb_clean(v)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_bb_clean(v) for v in list(value)[:40]]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 600:
            return value[:600] + "...[truncated]"
        return value
    return str(value)[:600]

def _bb_phase(event):
    lower = str(event or "").lower()
    if lower.startswith(("qbt", "qbit")) or "qbittorrent" in lower:
        return "qbittorrent"
    if lower.startswith("rdt") or "rdt" in lower:
        return "rdt-client"
    if lower.startswith("rd") or "real_debrid" in lower or "real-debrid" in lower:
        return "real-debrid"
    if lower.startswith(("btdigg", "browser", "dom", "extract")):
        return "btdigg"
    if lower.startswith(("export", "history", "editor")):
        return "search"
    return "motor"

def _bb_problem_counter_total(data):
    total = 0.0
    if not isinstance(data, dict):
        return total
    for key, value in data.items():
        key_text = str(key).lower()
        if not any(marker in key_text for marker in ("error", "fail", "api_off", "temporal")):
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            total += float(value)
            continue
        if isinstance(value, str):
            try:
                total += float(value.replace(",", "."))
            except ValueError:
                pass
    return total

def _bb_event_is_ok(event):
    lower = str(event or "").lower()
    return lower.endswith(("_ok", "_done", "_registered", "_selected", "_resolved")) or lower in {
        "job_finished_ok",
        "download_end_ok",
    }

def _bb_http_code(data):
    if not isinstance(data, dict):
        return None
    value = data.get("code") or data.get("status_code")
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None

def _bb_expected_rd_problem(event, data):
    lower_event = str(event or "").lower()
    try:
        text = json.dumps(data or {}, ensure_ascii=False, default=str).lower()
    except Exception:
        text = str(data or "").lower()
    code = _bb_http_code(data)
    if "disabled_endpoint" in text and lower_event in {"rd_api_http_error", "rd_cache_api_disabled"}:
        return True
    if code == 404 and lower_event == "rd_api_http_error" and ("unknown_ressource" in text or "unknown_resource" in text):
        return True
    if code in (429, 451) and lower_event.startswith("rd"):
        return True
    if lower_event == "rd_verify_error" and ("http 451" in text or "infringing_file" in text):
        return True
    if lower_event == "rd_delete_torrent_error" and ("unknown_ressource" in text or "unknown_resource" in text):
        return True
    return False

def _bb_http_level(event, data):
    code = _bb_http_code(data)
    if code is None:
        return None
    if _bb_expected_rd_problem(event, data):
        return "info"
    if code >= 500:
        return "error"
    if code >= 400:
        return "warn"
    return None

def _bb_has_explicit_error_value(data):
    if not isinstance(data, dict):
        return False
    value = data.get("error")
    if value is None or value is False:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True

def _bb_real_rd_error_counter_total(data):
    if not isinstance(data, dict):
        return 0
    keys = ("RD_ERROR", "RD_ERROR_TEMPORAL", "RD_API_OFF", "SIN_HASH", "TORRENT_NO_VALIDO")
    total = 0
    for key in keys:
        try:
            total += int(float(data.get(key) or 0))
        except Exception:
            pass
    return total

def _bb_level(event, data):
    lower_event = str(event or "").lower()
    if _bb_event_is_ok(event):
        return "info"
    if lower_event.endswith("_errors") and str((data or {}).get("total", "")).strip() in {"0", "0.0"}:
        return "info"
    if lower_event in {"rd_call_retry_429", "rd_rate_429_cooldown"}:
        return "info"
    if lower_event.startswith("rd_cache_api_disabled"):
        return "info"
    if lower_event in {
        "rd_call_terminal_error",
        "rd_verify_infringing",
    } and _bb_expected_rd_problem(event, data):
        return "info"
    if "skipped" in lower_event and str((data or {}).get("reason", "")).lower() in {"disabled", "solo_enlaces_directos"}:
        return "info"
    if lower_event in {"rd_verify_batch_end", "rd_check_summary"}:
        return "warn" if _bb_real_rd_error_counter_total(data) > 0 else "info"
    level = _bb_http_level(event, data)
    if level:
        return level
    if any(word in lower_event for word in ("fatal", "traceback", "exception")):
        return "error"
    if any(word in lower_event for word in ("error", "fail", "failed")):
        return "warn" if _bb_expected_rd_problem(event, data) else "error"
    if any(word in lower_event for word in ("poll", "wait", "heartbeat", "tick")):
        return "debug"
    if any(word in lower_event for word in ("warn", "retry", "rejected", "pending", "timeout")):
        return "warn"
    if isinstance(data, dict) and (data.get("ok") is False or _bb_has_explicit_error_value(data)):
        return "warn"
    return "info"

def _bb_code(event, data, level):
    if level not in ("warn", "error"):
        return None
    category = _bb_phase(event).upper().replace("-", "_")
    value = None
    if isinstance(data, dict):
        value = data.get("code") or data.get("status") or data.get("status_code")
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        return f"{category}.HTTP_{value}"
    clean_event = re.sub(r"[^A-Z0-9]+", "_", str(event or "").upper()).strip("_")
    return f"{category}.{clean_event or 'EVENT'}"

BLACKBOX_SEQ = None

def _blackbox_next_seq(events_file):
    global BLACKBOX_SEQ
    if BLACKBOX_SEQ is None:
        try:
            BLACKBOX_SEQ = sum(1 for line in events_file.read_text(encoding="utf-8").splitlines() if line.strip())
        except Exception:
            BLACKBOX_SEQ = 0
    BLACKBOX_SEQ += 1
    return BLACKBOX_SEQ

def _blackbox_diag(event, data):
    events_path = os.environ.get("BTDIGG_BLACKBOX_EVENTS")
    if not events_path:
        return
    try:
        events_file = Path(events_path)
        events_file.parent.mkdir(parents=True, exist_ok=True)
        clean_data = _bb_clean(data or {})
        level = _bb_level(event, clean_data)
        phase = _bb_phase(event)
        seq = _blackbox_next_seq(events_file)
        trace_kind = os.environ.get("BTDIGG_BLACKBOX_KIND", "job")
        trace_id = os.environ.get("BTDIGG_BLACKBOX_TRACE_ID") or os.environ.get("BTDIGG_BLACKBOX_JOB_ID", "")
        ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        record = {
            "ts": ts,
            "observed_ts": ts,
            "event_id": f"M{seq:06d}",
            "seq": seq,
            "trace_kind": trace_kind,
            "trace_id": trace_id,
            "source": "motor",
            "kind": "rd_test" if trace_kind == "rd_test" else "search",
            "job_id": os.environ.get("BTDIGG_BLACKBOX_JOB_ID", ""),
            "event": event,
            "level": level,
            "phase": phase,
            "code": _bb_code(event, clean_data, level),
            "data": clean_data,
        }
        with events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        if level == "warn":
            with events_file.with_name("warnings.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        elif level == "error":
            with events_file.with_name("errors.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        detail = clean_data.get("message") or clean_data.get("error") or clean_data.get("reason") or clean_data.get("title") or ""
        detail = f" - {detail}" if detail else ""
        with events_file.with_name("timeline.md").open("a", encoding="utf-8") as f:
            f.write(f"- {record['ts']} [{level}] {phase}::{event}{detail}\n")
        summary_file = events_file.with_name("summary.json")
        try:
            summary = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file.exists() else {}
        except Exception:
            summary = {}
        counts = summary.setdefault("counts", {"info": 0, "warn": 0, "error": 0, "debug": 0})
        counts[level] = int(counts.get(level, 0)) + 1
        summary["updated_at"] = record["ts"]
        summary["last_motor_event"] = event
        if level == "error":
            summary["status"] = "error"
        elif level == "warn" and summary.get("status") == "running":
            summary["status"] = "warning"
        summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    except Exception:
        pass

def diag(event, **data):
    with DIAG_LOCK:
        item = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event}
        item.update(data)
        DIAG_EVENTS.append(item)
        _blackbox_diag(event, data)
    if LEGACY_MOTOR_LOGS:
        try:
            lines = []
            lines.append("RD Turbo Pro - último diagnóstico")
            lines.append("=" * 70)
            lines.append(f"Carpeta: {APP_DIR}")
            lines.append(f"Log run: {RUN_LOG_FILE}")
            lines.append("")
            for x in DIAG_EVENTS[-300:]:
                lines.append(json.dumps(x, ensure_ascii=False))
            DIAG_FILE.write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            pass
        if event.startswith(("authorized_", "torrent_probe", "torznab")):
            try:
                with STEP2_DIAG_FILE.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            except Exception:
                pass
    log(f"DIAG {event}: {data}")

def reset_step2_diag():
    if not LEGACY_MOTOR_LOGS:
        return
    try:
        STEP2_DIAG_FILE.write_text("", encoding="utf-8")
    except Exception:
        pass

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def pause():
    try:
        input("\nPulsa ENTER para seguir...")
    except EOFError:
        pass

def banner():
    print("=" * 72)
    print(" RD TURBO PRO v2.4  |  BTDigg + Real-Debrid + JDownloader")
    print("=" * 72)

def read_token():
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text("PON_AQUI_TU_TOKEN_REAL_DEBRID", encoding="utf-8")
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token or token.startswith("PON_AQUI"):
        return ""
    return token

def http_get_text(url, timeout=None):
    timeout = timeout or int(CONFIG.get("request_timeout_sec", 20))
    started = time.time()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = getattr(resp, "status", 200)
        elapsed = round(time.time() - started, 2)
        diag("http_ok", url=url, status=status, bytes=len(raw), seconds=elapsed)
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="ignore")[:500]
        except Exception:
            body = ""
        elapsed = round(time.time() - started, 2)
        diag("http_error", url=url, status=e.code, reason=str(e.reason), body=body, seconds=elapsed)
        raise
    except Exception as e:
        elapsed = round(time.time() - started, 2)
        diag("http_exception", url=url, error=repr(e), seconds=elapsed)
        raise
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="ignore")

def rd_api(method, path, token, data=None, raw=None, content_type=None):
    cancel_checkpoint(f"rd_api.before:{path}")
    pacer = get_rd_endpoint_pacer()
    pacer_group = ""
    if pacer:
        pacer_group = pacer.acquire(method, path)
    limiter = get_rd_rate_limiter()
    if limiter:
        limiter.acquire(method, path)
    base = CONFIG.get("real_debrid_api_base", "https://api.real-debrid.com/rest/1.0").rstrip("/")
    url = base + path
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "RD-Turbo-Pro/1.0",
    }
    body = None
    if raw is not None:
        body = raw
        if content_type:
            headers["Content-Type"] = content_type
    elif data is not None:
        from urllib.parse import urlencode
        body = urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urlopen(req, timeout=int(CONFIG.get("request_timeout_sec", 20))) as resp:
            raw_resp = resp.read()
            cancel_checkpoint(f"rd_api.after:{path}")
            if not raw_resp:
                return None
            text = raw_resp.decode("utf-8", errors="ignore")
            try:
                return json.loads(text)
            except Exception:
                return text
    except HTTPError as e:
        text = e.read().decode("utf-8", errors="ignore")
        payload = None
        try:
            payload = json.loads(text)
        except Exception:
            payload = None
        err = RDAPIError(method.upper(), path, e.code, text[:500], payload=payload)
        diag(
            "rd_api_http_error",
            method=method.upper(),
            path=path,
            code=e.code,
            error=getattr(err, "error", ""),
            error_code=getattr(err, "error_code", None),
            body=text[:500],
        )
        if limiter and err.is_429:
            massive = pacer.notify_429(err) if pacer else False
            cooldown_key = "rd_mass_429_cooldown_sec" if massive else "rd_api_429_cooldown_sec"
            cooldown_default = 10.0 if massive else 3.0
            limiter.notify_429(err, cooldown_override=CONFIG.get(cooldown_key, cooldown_default))
        raise err
    except URLError as e:
        msg = f"Real-Debrid conexión: {e}"
        diag("rd_api_url_error", method=method.upper(), path=path, error=str(e))
        raise RuntimeError(msg)
    finally:
        if pacer:
            pacer.release(pacer_group)


def _is_rd_temp_error_msg(msg):
    if isinstance(msg, RDAPIError):
        return msg.is_temp
    text = normalize(str(msg or ""))
    needles = [
        "error 503",
        "http 503",
        "service unavailable",
        "temporarily unavailable",
        "timed out",
        "timeout",
        "read operation timed out",
        "connection reset",
        "connection aborted",
        "too many requests",
        "http 429",
        "bad gateway",
        "http 502",
        "gateway timeout",
        "http 504",
        "cloudflare",
    ]
    return any(n in text for n in needles)

def _mark_rd_temp_error(r, msg, idx=0, total=0, tid=""):
    r.rd_status = "RD_ERROR_TEMPORAL"
    r.reason = "Real-Debrid fallo temporalmente al verificar: " + str(msg)[:420]
    diag("rd_verify_temp_error", n=idx, total=total, id=tid, hash=r.hash, error=str(msg)[:500], title=r.title[:160])
    return r

def _rd_retry_sleep(attempt, base_sec=None, max_sec=None):
    base = float(base_sec if base_sec is not None else CONFIG.get("rd_temp_error_retry_sec", 1.0) or 1.0)
    max_wait = float(max_sec if max_sec is not None else max(base, 4.0))
    wait_sec = min(max_wait, max(0.05, base * (1.5 ** max(0, int(attempt or 1) - 1))))
    sleep_interruptible(wait_sec, where="rd_retry_sleep")
    return wait_sec


def rd_call_with_retry(
    method,
    path,
    token,
    data=None,
    raw=None,
    content_type=None,
    op_name="",
    attempts=None,
    retry_context=None,
    base_sec=None,
    max_sec=None,
    retry_429_attempts=None,
):
    return rd_call_with_retry_impl(
        method,
        path,
        token,
        data=data,
        raw=raw,
        content_type=content_type,
        op_name=op_name,
        attempts=attempts,
        retry_context=retry_context,
        base_sec=base_sec,
        max_sec=max_sec,
        retry_429_attempts=retry_429_attempts,
        config=CONFIG,
        rd_api=rd_api,
        rd_api_error_cls=RDAPIError,
        rd_retry_sleep=_rd_retry_sleep,
        diag=diag,
        sleep_interruptible=sleep_interruptible,
        is_rd_temp_error_msg=_is_rd_temp_error_msg,
        rd_path_group=_rd_path_group,
    )

def qbt_request(opener, method, path, data=None, timeout=None):
    base = str(CONFIG.get("qbit_host", "")).rstrip("/")
    if not base:
        raise RuntimeError("qBittorrent host vacío en config.json")
    url = base + path
    body = None
    headers = {"User-Agent": "RD-Turbo-Pro/2.4"}
    if data is not None:
        body = urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = Request(url, data=body, headers=headers, method=method.upper())
    with opener.open(req, timeout=timeout or int(CONFIG.get("request_timeout_sec", 20))) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", errors="ignore")
    try:
        return json.loads(text)
    except Exception:
        return text

def qbt_login():
    if not CONFIG.get("qbit_probe_enabled", True):
        return None
    cj = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(cj))
    user = str(CONFIG.get("qbit_user", "admin"))
    password = str(CONFIG.get("qbit_pass", "CAMBIAR_EN_ENTORNO_REAL"))
    try:
        resp = qbt_request(opener, "POST", "/api/v2/auth/login", {"username": user, "password": password}, timeout=12)
        response_text = str(resp).strip()
        ok = response_text in ("Ok.", "Ok", "")
        version = ""
        if ok:
            try:
                version = str(qbt_request(opener, "GET", "/api/v2/app/version", timeout=12)).strip()
                ok = bool(version)
            except Exception as e:
                ok = False
                diag("qbt_login_verify_error", host=str(CONFIG.get("qbit_host", "")), error=str(e)[:300])
        diag("qbt_login", ok=ok, host=str(CONFIG.get("qbit_host", "")), response=response_text[:80], version=version[:40])
        return opener if ok else None
    except Exception as e:
        diag("qbt_login_error", host=str(CONFIG.get("qbit_host", "")), error=str(e)[:300])
        return None

def qbt_info_by_hash(opener, h):
    h = (h or "").lower()
    if not h:
        return None
    try:
        data = qbt_request(opener, "GET", f"/api/v2/torrents/info?hashes={quote(h)}", timeout=12)
        if isinstance(data, list) and data:
            return data[0]
    except Exception as e:
        diag("qbt_info_error", hash=h, error=str(e)[:300])
    return None

def _safe_int(v, default=0):
    try:
        if v is None:
            return default
        return int(float(v))
    except Exception:
        return default

def _result_display_name(r):
    for value in (
        getattr(r, "selected_file_name", ""),
        getattr(r, "btdigg_file_name", ""),
        getattr(r, "title", ""),
    ):
        value = str(value or "").strip()
        if value:
            return value.lstrip("/")
    return ""

def qbt_eval_info(info):
    if not isinstance(info, dict):
        return "QBT_NO_INFO", "Sin info en qBittorrent"
    progress = float(info.get("progress") or 0)
    dlspeed = _safe_int(info.get("dlspeed"), 0)
    seeds = max(0, _safe_int(info.get("num_seeds"), 0))
    peers = max(0, _safe_int(info.get("num_leechs"), 0))
    complete = max(0, _safe_int(info.get("num_complete"), 0))
    availability = float(info.get("availability") or 0)
    state = str(info.get("state") or "").lower()
    size = _safe_int(info.get("size"), 0)
    amount_left = _safe_int(info.get("amount_left"), 0)
    has_metadata = size > 0
    if progress >= 0.999 or (size > 0 and amount_left == 0):
        return "QBT_OK", f"qBittorrent completado/listo: progress={progress:.3f}, size={size/(1024**3):.2f}GB"
    if dlspeed > 0:
        return "QBT_VIVO", f"qBittorrent descargando: {dlspeed/1024/1024:.2f} MB/s, seeds={seeds}, peers={peers}"
    if seeds > 0:
        return "QBT_VIVO", f"qBittorrent con seed conectado: seeds={seeds}, peers={peers}, state={state}"
    if has_metadata and availability >= 1.0:
        return "QBT_VIVO", f"qBittorrent con vida: seeds={seeds}, complete={complete}, availability={availability:.2f}, state={state}"
    if has_metadata and progress > 0:
        return "QBT_VIVO", f"qBittorrent ya tiene progreso real: progress={progress:.3f}, availability={availability:.2f}, state={state}"
    if complete > 0:
        return "QBT_TRACKER_HINT", f"Tracker indica posibles seeds ({complete}), pero qBittorrent no conecto ni obtuvo vida real: state={state}, seeds={seeds}, peers={peers}, availability={availability:.2f}"
    if size > 0 and state in ("downloading", "stalleddl", "queueddl", "metadl", "forceddl"):
        return "QBT_METADATA", f"qBittorrent tiene metadatos pero sin vida clara: state={state}, seeds={seeds}, peers={peers}"
    return "QBT_NO_PEERS", f"Sin vida clara en qBittorrent: state={state}, seeds={seeds}, peers={peers}, progress={progress:.3f}"

def qbt_delete_hash(opener, h, why="probe"):
    try:
        qbt_request(opener, "POST", "/api/v2/torrents/delete", {"hashes": h, "deleteFiles": "true"}, timeout=12)
        diag("qbt_delete_probe", hash=h, why=why)
    except Exception as e:
        diag("qbt_delete_error", hash=h, why=why, error=str(e)[:300])

def qbt_probe_one(opener, r, idx=0, total=0):
    return qbt_probe_one_impl(
        opener,
        r,
        idx=idx,
        total=total,
        config=CONFIG,
        magnet_hash=magnet_hash,
        qbt_info_by_hash=qbt_info_by_hash,
        qbt_eval_info=qbt_eval_info,
        qbt_request=qbt_request,
        qbt_delete_hash=qbt_delete_hash,
        result_display_name=_result_display_name,
        safe_int=_safe_int,
        diag=diag,
        cancel_checkpoint=cancel_checkpoint,
        sleep_interruptible=sleep_interruptible,
        user_cancelled_cls=UserCancelled,
        non_cancelable_cleanup=non_cancelable_cleanup,
        time_module=time,
    )

def _is_qbt_working_status(status):
    if status in ("QBT_OK", "QBT_VIVO"):
        return True
    return bool(CONFIG.get("qbit_show_metadata_only", False) and status == "QBT_METADATA")

def _qbt_candidate_relevant(r):
    if not CONFIG.get("qbit_require_same_file_match", True):
        return True
    if _is_working_status(r.rd_status):
        return True
    ok, fname, fgb, why = _same_file_match_for_result(r.title, _match_context_for_result(r))
    if ok:
        r.same_file_match = True
        r.same_file_reason = why
        if fname and fname != r.title and not r.btdigg_file_name:
            r.btdigg_file_name = fname
            r.btdigg_file_size_gb = fgb or 0.0
        return True
    r.same_file_match = False
    r.same_file_reason = why
    r.qbt_status = "QBT_NO_COINCIDE_ARCHIVO"
    r.qbt_reason = "Descartado para qBittorrent: la búsqueda no aparece en un mismo archivo/título. " + why
    return False

def _qbt_probe_one_fresh(r, idx, total):
    opener = qbt_login()
    if not opener:
        r.qbt_status = "QBT_OFF"
        r.qbt_reason = "No pude conectar/login con qBittorrent"
        return r
    return qbt_probe_one(opener, r, idx, total)

def qbt_probe_candidates(results):
    cancel_checkpoint("qbt_probe_candidates.before")
    if not CONFIG.get("qbit_probe_enabled", True):
        diag("qbt_probe_skipped", reason="disabled")
        return results
    candidates = [r for r in results if r.magnet]
    if CONFIG.get("qbit_probe_only_non_rd_working", True):
        candidates = [r for r in results if not _is_working_status(r.rd_status)]
    relevant = []
    skipped = 0
    for r in candidates:
        if _qbt_candidate_relevant(r):
            relevant.append(r)
        else:
            skipped += 1
    diag("qbt_relevance_filter", before=len(candidates), after=len(relevant), skipped=skipped)
    candidates = relevant[:int(CONFIG.get("qbit_probe_max_candidates", 15) or 15)]
    if not candidates:
        diag("qbt_probe_skipped", reason="no_candidates_after_relevance")
        return results
    workers = max(1, int(CONFIG.get("qbit_probe_parallel_workers", 1) or 1))
    workers = min(workers, len(candidates))
    wait_sec = int(float(CONFIG.get("qbit_probe_wait_sec", 25) or 25))
    total_candidates = len(candidates)
    progress_step = max(2, total_candidates // 5 or 1)
    vivos = 0
    print(f"\nqBit: probando {total_candidates} candidatos extra ({workers} a la vez, {wait_sec}s máximo).", flush=True)
    diag("qbt_probe_batch_start", total=len(results), probing=len(candidates), workers=workers)
    if workers <= 1:
        opener = qbt_login()
        if not opener:
            print("\nAviso: no puedo entrar a qBittorrent para la lista extra.")
            for r in candidates:
                r.qbt_status = "QBT_OFF"
                r.qbt_reason = "No pude conectar/login con qBittorrent"
            return results
        for i, r in enumerate(candidates, 1):
            cancel_checkpoint("qbt_probe_candidates.item")
            qbt_probe_one(opener, r, i, len(candidates))
            if _is_qbt_working_status(r.qbt_status):
                vivos += 1
                print(f"qBit vivo {i}/{total_candidates}: {r.qbt_status} - {_result_display_name(r)[:100]}", flush=True)
            elif i % progress_step == 0 or i == total_candidates:
                print(f"qBit progreso: {i}/{total_candidates} comprobados | vivos {vivos}", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_qbt_probe_one_fresh, r, i, len(candidates)): (i, r) for i, r in enumerate(candidates, 1)}
            done = 0
            for fut in as_completed(futs):
                cancel_checkpoint("qbt_probe_candidates.worker")
                i, r = futs[fut]
                done += 1
                try:
                    fut.result()
                    if _is_qbt_working_status(r.qbt_status):
                        vivos += 1
                        print(f"qBit vivo {done}/{total_candidates}: {r.qbt_status} - {_result_display_name(r)[:100]}", flush=True)
                    elif done % progress_step == 0 or done == total_candidates:
                        print(f"qBit progreso: {done}/{total_candidates} comprobados | vivos {vivos}", flush=True)
                except Exception as e:
                    r.qbt_status = "QBT_ERROR"
                    r.qbt_reason = str(e)[:500]
                    diag("qbt_probe_worker_error", n=i, title=r.title[:120], error=str(e)[:400])
                    print(f"  qBit error worker {i}/{len(candidates)}: {str(e)[:120]}", flush=True)
    summary = {}
    for r in results:
        if r.qbt_status:
            summary[r.qbt_status] = summary.get(r.qbt_status, 0) + 1
    vivos_finales = sum(1 for r in results if _is_qbt_working_status(r.qbt_status) and not _is_working_status(r.rd_status))
    diag("qbt_probe_batch_end", **summary, total=len(results), vivos_reales=vivos_finales)
    return results

@dataclass
class Result:
    title: str
    magnet: str = ""
    torrent_url: str = ""
    hash: str = ""
    size_gb: float = 0.0
    source_url: str = ""
    btdigg_file_name: str = ""
    btdigg_file_size_gb: float = 0.0
    same_file_match: bool = False
    same_file_reason: str = ""
    score: int = 0
    rd_status: str = "SIN_COMPROBAR"
    rd_files: int = 0
    rd_largest_gb: float = 0.0
    rd_torrent_id: str = ""
    rd_existing: bool = False
    rd_links: int = 0
    selected_file_ids: str = ""
    selected_file_name: str = ""
    selected_file_size_gb: float = 0.0
    is_pack: bool = False
    pack_note: str = ""
    qbt_status: str = ""
    qbt_reason: str = ""
    qbt_seeds: int = 0
    qbt_peers: int = 0
    qbt_progress: float = 0.0
    qbt_speed_bps: int = 0
    qbt_size_gb: float = 0.0
    qbt_was_existing: bool = False
    tracker_name: str = ""
    tracker_seeders: int = 0
    tracker_leechers: int = 0
    tracker_category: str = ""
    raw_context: str = ""
    prefilter_bucket: str = ""
    prefilter_reason: str = ""
    reason: str = ""

def strip_html(s):
    s = re.sub(r"<script.*?</script>", " ", s, flags=re.I | re.S)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def extract_magnets_from_text(text, source_url=""):
    """
    Extrae magnets de texto normal y de HTML copiado desde navegador.
    Truco importante: al hacer CTRL+A / CTRL+C en una web, el texto visible puede
    recortar el magnet, pero el portapapeles HTML suele guardar el href completo.
    """
    original = text or ""
    text = html.unescape(original)
    # También probamos versión URL-decodificada por si el magnet viene como magnet%3A...
    decoded = unquote(text)
    scan_blob = text + "\n" + decoded

    candidates = []

    # Magnet normal dentro de texto/HTML/href
    for m in re.finditer(r"magnet:\?xt=urn:btih:[^\s\"'<>]+", scan_blob, flags=re.I):
        candidates.append((m.group(0), m.start(), m.end()))

    # Magnet URL encoded: magnet%3A%3Fxt%3Durn%3Abtih%3A...
    for m in re.finditer(r"magnet%3A%3Fxt%3Durn%3Abtih%3A[^\s\"'<>]+", original, flags=re.I):
        candidates.append((unquote(m.group(0)), m.start(), m.end()))

    magnets = []
    for magnet, pos_start, pos_end in candidates:
        magnet = html.unescape(magnet).strip().replace("&amp;", "&")
        # Cortes defensivos por si arrastra basura al final
        magnet = re.split(r"[\s\"'<>]", magnet, maxsplit=1)[0]
        h = magnet_hash(magnet)
        if not h:
            continue
        start = max(0, pos_start - 1500)
        end = min(len(scan_blob), pos_end + 800)
        context = strip_html(scan_blob[start:end])
        title = magnet_title(magnet) or guess_title_from_context(context) or h
        size_gb = parse_size_gb(context)
        same_ok, file_name, file_gb, same_reason = _same_file_match_for_result(title, context)
        r = Result(title=title, magnet=magnet, hash=h.lower(), size_gb=size_gb, source_url=source_url, raw_context=context[:4000], reason=context[:900])
        r.same_file_match = bool(same_ok)
        r.same_file_reason = same_reason
        if file_name and file_name != title:
            r.btdigg_file_name = file_name
            r.btdigg_file_size_gb = file_gb or 0.0
        magnets.append(r)

    diag("extract_magnets", source=source_url, magnets=len(magnets), text_chars=len(original))
    return dedupe_results(magnets)


def _btdigg_dump_dom_fallback(url):
    """
    Fallback NAS/Docker: Chromium --dump-dom ve los magnets aunque CDP no los recoja.
    No cambia filtros ni lógica; solo alimenta al extractor con el HTML real.
    """
    browser = os.environ.get("BROWSER_BIN") or str(CONFIG.get("browser_bin") or "/usr/bin/chromium")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    cmd = [
        browser,
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--window-size=1600,1200",
        "--user-agent=" + ua,
        "--dump-dom",
        url,
    ]
    try:
        rc, stdout, _stderr = run_capture_interruptible(
            cmd,
            timeout=int(CONFIG.get("btdigg_dump_dom_timeout_sec", 45) or 45),
            where="btdigg_dump_dom",
        )
        html_text = stdout or ""
        results = extract_magnets_from_text(html_text, source_url=url)
        diag("btdigg_dump_dom_fallback", url=url, magnets=len(results), html_chars=len(html_text), rc=rc)
        if results:
            print(f"  Rescate DOM: {len(results)} magnets encontrados")
        return results
    except Exception as e:
        diag("btdigg_dump_dom_fallback_error", url=url, error=repr(e))
        print(f"  Rescate DOM falló: {e}")
        return []

def extract_urls_from_text(text):
    found = re.findall(r"https?://[^\s\"'<>]+", text, flags=re.I)
    return [u.rstrip(".,);]") for u in found]

def _clean_url(u):
    u = html.unescape(str(u or "")).strip()
    u = u.strip(" \t\r\n\"'<>")
    return u.rstrip(".,);]")

def _direct_exts():
    return [str(x).lower() for x in CONFIG.get("direct_link_extensions", [])]

def _has_direct_extension(url):
    path = unquote(urlparse(url).path).lower()
    return any(path.endswith(ext) for ext in _direct_exts())

def _looks_like_torrent_url(url):
    parsed = urlparse(str(url or ""))
    path = unquote(parsed.path or "").lower()
    query = unquote(parsed.query or "").lower()
    if path.endswith(".torrent"):
        return True
    if any(ext and path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".css", ".js", ".ico")):
        return False
    blob = f"{path}?{query}"
    return bool(
        re.search(r"(^|/)(torrent|torrents|download|downloads|descargar|descarga)(/|$)", path)
        or "torznab" in blob
        or "apikey=" in blob and ("t=download" in blob or "download" in blob)
    )

def _is_direct_candidate_result(r):
    return bool(r.source_url and not r.magnet and not r.torrent_url and not r.hash)

def extract_direct_links_from_html(text, base_url=""):
    """
    Extrae enlaces HTTP(S) que parecen archivos descargables públicos.
    No ejecuta pasos de login ni salta protecciones; solo usa href/src visibles.
    """
    raw = str(text or "")
    links = []
    anchor_links = []
    label_candidates = set()
    for m in re.finditer(r"""<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", raw, flags=re.I | re.S):
        anchor_links.append((m.group(1), strip_html(m.group(2))))
    for href, label in anchor_links:
        u = _clean_url(href)
        if not u or u.startswith(("mailto:", "javascript:", "#")):
            continue
        u = urljoin(base_url, u)
        label_match = bool(label and re.search(r"\b(torrent|descargar|download|freeleech|enlace|link|continuar|continue|saltar|skip)\b|ir\s+al\s+enlace", label, flags=re.I))
        if u.lower().startswith(("http://", "https://")) and (label_match or _looks_like_torrent_url(u)):
            if label_match:
                label_candidates.add(u.split("#", 1)[0])
            links.append(u)
    for m in re.finditer(r"""(?:href|src)\s*=\s*["']([^"']+)["']""", raw, flags=re.I):
        u = _clean_url(m.group(1))
        if not u or u.startswith(("mailto:", "javascript:", "#")):
            continue
        u = urljoin(base_url, u)
        if u.lower().startswith(("http://", "https://")):
            links.append(u)
    links.extend(extract_urls_from_text(raw))

    out = []
    seen = set()
    for u in links:
        u = _clean_url(u)
        key = u.split("#", 1)[0]
        if not key or key in seen:
            continue
        seen.add(key)
        if _has_direct_extension(key) or _looks_like_torrent_url(key) or key in label_candidates:
            title = unquote(Path(urlparse(key).path).name) or key
            if unquote(urlparse(key).path).lower().endswith(".torrent"):
                out.append(Result(title=title, torrent_url=key, source_url=key, rd_status="TORRENT_PENDIENTE"))
            elif _looks_like_torrent_url(key) or key in label_candidates:
                out.append(Result(title=title, torrent_url=key, source_url=key, rd_status="TORRENT_PENDIENTE"))
            else:
                out.append(Result(title=title, source_url=key, rd_status="DIRECT_PENDIENTE"))
    return out[:int(CONFIG.get("direct_link_max_candidates", 80) or 80)]

def normalize_base_url(url):
    url = str(url or "").strip()
    if not url:
        return ""
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"

def build_authorized_search_urls(base_url, query):
    base = normalize_base_url(base_url)
    if not base:
        return []
    q = quote(query)
    paths = CONFIG.get("authorized_site_search_paths", []) or ["?s={query}"]
    urls = []
    seen = set()
    for path in paths:
        u = str(path or "").replace("{query}", q).replace("{query_quote}", q)
        full = urljoin(base, u)
        if full not in seen:
            seen.add(full)
            urls.append(full)
    return urls

def extract_candidate_pages_from_html(text, base_url, query):
    raw = str(text or "")
    terms = terms_from_query_for_match(query)
    if not terms:
        terms = [t for t in re.findall(r"[a-z0-9]{3,}", normalize(query))]
    base_host = urlparse(base_url).netloc.lower()
    candidates = []
    seen = set()
    for m in re.finditer(r"""<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", raw, flags=re.I | re.S):
        href = _clean_url(m.group(1))
        if not href or href.startswith(("mailto:", "javascript:", "#")):
            continue
        full = urljoin(base_url, href).split("#", 1)[0]
        p = urlparse(full)
        if p.scheme not in ("http", "https") or p.netloc.lower() != base_host:
            continue
        if _has_direct_extension(full):
            continue
        label = strip_html(m.group(2))
        blob = normalize(label + " " + full)
        if terms and not any(t in blob for t in terms):
            continue
        if full not in seen:
            seen.add(full)
            candidates.append(full)
    return candidates[:int(CONFIG.get("authorized_site_max_detail_pages", 12) or 12)]

def _xml_text(node, name):
    found = node.find(name)
    return (found.text or "").strip() if found is not None and found.text else ""

def _torznab_attr(item, attr_name):
    for child in list(item):
        tag = child.tag.split("}", 1)[-1].lower()
        if tag != "attr":
            continue
        if str(child.attrib.get("name", "")).lower() == attr_name.lower():
            return str(child.attrib.get("value", "")).strip()
    return ""

def _to_int(v, default=0):
    try:
        return int(float(str(v or "").strip()))
    except Exception:
        return default

def _build_torznab_url(query):
    if not CONFIG.get("torznab_enabled", False):
        return ""
    base = str(CONFIG.get("torznab_url", "") or "").strip()
    key = str(CONFIG.get("torznab_api_key", "") or "").strip()
    if not base:
        return ""
    if "{query}" in base or "{query_quote}" in base:
        return base.replace("{query}", quote(query)).replace("{query_quote}", quote(query))
    params = {"t": "search", "q": query}
    if key:
        params["apikey"] = key
    cats = str(CONFIG.get("torznab_categories", "") or "").strip()
    if cats:
        params["cat"] = cats
    sep = "&" if "?" in base else "?"
    return base + sep + urlencode(params)

def torznab_is_configured():
    return bool(CONFIG.get("torznab_enabled", False) and str(CONFIG.get("torznab_url", "") or "").strip())

def configure_torznab_interactive():
    print("\nPara obtener resultados con seeds como en Jackett, configura Torznab una vez.")
    print("En Jackett puedes usar el botón 'Copy Torznab Feed' del indexador.")
    feed = input("URL Torznab/Jackett (ENTER para saltar): ").strip()
    if not feed:
        return False
    key = input("API key si no viene en la URL (ENTER si ya viene incluida): ").strip()
    cats = input("Categorías opcionales, ej 2000,2040 (ENTER para todas): ").strip()
    min_seeders = input(f"Semillas mínimas [{CONFIG.get('torznab_min_seeders', 1)}]: ").strip()
    CONFIG["torznab_enabled"] = True
    CONFIG["torznab_url"] = feed
    if key:
        CONFIG["torznab_api_key"] = key
    CONFIG["torznab_categories"] = cats
    if min_seeders:
        try:
            CONFIG["torznab_min_seeders"] = max(0, int(min_seeders))
        except Exception:
            pass
    if save_config():
        print("Torznab/Jackett guardado en config.json.")
    else:
        print("No pude guardar config.json, pero lo usaré en esta ejecución.")
    return True

def search_torznab_indexer(query):
    url = _build_torznab_url(query)
    if not url:
        return []
    min_seeders = int(CONFIG.get("torznab_min_seeders", 1) or 0)
    max_results = int(CONFIG.get("torznab_max_results", 30) or 30)
    print("\nBuscando en Torznab/Jackett configurado...")
    try:
        xml_text = http_get_text(url)
        root = ET.fromstring(xml_text)
    except Exception as e:
        diag("torznab_error", error=str(e)[:500])
        print(f"  Torznab/Jackett no respondió bien: {str(e)[:160]}")
        return []

    out = []
    for item in root.findall(".//item"):
        title = _xml_text(item, "title") or "torrent"
        link = _xml_text(item, "link")
        enclosure = item.find("enclosure")
        if enclosure is not None:
            link = enclosure.attrib.get("url") or link
        link = _clean_url(link)
        if not link:
            continue
        seeders = _to_int(_torznab_attr(item, "seeders"), _to_int(_torznab_attr(item, "seed"), 0))
        leechers = _to_int(_torznab_attr(item, "leechers"), _to_int(_torznab_attr(item, "peers"), 0))
        size = _to_int(_torznab_attr(item, "size"), 0)
        if not size and enclosure is not None:
            size = _to_int(enclosure.attrib.get("length"), 0)
        category = _torznab_attr(item, "category") or _xml_text(item, "category")
        tracker = _xml_text(item, "jackettindexer") or _xml_text(item, "tracker") or "Torznab"
        if seeders < min_seeders:
            continue
        r = Result(
            title=title,
            torrent_url=link,
            source_url=link,
            size_gb=(size / (1024 ** 3) if size else 0.0),
            rd_status="TORRENT_PENDIENTE",
            tracker_name=tracker,
            tracker_seeders=seeders,
            tracker_leechers=leechers,
            tracker_category=category,
            reason=f"Torznab: seeds={seeders}, leechers={leechers}, categoria={category or '-'}",
        )
        out.append(r)
        if len(out) >= max_results:
            break
    diag("torznab_results", total=len(out), min_seeders=min_seeders)
    return dedupe_results(out)

def search_authorized_site_for_torrents(base_url, query):
    all_results = []
    torznab_results = search_torznab_indexer(query)
    if torznab_results:
        print(f"\nTorznab/Jackett: {len(torznab_results)} candidatos con semillas suficientes.")
        return dedupe_results(torznab_results)
    searched = []
    for search_url in build_authorized_search_urls(base_url, query):
        try:
            print(f"  Buscando: {search_url}")
            text = http_get_text(search_url)
            searched.append(search_url)
            page_results = extract_direct_links_from_html(text, base_url=search_url)
            all_results.extend(page_results)
            detail_pages = extract_candidate_pages_from_html(text, search_url, query)
            if detail_pages:
                print(f"  Fichas candidatas: {len(detail_pages)}")
            for i, detail_url in enumerate(detail_pages, 1):
                try:
                    print(f"    Ficha {i}/{len(detail_pages)}: {detail_url[:90]}")
                    detail_text = http_get_text(detail_url)
                    all_results.extend(extract_direct_links_from_html(detail_text, base_url=detail_url))
                except Exception as e:
                    diag("authorized_detail_error", url=detail_url, error=str(e)[:300])
            if all_results:
                break
        except Exception as e:
            diag("authorized_search_url_error", url=search_url, error=str(e)[:300])
            continue
    out = dedupe_results(all_results)
    if not out and CONFIG.get("authorized_site_browser_fallback", True):
        try:
            print("\nNo encontré .torrent con rutas comunes. Pruebo navegador automático...")
            out = dedupe_results(search_authorized_site_browser_auto(base_url, query))
        except Exception as e:
            diag("authorized_browser_fallback_error", base=base_url, query=query, error=str(e)[:500])
    diag("authorized_site_search_done", base=base_url, query=query, searched=searched, total=len(out))
    return out

def _content_length_to_gb(value):
    try:
        n = int(value or 0)
    except Exception:
        return 0.0
    return n / (1024 ** 3) if n > 0 else 0.0

def validate_direct_link(r):
    url = r.source_url
    timeout = int(CONFIG.get("direct_link_check_timeout_sec", 12) or 12)
    try:
        min_mb = float(CONFIG.get("direct_link_min_size_mb", 1))
    except Exception:
        min_mb = 1.0
    headers = {
        "User-Agent": "RD-Turbo-Pro/2.4",
        "Accept": "*/*",
    }
    try:
        req = Request(url, headers=headers, method="HEAD")
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            ctype = resp.headers.get("Content-Type", "")
            clen = resp.headers.get("Content-Length", "")
            dispo = resp.headers.get("Content-Disposition", "")
    except Exception as head_error:
        try:
            headers["Range"] = "bytes=0-0"
            req = Request(url, headers=headers, method="GET")
            with urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                ctype = resp.headers.get("Content-Type", "")
                clen = resp.headers.get("Content-Length", "")
                dispo = resp.headers.get("Content-Disposition", "")
        except Exception as get_error:
            r.rd_status = "DIRECT_ERROR"
            r.reason = f"No responde como enlace directo: HEAD={str(head_error)[:160]} GET={str(get_error)[:160]}"
            return r

    size_gb = _content_length_to_gb(clen)
    if size_gb:
        r.size_gb = size_gb
    looks_file = _has_direct_extension(url) or "attachment" in dispo.lower()
    looks_html = "text/html" in str(ctype).lower()
    if 200 <= int(status) < 400 and looks_file and not looks_html and (not size_gb or size_gb * 1024 >= min_mb):
        r.rd_status = "DIRECT_OK"
        r.reason = f"Enlace directo verificado: HTTP {status}, tipo={ctype or '-'}, tamaño={(size_gb or 0):.2f} GB"
    else:
        r.rd_status = "DIRECT_NO_VALIDO"
        r.reason = f"No parece descarga directa final: HTTP {status}, tipo={ctype or '-'}, tamaño={(size_gb or 0):.2f} GB"
    return r

def validate_direct_links(results):
    direct = [r for r in results if _is_direct_candidate_result(r)]
    if not direct:
        return results
    print(f"\nComprobando enlaces directos: {len(direct)}")
    diag("direct_check_start", total=len(direct))
    for i, r in enumerate(direct, 1):
        print(f"  Directo {i}/{len(direct)}: {r.title[:100]}")
        validate_direct_link(r)
        diag("direct_check_item", n=i, total=len(direct), status=r.rd_status, url=r.source_url[:240], reason=r.reason[:300])
    summary = {}
    for r in direct:
        summary[r.rd_status] = summary.get(r.rd_status, 0) + 1
    diag("direct_check_end", **summary, total=len(direct))
    return results

def _is_probably_torrent_bytes(raw):
    if not raw:
        return False
    chunk = raw[:8192].lower()
    return raw[:1] == b"d" and b"announce" in chunk and b"info" in chunk

def _looks_html_bytes(raw):
    head = (raw or b"")[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<head" in head[:200]

def probe_torrent_candidate_url(url):
    """
    Resuelve un candidato antes de mandarlo a Real-Debrid.
    Evita el fallo visto en diagnóstico: enviar HTML, imágenes o páginas de categoría como si fueran .torrent.
    """
    timeout = int(CONFIG.get("torrent_candidate_probe_timeout_sec", 12) or 12)
    headers = {
        "User-Agent": "Mozilla/5.0 RD-Turbo-Pro/2.4",
        "Accept": "application/x-bittorrent,application/octet-stream,*/*;q=0.8",
        "Range": "bytes=0-8191",
    }

    def _request(with_range=True):
        req_headers = dict(headers)
        if not with_range:
            req_headers.pop("Range", None)
        req = Request(url, headers=req_headers, method="GET")
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read(8192)
            return {
                "status": int(getattr(resp, "status", 200) or 200),
                "content_type": resp.headers.get("Content-Type", ""),
                "content_length": resp.headers.get("Content-Length", ""),
                "content_disposition": resp.headers.get("Content-Disposition", ""),
                "final_url": resp.geturl() or url,
                "raw": raw,
            }

    try:
        try:
            meta = _request(with_range=True)
        except HTTPError as e:
            if e.code == 416:
                meta = _request(with_range=False)
            else:
                raise
    except Exception as e:
        return {"ok": False, "url": url, "final_url": url, "reason": f"No responde: {str(e)[:180]}", "content_type": ""}

    final_url = meta["final_url"]
    ctype = str(meta.get("content_type") or "").lower()
    dispo = str(meta.get("content_disposition") or "").lower()
    raw = meta.get("raw") or b""
    path = unquote(urlparse(final_url).path or "").lower()
    is_html = "text/html" in ctype or _looks_html_bytes(raw)
    is_image = ctype.startswith("image/") or path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".ico"))
    is_torrent = (
        "application/x-bittorrent" in ctype
        or path.endswith(".torrent")
        or ".torrent" in dispo
        or _is_probably_torrent_bytes(raw)
    )

    if is_html:
        reason = f"Es HTML, no .torrent final: tipo={ctype or '-'}"
        return {"ok": False, "url": url, "final_url": final_url, "reason": reason, "content_type": ctype}
    if is_image:
        reason = f"Es imagen/recurso, no .torrent final: tipo={ctype or '-'}"
        return {"ok": False, "url": url, "final_url": final_url, "reason": reason, "content_type": ctype}
    if not is_torrent:
        reason = f"No parece .torrent final: tipo={ctype or '-'}"
        return {"ok": False, "url": url, "final_url": final_url, "reason": reason, "content_type": ctype}

    return {"ok": True, "url": url, "final_url": final_url, "reason": f".torrent confirmado: tipo={ctype or '-'}", "content_type": ctype}

def materialize_torrent_candidates(results):
    if not CONFIG.get("torrent_candidate_probe_enabled", True):
        return results
    targets = [r for r in results if r.torrent_url and r.rd_status in ("TORRENT_PENDIENTE", "SIN_COMPROBAR")]
    if not targets:
        return results
    max_probe = int(CONFIG.get("torrent_candidate_probe_max", 40) or 40)
    print(f"\nValidando enlaces .torrent antes de Real-Debrid: {min(len(targets), max_probe)}/{len(targets)}")
    diag("torrent_probe_start", total=len(targets), max=max_probe)
    checked = 0
    for r in targets:
        if checked >= max_probe:
            r.rd_status = "NO_VERIFICADO"
            r.reason = "No verificado por límite de seguridad de prueba .torrent"
            continue
        checked += 1
        meta = probe_torrent_candidate_url(r.torrent_url)
        if meta.get("ok"):
            old = r.torrent_url
            r.torrent_url = meta.get("final_url") or r.torrent_url
            r.source_url = r.torrent_url
            r.rd_status = "TORRENT_PENDIENTE"
            r.reason = meta.get("reason", "")
            diag("torrent_probe_ok", n=checked, url=old[:240], final_url=r.torrent_url[:240], content_type=meta.get("content_type", ""), title=r.title[:160])
        else:
            r.rd_status = "TORRENT_NO_VALIDO"
            r.reason = meta.get("reason", "No es .torrent final")
            diag("torrent_probe_reject", n=checked, url=r.torrent_url[:240], final_url=str(meta.get("final_url", ""))[:240], reason=r.reason[:300], title=r.title[:160])
    summary = {}
    for r in targets:
        summary[r.rd_status] = summary.get(r.rd_status, 0) + 1
    diag("torrent_probe_end", **summary, total=len(targets))
    return results

def magnet_hash(magnet):
    try:
        q = parse_qs(urlparse(magnet).query)
        for xt in q.get("xt", []):
            if xt.lower().startswith("urn:btih:"):
                h = xt.split(":")[-1].strip().lower()
                if re.fullmatch(r"[a-f0-9]{40}", h):
                    return h
                if re.fullmatch(r"[a-z2-7]{32}", h):
                    try:
                        return base64.b32decode(h.upper()).hex()
                    except Exception:
                        return h
    except Exception:
        pass
    m = re.search(r"btih:([a-fA-F0-9]{40}|[A-Za-z2-7]{32})", magnet)
    if m:
        h = m.group(1).lower()
        if len(h) == 32:
            try:
                return base64.b32decode(h.upper()).hex()
            except Exception:
                return h
        return h
    return ""

def magnet_title(magnet):
    try:
        q = parse_qs(urlparse(magnet).query)
        dn = q.get("dn", [""])[0]
        if dn:
            return unquote(dn).replace("+", " ").strip()
    except Exception:
        pass
    return ""

def guess_title_from_context(context):
    ctx = context.replace("magnet:?", " magnet:?")
    before = re.split(r"magnet:\?", ctx, maxsplit=1)[0]
    before = re.sub(r"\b\d+\s+files?\b.*$", "", before, flags=re.I)
    before = re.sub(r"\bfound\s+\d+\s+(years?|months?|days?)\s+ago\b", "", before, flags=re.I)
    before = before.strip(" -·|\t\r\n")
    if len(before) > 180:
        before = before[-180:]
    return before.strip()

def parse_size_gb(text):
    """Saca el tamaño más grande que aparezca en el bloque de resultado."""
    text = html.unescape(str(text or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    sizes = []
    patterns = [
        r"(\d+(?:[\.,]\d+)?)\s*(TB|GB|MB|GiB|MiB|TiB)",
        r"(\d+(?:[\.,]\d+)?)\s*(T|G|M)\b",
    ]
    for pat in patterns:
        for num, unit in re.findall(pat, text, flags=re.I):
            try:
                value = float(num.replace(",", "."))
            except Exception:
                continue
            u = unit.lower()
            if u in ("tb", "tib", "t"):
                value *= 1024
            elif u in ("mb", "mib", "m"):
                value /= 1024
            # Evita pillar años tipo 2011 G por error, pero acepta películas pequeñas.
            if 0.001 <= value <= 5000:
                sizes.append(value)
    return max(sizes) if sizes else 0.0


def _candidate_file_lines_from_context(context):
    """Saca posibles archivos internos de un bloque BTDigg sin repartir la búsqueda entre varios archivos."""
    raw = html.unescape(str(context or "")).replace("\xa0", " ")
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</?(div|p|li|tr|td|span|a|b|strong|em)[^>]*>", "\n", raw, flags=re.I)
    raw = re.sub(r"<script.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"\r\n?", "\n", raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n\s+", "\n", raw)
    txt = raw.strip()
    txt = re.sub(r"\b(TB|GB|MB|GiB|MiB|TiB)found\b", r"\1 found", txt, flags=re.I)
    txt = re.sub(r"\bfound\s+\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago\s+", lambda m: m.group(0) + "\n", txt, flags=re.I)
    txt = re.sub(r"((?:TB|GB|MB|GiB|MiB|TiB)\b)\s+(?=.{3,180}?\.(?:mkv|mp4|avi|m4v|mov|wmv|torrent)\b)", r"\1\n", txt, flags=re.I)
    candidates = []
    seen = set()
    video_pat = re.compile(r"([^\n]{1,260}?\.(?:mkv|mp4|avi|m4v|mov|wmv))\s+(\d+(?:[\.,]\d+)?)\s*(TB|GB|MB|GiB|MiB|TiB)\b", re.I)
    torrent_pat = re.compile(r"([^\n]{1,260}?\.torrent)\s+(\d+(?:[\.,]\d+)?)\s*(KB|MB|GB)\b", re.I)
    for pat, kind in ((video_pat, "video"), (torrent_pat, "torrent")):
        for m in pat.finditer(txt):
            name = re.sub(r"\s+", " ", m.group(1)).strip(" -•·\t\r\n")
            gb = parse_size_gb(f"{m.group(2)} {m.group(3)}")
            key = normalize(name)
            if not name or key in seen:
                continue
            seen.add(key)
            candidates.append({"name": name, "gb": gb, "kind": kind})
    return candidates

def _same_file_match_for_result(title, context):
    """True solo si los términos fuertes de búsqueda caen en el mismo título/archivo."""
    terms = query_terms_for_match()
    if not terms:
        return True, title or "", 0.0, "sin_terminos_fuertes"
    title_ratio, title_hits = _match_ratio(terms, title or "")
    if title_ratio >= 1.0:
        return True, title or "", 0.0, "titulo_coincide=" + ",".join(title_hits)
    best = None
    for c in _candidate_file_lines_from_context(context):
        if c.get("kind") != "video":
            continue
        ratio, hits = _match_ratio(terms, c["name"])
        quality = score_result(Result(title=c["name"], size_gb=c.get("gb") or 0), 0).score
        score = ratio * 1000 + min(200, (c.get("gb") or 0) * 4) + quality
        item = (score, ratio, hits, c)
        if best is None or item[0] > best[0]:
            best = item
    if best and best[1] >= float(CONFIG.get("qbit_same_file_min_ratio", 1.0) or 1.0):
        c = best[3]
        return True, c["name"], c.get("gb") or 0.0, "archivo_interno_coincide=" + ",".join(best[2])
    ctx_ratio, ctx_hits = _match_ratio(terms, context or "")
    if ctx_hits:
        return False, "", 0.0, "palabras_repartidas_en_bloque=" + ",".join(ctx_hits)
    return False, "", 0.0, "sin_coincidencia_mismo_archivo terms=" + ",".join(terms)


def _query_relevance_bucket(r):
    """
    Criba previa en dos carriles:
    - primary: se verifica normal.
    - rescue: no se tira; se prueba solo si hace falta y con limite.
    - discard: basura clara.
    """
    terms = query_terms_for_match()
    if not terms:
        r.same_file_match = True
        r.same_file_reason = "sin_terminos_fuertes"
        r.prefilter_bucket = "primary"
        r.prefilter_reason = "sin_terminos_fuertes"
        return "primary"

    context = _match_context_for_result(r)
    title_ratio, title_hits = _match_ratio(terms, r.title or "")
    ok, fname, fgb, why = _same_file_match_for_result(r.title, context)
    r.same_file_match = bool(ok)
    r.same_file_reason = why
    if ok:
        if fname and fname != r.title:
            r.btdigg_file_name = fname
            r.btdigg_file_size_gb = fgb or 0.0
        if fname and fname != r.title and not title_hits:
            r.rd_status = "RESCATE_BUSQUEDA"
            r.prefilter_bucket = "rescue"
            r.prefilter_reason = "archivo_interno_sin_titulo: " + why
            r.reason = "Rescate RD: archivo interno coincide, pero el titulo del torrent no. " + why
            return "rescue"
        r.prefilter_bucket = "primary"
        r.prefilter_reason = why
        return "primary"

    min_title_ratio = float(CONFIG.get("rd_rescue_min_title_ratio", 0.5) or 0.5)
    if title_hits and title_ratio >= min_title_ratio:
        r.rd_status = "RESCATE_BUSQUEDA"
        r.prefilter_bucket = "rescue"
        r.prefilter_reason = f"titulo_parcial={','.join(title_hits)} ratio={title_ratio:.2f}; {why}"
        r.reason = "Rescate RD: titulo parcial fuerte o pack con archivos ocultos. " + r.prefilter_reason
        return "rescue"

    r.rd_status = "DESCARTADO_BUSQUEDA"
    r.reason = "Descartado antes de verificar: la busqueda no coincide en un mismo titulo/archivo. " + why
    r.prefilter_bucket = "discard"
    r.prefilter_reason = why
    return "discard"


def _result_relevant_to_current_query(r):
    return _query_relevance_bucket(r) == "primary"
    """
    Criba seria previa: no verifica basura.
    Regla: los términos fuertes de búsqueda deben aparecer juntos en el título del torrent
    o en un MISMO archivo interno detectado en el bloque de BTDigg.
    No vale repartir palabras entre archivos distintos del pack.
    """
    terms = query_terms_for_match()
    if not terms:
        r.same_file_match = True
        r.same_file_reason = "sin_terminos_fuertes"
        return True
    ok, fname, fgb, why = _same_file_match_for_result(r.title, _match_context_for_result(r))
    r.same_file_match = bool(ok)
    r.same_file_reason = why
    if ok:
        if fname and fname != r.title:
            r.btdigg_file_name = fname
            r.btdigg_file_size_gb = fgb or 0.0
        return True
    r.rd_status = "DESCARTADO_BUSQUEDA"
    r.reason = "Descartado antes de verificar: la búsqueda no coincide en un mismo título/archivo. " + why
    return False

def normalize(s):
    s = str(s or "").lower()
    repl = {"á":"a", "é":"e", "í":"i", "ó":"o", "ú":"u", "ñ":"n", "ü":"u"}
    for a, b in repl.items():
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s

def _word_hit(word, text):
    w = normalize(word)
    if not w:
        return False
    # Para palabras cortas como ts/cam/esp evitamos falsos positivos dentro de otras palabras.
    if len(w) <= 4 and re.fullmatch(r"[a-z0-9]+", w):
        return re.search(r"(^|[^a-z0-9])" + re.escape(w) + r"([^a-z0-9]|$)", text) is not None
    return w in text

def _effective_result_size_gb(r):
    for attr in ("selected_file_size_gb", "btdigg_file_size_gb", "size_gb", "rd_largest_gb", "qbt_size_gb"):
        try:
            value = float(getattr(r, attr, 0) or 0)
        except Exception:
            value = 0.0
        if value > 0:
            return value
    return 0.0

def _current_min_size_gb():
    try:
        return max(0.0, float(CURRENT_MIN_SIZE_GB or 0))
    except Exception:
        return 0.0

def _current_min_size_effective_gb():
    min_gb = _current_min_size_gb()
    if min_gb <= 0:
        return 0.0
    try:
        tol_gb = max(0.0, float(CONFIG.get("quality_min_size_tolerance_gb", 1.0) or 0.0))
    except Exception:
        tol_gb = 1.0
    try:
        tol_pct = max(0.0, float(CONFIG.get("quality_min_size_tolerance_pct", 0.05) or 0.0))
    except Exception:
        tol_pct = 0.05
    try:
        tol_max = max(0.0, float(CONFIG.get("quality_min_size_tolerance_max_gb", 3.0) or 0.0))
    except Exception:
        tol_max = 3.0
    tolerance = max(tol_gb, min_gb * tol_pct)
    if tol_max > 0:
        tolerance = min(tolerance, tol_max)
    return max(0.0, min_gb - tolerance)

def _current_min_size_text():
    min_gb = _current_min_size_gb()
    effective = _current_min_size_effective_gb()
    if min_gb <= 0:
        return "sin minimo"
    if effective < min_gb:
        return f">= ~{min_gb:g} GB (acepto desde {effective:.1f} GB)"
    return f">= {min_gb:g} GB"

def _passes_current_min_size(r, stage=""):
    min_gb = _current_min_size_gb()
    if min_gb <= 0:
        return True
    effective_min_gb = _current_min_size_effective_gb()
    selected = float(getattr(r, "selected_file_size_gb", 0) or 0)
    btdigg_file = float(getattr(r, "btdigg_file_size_gb", 0) or 0)
    total_size = float(getattr(r, "size_gb", 0) or 0)
    rd_largest = float(getattr(r, "rd_largest_gb", 0) or 0)
    if "after_rd" in str(stage) and selected > 0:
        if getattr(r, "rd_existing", False) and total_size >= min_gb:
            return True
        size = selected
    elif "after_rd" in str(stage) and rd_largest > 0:
        size = rd_largest
    else:
        size = _effective_result_size_gb(r)
        if (
            size > 0
            and size < min_gb
            and btdigg_file > 0
            and total_size >= min_gb
            and _title_strong_match_for_current_query(r)
        ):
            _append_reason(r, f"rescate_tamano_total_preRD={total_size:.1f}GB")
            return True
    if size <= 0:
        _append_reason(r, f"sin_tamano_para_min_{min_gb:g}GB")
        return True
    if size >= effective_min_gb:
        return True
    r.rd_status = "DESCARTADO_TAMANO"
    r.reason = f"Descartado por minimo de calidad: {size:.1f} GB < {min_gb:g} GB aprox"
    return False

def _apply_current_min_size_filter(items, stage):
    min_gb = _current_min_size_gb()
    if min_gb <= 0:
        return list(items), []
    effective_min_gb = _current_min_size_effective_gb()
    kept = []
    discarded = []
    for r in items:
        if _passes_current_min_size(r, stage):
            kept.append(r)
        else:
            discarded.append(r)
    diag(
        "min_size_filter",
        stage=stage,
        min_gb=min_gb,
        effective_min_gb=round(effective_min_gb, 3),
        tolerance_gb=round(max(0.0, min_gb - effective_min_gb), 3),
        before=len(items),
        after=len(kept),
        removed=len(discarded),
    )
    if discarded:
        print(f"Filtro tamano calidad: {len(kept)}/{len(items)} siguen con {_current_min_size_text()}.")
    return kept, discarded

def score_result(r, mode):
    original_context = getattr(r, "raw_context", "") or r.reason or ""
    text = normalize(r.title + " " + original_context)
    score = 0
    found = []

    # Calidad: SIEMPRE puntúa, incluso en modo 0 sin filtro.
    for word, weight in CONFIG.get("quality_weights", {}).items():
        if _word_hit(word, text):
            score += int(weight)
            found.append(f"+{word}")

    # Pesos extra realistas.
    extras = {
        "bdrip": -8, "brrip": -8, "dvdrip": -25, "xvid": -20,
        "hdrip": -15, "webdl": 16, "web dl": 16,
        "ac3": 3, "dts-hd": 8, "dts hd": 8,
    }
    for word, weight in extras.items():
        if _word_hit(word, text):
            score += weight
            found.append(f"{word}:{weight:+d}")

    if r.size_gb:
        if CONFIG.get("min_size_gb", 0) <= r.size_gb <= CONFIG.get("max_size_gb", 9999):
            # Da puntos por tamaño, pero no dejes que una burrada mande por encima de calidad.
            score += min(25, max(0, int(r.size_gb // 3)))
            found.append(f"+size:{r.size_gb:.1f}GB")
        else:
            score -= 35
            found.append("tamaño_raro")

    lang_good = [normalize(x) for x in CONFIG.get("language_good", [])]
    lang_bad = [normalize(x) for x in CONFIG.get("language_bad", [])]
    has_good_lang = any(_word_hit(w, text) for w in lang_good)
    has_bad_lang = any(_word_hit(w, text) for w in lang_bad)

    if mode == 2:
        if has_good_lang:
            score += 25
            found.append("+idioma")
        if has_bad_lang:
            score -= 12
            found.append("-idioma")
    elif mode == 3:
        if has_good_lang:
            score += 40
            found.append("+idioma_obligatorio")
        else:
            score -= 999
            found.append("sin_idioma")
        if has_bad_lang:
            score -= 40
            found.append("-idioma")

    for w in CONFIG.get("bad_words", []):
        if _word_hit(w, text):
            score -= 70
            found.append(f"-{w}")

    r.score = score
    r.reason = ", ".join(found) if found else "sin marcas relevantes"
    return r

def dedupe_results(results):
    seen = set()
    out = []
    for r in results:
        key = r.hash or r.magnet or r.torrent_url or r.source_url
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out

def parse_pages(spec):
    spec = (spec or "").strip()
    if spec == "0":
        return list(range(1, int(CONFIG.get("safe_max_pages_when_zero", 30)) + 1))
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", spec)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            a, b = b, a
        return list(range(max(1, a), min(b, 500) + 1))
    if spec.isdigit():
        n = int(spec)
        return list(range(1, max(1, n) + 1))
    return parse_pages(str(CONFIG.get("default_pages", "1-5")))

def build_url(template, query, page):
    return template.format(
        query_quote=quote(query),
        query_path=quote(query.replace(" ", "-")),
        page=page,
        page0=max(0, page - 1),
    )

def btdigg_search_query(query):
    raw = str(query or "").strip()
    if not raw:
        return raw
    out = []
    changed = False
    for token in re.split(r"\s+", raw):
        if not token:
            continue
        if re.fullmatch(r"(?i)(?:\d{3,4}p|\d+k|x?26[45]|h?26[45]|\d+bits?)", token):
            out.append(token)
            continue
        camel = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", token)
        parts = re.findall(r"[A-Za-z]+|\d+", camel)
        if len(parts) >= 2:
            nums = [p for p in parts if p.isdigit()]
            split_ok = (
                any(len(n) >= 2 for n in nums)
                or (parts[-1].isdigit() and len(parts[-1]) == 1)
                or bool(re.search(r"\d(?=[A-Z])", token))
            )
            if split_ok:
                out.extend(parts)
                changed = True
                continue
        out.append(camel)
        if camel != token:
            changed = True
    final = re.sub(r"\s+", " ", " ".join(out)).strip()
    if changed and normalize(final) != normalize(raw):
        diag("btdigg_query_expanded", original=raw, expanded=final)
    return final or raw

# ============================================================
# NAVEGADOR AUTOMÁTICO POR CDP (sin Selenium / sin Playwright)
# ============================================================

def _win_paths():
    vals = []
    for k in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        v = os.environ.get(k)
        if v:
            vals.append(Path(v))
    return vals

def find_browser_exe():
    # Busca navegador compatible con DevTools. En Docker/NAS usa Chromium.
    env_browser = os.environ.get("BROWSER_BIN") or os.environ.get("CHROME_BIN") or os.environ.get("CHROMIUM_BIN")
    if env_browser and Path(env_browser).exists():
        return env_browser
    if os.name != "nt":
        for c in ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"):
            if Path(c).exists():
                return c
        return ""
    preferred = str(CONFIG.get("browser_preferred", "edge")).lower()
    candidates = []
    pfiles = _win_paths()

    edge_paths = []
    chrome_paths = []
    for base in pfiles:
        edge_paths.append(base / "Microsoft" / "Edge" / "Application" / "msedge.exe")
        chrome_paths.append(base / "Google" / "Chrome" / "Application" / "chrome.exe")

    if preferred == "chrome":
        candidates = chrome_paths + edge_paths
    else:
        candidates = edge_paths + chrome_paths

    for c in candidates:
        if c.exists():
            return str(c)

    for exe in (("chrome.exe" if preferred == "chrome" else "msedge.exe"), "msedge.exe", "chrome.exe"):
        try:
            r = subprocess.run(["where", exe], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                first = (r.stdout or "").splitlines()[0].strip()
                if first:
                    return first
        except Exception:
            pass
    return ""

def _port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.6):
            return True
    except Exception:
        return False

def _json_http(port, path, method="GET", timeout=8):
    url = f"http://127.0.0.1:{int(port)}{path}"
    req = Request(url, data=(b"" if method.upper() in ("PUT", "POST") else None), method=method.upper(), headers={"User-Agent": "RD-Turbo-Pro/1.5"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
        return json.loads(raw or "{}")

def ensure_browser_debug():
    # Arranca navegador real con puerto DevTools o conecta si ya existe.
    port = int(CONFIG.get("browser_debug_port", 9227))
    if _port_open(port):
        try:
            _json_http(port, "/json/version")
            diag("browser_debug_existing", port=port)
            return port
        except Exception:
            pass

    exe = find_browser_exe()
    if not exe:
        raise RuntimeError("No encuentro Edge/Chrome. Instala Edge/Chrome o pon browser_preferred en config.json.")

    profile = APP_DIR / "browser_profile"
    profile.mkdir(exist_ok=True)
    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-popup-blocking",
        "--new-window",
        "about:blank",
    ]
    if os.name != "nt":
        args.extend(["--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
    diag("browser_launch", exe=exe, port=port, profile=str(profile))
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(40):
        sleep_interruptible(0.5, where="browser_debug_launch")
        if _port_open(port):
            try:
                _json_http(port, "/json/version")
                diag("browser_debug_ready", port=port)
                return port
            except Exception:
                pass
    raise RuntimeError("El navegador no abrió el puerto de control. Revisa antivirus/permisos.")

def new_debug_tab(port, url="about:blank"):
    path = "/json/new?" + quote(url, safe=":/?&=%")
    last = None
    for method in ("PUT", "GET"):
        try:
            tab = _json_http(port, path, method=method)
            ws = tab.get("webSocketDebuggerUrl")
            if ws:
                diag("browser_new_tab", method=method, ws=ws[:80])
                return ws
        except Exception as e:
            last = e
    try:
        tabs = _json_http(port, "/json/list")
        for tab in tabs:
            if tab.get("type") == "page" and tab.get("webSocketDebuggerUrl"):
                diag("browser_reuse_tab", ws=tab.get("webSocketDebuggerUrl", "")[:80])
                return tab["webSocketDebuggerUrl"]
    except Exception as e:
        last = e
    raise RuntimeError(f"No pude crear pestaña DevTools: {last}")

class CDPClient:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.next_id = 1
        u = urlparse(ws_url)
        self.host = u.hostname or "127.0.0.1"
        self.port = u.port or 80
        self.path = (u.path or "/") + (("?" + u.query) if u.query else "")
        self.sock = socket.create_connection((self.host, self.port), timeout=10)
        self.sock.settimeout(10)
        self._handshake()

    def _handshake(self):
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self.sock.sendall(req)
        resp = self.sock.recv(4096)
        if b" 101 " not in resp and b" 101\r\n" not in resp:
            raise RuntimeError("Handshake WebSocket fallido")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass

    def _send_frame(self, data: bytes):
        header = bytearray([0x81])
        ln = len(data)
        if ln < 126:
            header.append(0x80 | ln)
        elif ln < 65536:
            header.append(0x80 | 126)
            header += ln.to_bytes(2, "big")
        else:
            header.append(0x80 | 127)
            header += ln.to_bytes(8, "big")
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RuntimeError("WebSocket cerrado")
            buf += chunk
        return buf

    def _recv_frame(self, timeout=20):
        old = self.sock.gettimeout()
        self.sock.settimeout(timeout)
        try:
            h = self._recv_exact(2)
            b1, b2 = h[0], h[1]
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            ln = b2 & 0x7F
            if ln == 126:
                ln = int.from_bytes(self._recv_exact(2), "big")
            elif ln == 127:
                ln = int.from_bytes(self._recv_exact(8), "big")
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(ln) if ln else b""
            if masked and payload:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 8:
                raise RuntimeError("WebSocket cerrado por navegador")
            if opcode in (1, 2):
                return payload.decode("utf-8", errors="ignore")
            return ""
        finally:
            self.sock.settimeout(old)

    def call(self, method, params=None, timeout=30):
        msg_id = self.next_id
        self.next_id += 1
        payload = {"id": msg_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._send_frame(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        end = time.time() + timeout
        while time.time() < end:
            raw = self._recv_frame(timeout=max(1, int(end - time.time())))
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if obj.get("id") == msg_id:
                if "error" in obj:
                    raise RuntimeError(obj["error"])
                return obj
        raise RuntimeError(f"Timeout CDP esperando {method}")

def browser_eval(cdp, expression, timeout=30):
    res = cdp.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": False}, timeout=timeout)
    return (((res.get("result") or {}).get("result") or {}).get("value"))

def browser_collect_page(cdp, url, page):
    diag("browser_nav_start", page=page, url=url)
    cdp.call("Page.enable", timeout=10)
    cdp.call("Runtime.enable", timeout=10)
    cdp.call("Page.navigate", {"url": url}, timeout=15)
    sleep_interruptible(float(CONFIG.get("browser_wait_after_load_sec", 5)), where="browser_collect_page.wait")
    for _ in range(8):
        try:
            state = browser_eval(cdp, "document.readyState", timeout=5)
            if state in ("complete", "interactive"):
                break
        except Exception:
            pass
        sleep_interruptible(0.75, where="browser_collect_page.ready")

    js = r'''
(() => {
  function clean(t){ return (t || '').replace(/\s+/g, ' ').trim(); }
  function sizeFrom(t){
    const m = clean(t).match(/(\d+(?:[\.,]\d+)?)\s*(TB|GB|MB|GiB|MiB|TiB)/i);
    return m ? (m[1] + ' ' + m[2]) : '';
  }
  function bestContext(a){
    let best = '';
    let bestScore = -999;
    let el = a;
    for (let i=0; i<10 && el; i++, el=el.parentElement) {
      const txt = clean(el.innerText || el.textContent || '');
      if (!txt) continue;
      const magnets = el.querySelectorAll ? el.querySelectorAll('a[href^="magnet:"]').length : 1;
      let score = 0;
      if (magnets === 1) score += 1400;
      if (magnets > 1) score -= 1200 * (magnets - 1);
      if (/results found|order by:|previous|next/i.test(txt)) score -= 1600;
      if (/\d+(?:[\.,]\d+)?\s*(TB|GB|MB|GiB|MiB|TiB)/i.test(txt)) score += 1000;
      if (/2160p|1080p|720p|bluray|bdrip|dvdrip|hevc|x265|castellano|spanish|es-en/i.test(txt)) score += 120;
      if (/files?\b/i.test(txt)) score += 50;
      score += Math.min(txt.length, 900) / 10;
      if (txt.length > 1800) score -= Math.min(900, txt.length / 2);
      if (score > bestScore) { bestScore = score; best = txt; }
    }
    return best;
  }
  const out = [];
  const anchors = Array.from(document.querySelectorAll('a[href]'));
  for (const a of anchors) {
    const href = a.href || a.getAttribute('href') || '';
    if (!href.toLowerCase().startsWith('magnet:')) continue;
    const context = bestContext(a);
    out.push({
      href: href,
      text: clean(a.innerText || a.textContent || ''),
      context: context,
      size_text: sizeFrom(context),
      html_context: a.outerHTML || ''
    });
  }
  return {
    url: location.href,
    title: document.title,
    ready: document.readyState,
    items: out,
    bodyText: document.body ? document.body.innerText.slice(0, 8000) : '',
    htmlSample: document.documentElement ? document.documentElement.outerHTML.slice(0, 250000) : ''
  };
})()
'''
    data = browser_eval(cdp, js, timeout=20) or {}
    items = data.get("items") or []
    results = []
    for item in items:
        magnet = html.unescape(str(item.get("href") or "")).strip().replace("&amp;", "&")
        h = magnet_hash(magnet)
        if not h:
            continue
        context = str(item.get("context") or "")
        title = magnet_title(magnet) or str(item.get("text") or "").strip() or guess_title_from_context(context) or h
        dom_size = parse_size_gb(item.get("context", "") + " " + item.get("size_text", ""))
        same_ok, file_name, file_gb, same_reason = _same_file_match_for_result(title, context)
        r = Result(title=title, magnet=magnet, hash=h.lower(), size_gb=dom_size, source_url=url, raw_context=context[:4000], reason=context[:900])
        r.same_file_match = bool(same_ok)
        r.same_file_reason = same_reason
        if file_name and file_name != title:
            r.btdigg_file_name = file_name
            r.btdigg_file_size_gb = file_gb or 0.0
        results.append(r)
    if not results:
        blob = (data.get("htmlSample") or "") + "\n" + (data.get("bodyText") or "")
        results = extract_magnets_from_text(blob, source_url=url)
    results = dedupe_results(results)
    diag("browser_page_result", page=page, url=url, ready=data.get("ready"), title=data.get("title"), dom_items=len(items), magnets=len(results), sizes=sum(1 for r in results if r.size_gb))
    return results, data

def browser_wait_ready(cdp, seconds=None):
    wait_total = float(seconds if seconds is not None else CONFIG.get("browser_wait_after_load_sec", 5))
    sleep_interruptible(max(0.5, min(wait_total, 3)), where="browser_wait_ready.initial")
    for _ in range(8):
        try:
            state = browser_eval(cdp, "document.readyState", timeout=5)
            if state in ("complete", "interactive"):
                break
        except Exception:
            pass
        sleep_interruptible(0.75, where="browser_wait_ready.ready")

def browser_snapshot(cdp):
    js = r'''
(() => {
  return {
    url: location.href,
    title: document.title,
    ready: document.readyState,
    bodyText: document.body ? document.body.innerText.slice(0, 12000) : '',
    htmlSample: document.documentElement ? document.documentElement.outerHTML.slice(0, 350000) : ''
  };
})()
'''
    return browser_eval(cdp, js, timeout=20) or {}

def browser_navigate_and_snapshot(cdp, url):
    diag("authorized_browser_nav", url=url)
    cdp.call("Page.enable", timeout=10)
    cdp.call("Runtime.enable", timeout=10)
    cdp.call("Page.navigate", {"url": url}, timeout=15)
    browser_wait_ready(cdp)
    return browser_snapshot(cdp)

def browser_submit_site_search(cdp, query):
    payload = json.dumps(query)
    js = r'''
(() => {
  const query = __QUERY__;
  function visible(el) {
    const r = el.getBoundingClientRect();
    const st = window.getComputedStyle(el);
    return r.width > 10 && r.height > 10 && st.visibility !== 'hidden' && st.display !== 'none';
  }
  function scoreInput(el) {
    const blob = [
      el.type || '', el.name || '', el.id || '', el.className || '',
      el.placeholder || '', el.getAttribute('aria-label') || ''
    ].join(' ').toLowerCase();
    let s = 0;
    if (el.type === 'search') s += 100;
    if (/(search|buscar|busqueda|búsqueda|s\b|q\b)/i.test(blob)) s += 80;
    if (/(email|password|login|user|usuario)/i.test(blob)) s -= 200;
    return s;
  }
  const inputs = Array.from(document.querySelectorAll('input, textarea'))
    .filter(visible)
    .map(el => ({ el, score: scoreInput(el) }))
    .filter(x => x.score > -100)
    .sort((a, b) => b.score - a.score);
  const pick = inputs[0] && inputs[0].el;
  if (!pick) return { ok:false, reason:'sin_input_visible' };
  pick.focus();
  pick.value = query;
  pick.dispatchEvent(new Event('input', { bubbles:true }));
  pick.dispatchEvent(new Event('change', { bubbles:true }));
  const form = pick.closest('form');
  if (form) {
    if (form.requestSubmit) form.requestSubmit();
    else form.submit();
    return { ok:true, method:'form', action: form.action || location.href };
  }
  pick.dispatchEvent(new KeyboardEvent('keydown', { key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true }));
  pick.dispatchEvent(new KeyboardEvent('keyup', { key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true }));
  return { ok:true, method:'enter' };
})()
'''.replace("__QUERY__", payload)
    return browser_eval(cdp, js, timeout=10) or {}

def _result_from_torrent_candidate_url(url, title=""):
    url = _clean_url(url)
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    title = strip_html(title) or unquote(Path(urlparse(url).path).name) or url
    return Result(title=title, torrent_url=url, source_url=url, rd_status="TORRENT_PENDIENTE")

def browser_download_controls(cdp, page_url, depth=0, seen_pages=None):
    """
    En una ficha renderizada, busca botones/enlaces de descarga y prueba clics controlados.
    Solo devuelve candidatos; la validación real de .torrent se hace después con probe_torrent_candidate_url.
    """
    max_clicks = int(CONFIG.get("authorized_site_download_clicks_max", 4) or 4)
    wait_sec = float(CONFIG.get("authorized_site_download_wait_sec", 4) or 4)
    max_hops = int(CONFIG.get("authorized_site_link_hops_max", 3) or 3)
    if depth > max_hops:
        diag("authorized_browser_hop_limit", url=page_url, depth=depth, max=max_hops)
        return []
    if seen_pages is None:
        seen_pages = set()
    page_key = (page_url or "").split("#", 1)[0]
    if page_key in seen_pages:
        return []
    seen_pages.add(page_key)
    diag("authorized_browser_download_scan", url=page_url, depth=depth)
    js_list = r'''
(() => {
  function clean(t){ return (t || '').replace(/\s+/g, ' ').trim(); }
  function visible(el) {
    const r = el.getBoundingClientRect();
    const st = window.getComputedStyle(el);
    return r.width > 8 && r.height > 8 && st.visibility !== 'hidden' && st.display !== 'none';
  }
  function blob(el) {
    return clean([
      el.innerText || el.textContent || el.value || '',
      el.getAttribute('aria-label') || '',
      el.getAttribute('title') || '',
      el.getAttribute('class') || '',
      el.getAttribute('id') || '',
      el.getAttribute('href') || '',
      el.getAttribute('onclick') || ''
    ].join(' '));
  }
  const els = Array.from(document.querySelectorAll('a[href], button, input[type=button], input[type=submit], [role=button]'));
  return els.map((el, idx) => ({ idx, text: blob(el), href: el.href || el.getAttribute('href') || '' }))
    .filter(x => /\b(descargar|descarga|download|torrent|freeleech|bajar|enlace|link|continuar|continue|saltar|skip)\b/i.test(x.text) || /ir\s+al\s+enlace|go\s+to\s+link|open\s+link|get\s+link/i.test(x.text) || /(^|\/)(download|downloads|descargar|descarga|torrent|torrents|link|go)(\/|$)/i.test(x.href || ''))
    .slice(0, 12);
})()
'''
    try:
        candidates = browser_eval(cdp, js_list, timeout=10) or []
    except Exception as e:
        diag("authorized_browser_download_controls_error", url=page_url, error=str(e)[:300])
        return []

    out = []
    seen = set()

    def add_result(url, title=""):
        url = _clean_url(url)
        if not url or url in seen:
            return
        seen.add(url)
        r = _result_from_torrent_candidate_url(url, title)
        if r:
            out.append(r)

    def follow_intermediate(url, title=""):
        url = _clean_url(url)
        if not url or depth >= max_hops:
            return
        if url.split("#", 1)[0] in seen_pages:
            return
        try:
            diag("authorized_browser_hop_start", from_url=page_url, to_url=url[:240], depth=depth + 1, title=str(title)[:120])
            snap = browser_navigate_and_snapshot(cdp, url)
            current = snap.get("url") or url
            blob = (snap.get("htmlSample") or "") + "\n" + (snap.get("bodyText") or "")
            for r in extract_direct_links_from_html(blob, base_url=current):
                key = r.torrent_url or r.source_url
                if key and key not in seen:
                    seen.add(key)
                    out.append(r)
            out.extend(browser_download_controls(cdp, current, depth=depth + 1, seen_pages=seen_pages))
            diag("authorized_browser_hop_done", from_url=page_url, to_url=url[:240], current=current[:240], depth=depth + 1, results=len(out))
        except Exception as e:
            diag("authorized_browser_hop_error", from_url=page_url, to_url=url[:240], depth=depth + 1, error=str(e)[:300])

    for c in candidates:
        href = _clean_url(c.get("href") or "")
        if href and not href.startswith(("javascript:", "#")):
            full = urljoin(page_url, href)
            add_result(full, c.get("text") or "")
            follow_intermediate(full, c.get("text") or "")
            try:
                browser_navigate_and_snapshot(cdp, page_url)
            except Exception:
                pass

    click_candidates = candidates[:max_clicks]
    if not click_candidates:
        return out

    try:
        cdp.call("Network.enable", timeout=10)
    except Exception:
        pass

    for pos, c in enumerate(click_candidates):
        idx = int(c.get("idx", -1))
        if idx < 0:
            continue
        before_url = ""
        try:
            before_url = browser_eval(cdp, "location.href", timeout=5) or page_url
            click_js = f'''
(() => {{
  const els = Array.from(document.querySelectorAll('a[href], button, input[type=button], input[type=submit], [role=button]'));
  const el = els[{idx}];
  if (!el) return {{ok:false, reason:'missing'}};
  el.scrollIntoView({{block:'center', inline:'center'}});
  el.click();
  return {{ok:true, href: el.href || el.getAttribute('href') || '', text: (el.innerText || el.textContent || el.value || '').trim()}};
}})()
'''
            click_res = browser_eval(cdp, click_js, timeout=10) or {}
            diag("authorized_browser_download_click", url=page_url, depth=depth, index=idx, ok=click_res.get("ok"), text=str(click_res.get("text", ""))[:120], href=str(click_res.get("href", ""))[:240])
            end = time.time() + wait_sec
            captured = []
            while time.time() < end:
                try:
                    raw = cdp._recv_frame(timeout=1)
                except Exception:
                    continue
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                method = obj.get("method", "")
                params = obj.get("params") or {}
                url = ""
                if method == "Network.requestWillBeSent":
                    url = ((params.get("request") or {}).get("url") or "")
                elif method == "Network.responseReceived":
                    url = ((params.get("response") or {}).get("url") or "")
                elif method == "Page.frameNavigated":
                    url = ((params.get("frame") or {}).get("url") or "")
                url = _clean_url(url)
                if url and _looks_like_torrent_url(url) and url not in captured:
                    captured.append(url)
            for url in captured:
                add_result(url, c.get("text") or "")
                follow_intermediate(url, c.get("text") or "")
            try:
                snap = browser_snapshot(cdp)
                current = snap.get("url") or ""
                if current and current not in seen and _looks_like_torrent_url(current):
                    seen.add(current)
                    r = _result_from_torrent_candidate_url(current, c.get("text") or "")
                    if r:
                        out.append(r)
                blob = (snap.get("htmlSample") or "") + "\n" + (snap.get("bodyText") or "")
                for r in extract_direct_links_from_html(blob, base_url=current or before_url):
                    key = r.torrent_url or r.source_url
                    if key and key not in seen:
                        seen.add(key)
                        out.append(r)
                if current and before_url and current.split("#", 1)[0] != before_url.split("#", 1)[0]:
                    out.extend(browser_download_controls(cdp, current, depth=depth + 1, seen_pages=seen_pages))
                if before_url and (snap.get("url") or "").split("#", 1)[0] != before_url.split("#", 1)[0]:
                    browser_navigate_and_snapshot(cdp, page_url)
            except Exception as e:
                diag("authorized_browser_download_snapshot_error", url=page_url, error=str(e)[:300])
                try:
                    browser_navigate_and_snapshot(cdp, page_url)
                except Exception:
                    pass
        except Exception as e:
            diag("authorized_browser_download_click_error", url=page_url, index=idx, error=str(e)[:300])
            try:
                browser_navigate_and_snapshot(cdp, page_url)
            except Exception:
                pass

    diag("authorized_browser_download_controls", url=page_url, depth=depth, controls=len(candidates), results=len(out))
    return dedupe_results(out)

def results_from_rendered_page(data, base_url, query, cdp=None):
    html_text = (data.get("htmlSample") or "") + "\n" + (data.get("bodyText") or "")
    results = extract_direct_links_from_html(html_text, base_url=base_url)
    detail_pages = extract_candidate_pages_from_html(html_text, data.get("url") or base_url, query)
    if cdp and detail_pages:
        print(f"  Fichas renderizadas candidatas: {len(detail_pages)}")
        for i, detail_url in enumerate(detail_pages, 1):
            try:
                print(f"    Ficha navegador {i}/{len(detail_pages)}: {detail_url[:90]}")
                snap = browser_navigate_and_snapshot(cdp, detail_url)
                blob = (snap.get("htmlSample") or "") + "\n" + (snap.get("bodyText") or "")
                results.extend(extract_direct_links_from_html(blob, base_url=snap.get("url") or detail_url))
                results.extend(browser_download_controls(cdp, snap.get("url") or detail_url))
            except Exception as e:
                diag("authorized_browser_detail_error", url=detail_url, error=str(e)[:300])
    return dedupe_results(results)

def search_authorized_site_browser_auto(base_url, query):
    base = normalize_base_url(base_url)
    if not base:
        return []
    port = ensure_browser_debug()
    ws = new_debug_tab(port, base)
    cdp = CDPClient(ws)
    try:
        print(f"  Navegador: {base}")
        browser_navigate_and_snapshot(cdp, base)
        submit = browser_submit_site_search(cdp, query)
        diag("authorized_browser_submit", base=base, query=query, submit=submit)
        if not submit.get("ok"):
            print(f"  No localicé buscador visible ({submit.get('reason', 'sin detalle')}).")
            return []
        browser_wait_ready(cdp, float(CONFIG.get("browser_wait_after_load_sec", 5)) + 2)
        data = browser_snapshot(cdp)
        results = results_from_rendered_page(data, base, query, cdp=cdp)
        diag("authorized_browser_done", base=base, query=query, url=data.get("url"), total=len(results))
        return results
    finally:
        cdp.close()

def search_btdigg_browser_auto(query, page_spec):
    search_query = btdigg_search_query(query)
    pages = parse_pages(page_spec)
    diag("browser_auto_search_start_dom", query=query, search_query=search_query, pages=page_spec, parsed_pages=pages[:80])
    all_results = []
    empty_streak = 0

    for i, page in enumerate(pages, 1):
        cancel_checkpoint("btdigg_browser_auto.page")
        url = build_url("https://en.btdig.com/search?q={query_quote}&p={page0}", search_query, page)
        print(f"\nNavegador automático página {page} ({i}/{len(pages)}):")
        print(f"  {url}")

        results = _btdigg_dump_dom_fallback(url)

        if results:
            all_results.extend(results)
            empty_streak = 0
        else:
            empty_streak += 1
            if empty_streak >= 2:
                print("  Corto: dos páginas seguidas sin magnets.")
                break

        sleep_interruptible(float(CONFIG.get("browser_delay_between_pages_sec", 2)), where="btdigg_browser_auto.delay")

    final = dedupe_results(all_results)
    diag("browser_auto_search_end_dom", query=query, search_query=search_query, total=len(final))
    return final

def _query_has_quality_marker(query):
    text = normalize(query or "")
    return bool(re.search(r"\b(?:2160p|1080p|720p|4k|uhd|remux|bdremux|bluray|blu\s*ray|hevc|x265|h265|x264|h264)\b", text))

def _query_has_identity_number(query):
    text = normalize(query or "")
    if re.search(r"\b(?:19|20)\d{2}\b", text):
        return True
    return bool(re.search(r"\b\d{1,2}\b", text))

def _quality_mode_extra_btdigg_queries(query, mode=0):
    if not CONFIG.get("quality_mode_extra_btdigg_enabled", True):
        return []
    if _query_has_quality_marker(query):
        return []
    # En calidad pura siempre interesa mirar 2160p. En modo normal lo hacemos solo
    # cuando la busqueda trae numero/año claro, para no abrir demasiado la puerta.
    if int(mode or 0) != 1 and not _query_has_identity_number(query):
        return []
    terms = CONFIG.get("quality_mode_extra_btdigg_terms", ["2160p"])
    if isinstance(terms, str):
        terms = [x.strip() for x in re.split(r"[,;|]+", terms) if x.strip()]
    out = []
    base_norm = normalize(query or "")
    for term in terms or []:
        term = str(term or "").strip()
        if not term:
            continue
        if normalize(term) in base_norm:
            continue
        candidate = re.sub(r"\s+", " ", f"{query} {term}").strip()
        if candidate and candidate not in out:
            out.append(candidate)
    return out[:3]

def search_btdigg_browser_auto_quality_aware(query, page_spec, mode):
    cancel_checkpoint("btdigg_quality.before_base")
    results = search_btdigg_browser_auto(query, page_spec)
    extra_queries = _quality_mode_extra_btdigg_queries(query, mode)
    if not extra_queries:
        return results
    base_count = len(dedupe_results(results))
    extra_pages = str(CONFIG.get("quality_mode_extra_btdigg_pages", "1") or "1")
    diag("browser_quality_rescue_start", query=query, extra_queries=extra_queries, pages=extra_pages)
    for extra_query in extra_queries:
        cancel_checkpoint("btdigg_quality.rescue")
        print(f"\nRescate calidad BTDigg: {extra_query} (paginas {extra_pages})")
        try:
            extra_results = search_btdigg_browser_auto(extra_query, extra_pages)
            results.extend(extra_results)
            diag("browser_quality_rescue_results", query=query, extra_query=extra_query, found=len(extra_results))
        except Exception as e:
            diag("browser_quality_rescue_error", query=query, extra_query=extra_query, error=repr(e))
            print(f"  Aviso rescate calidad: {e}")
    final = dedupe_results(results)
    diag("browser_quality_rescue_end", query=query, total=len(final), added=max(0, len(final) - base_count))
    return final

def search_btdigg(query, page_spec):
    search_query = btdigg_search_query(query)
    pages = parse_pages(page_spec)
    templates = CONFIG.get("btdigg_url_templates", [])
    working_template = None
    all_results = []
    empty_streak = 0
    total_429 = 0
    diag("btdigg_search_start", query=query, search_query=search_query, pages=page_spec, parsed_pages=pages[:80])

    for page in pages:
        cancel_checkpoint("btdigg_direct.page")
        print(f"\nBuscando BTDigg página {page}...")
        page_results = []
        trial_templates = [working_template] if working_template else templates
        trial_templates = [t for t in trial_templates if t]
        last_error = ""
        page_had_429 = False

        for tmpl in trial_templates:
            url = build_url(tmpl, search_query, page)
            diag("btdigg_try", page=page, template=tmpl, url=url)
            try:
                html_text = http_get_text(url)
                page_results = extract_magnets_from_text(html_text, source_url=url)
                diag("btdigg_page_result", page=page, url=url, magnets=len(page_results))
                if page_results:
                    working_template = tmpl
                    print(f"  OK: {len(page_results)} magnets encontrados")
                    break
                last_error = "sin magnets"
            except HTTPError as e:
                last_error = f"HTTP Error {e.code}: {e.reason}"
                if e.code == 429:
                    total_429 += 1
                    page_had_429 = True
                    print("  Ese dominio ha frenado la consulta: HTTP 429")
                    diag("btdigg_429_continue", page=page, url=url)
                    sleep_interruptible(float(CONFIG.get("delay_after_btdigg_429_sec", 8)), where="btdigg_direct.429")
                    continue
                continue
            except Exception as e:
                last_error = str(e)[:180]
                continue

        if not page_results:
            empty_streak += 1
            print(f"  Sin resultados útiles ({last_error})")
            if page_had_429 and not all_results:
                diag("btdigg_direct_blocked", page=page, total_429=total_429)
                rescue = browser_rescue_btdigg(search_query, pages)
                if rescue:
                    diag("browser_rescue_ok", total=len(rescue))
                    return rescue
                diag("browser_rescue_empty")
                return dedupe_results(all_results)
            if empty_streak >= 2:
                print("  Corto: dos páginas seguidas sin resultados.")
                break
        else:
            empty_streak = 0
            all_results.extend(page_results)

        sleep_interruptible(float(CONFIG.get("delay_between_btdigg_pages_sec", 7)), where="btdigg_direct.delay")

    diag("btdigg_search_end", query=query, search_query=search_query, total=len(dedupe_results(all_results)), total_429=total_429)
    return dedupe_results(all_results)


def export_results(results, shown=None, write_all_json=True):
    return export_results_impl(
        results,
        shown=shown,
        write_all_json=write_all_json,
        config=CONFIG,
        export_dir=EXPORT_DIR,
        cancel_checkpoint=cancel_checkpoint,
        diag=diag,
        log=log,
        is_qbt_working_status=_is_qbt_working_status,
        is_working_status=_is_working_status,
        last_qbit_extras=LAST_QBIT_EXTRAS,
        last_rd_temp_errors=LAST_RD_TEMP_ERRORS,
    )


def rd_token_healthcheck(token):
    if not token:
        return False, "sin token"
    try:
        user = rd_api("GET", "/user", token)
        if isinstance(user, dict):
            username = user.get("username") or user.get("email") or "usuario"
            account_type = user.get("type") or user.get("premium") or ""
            expiration = user.get("expiration") or ""
            diag("rd_account_check_ok", account_type=str(account_type), has_expiration=bool(expiration))
            print(f"Token Real-Debrid OK: {username}")
            return True, ""
        diag("rd_account_check_weird", response=str(user)[:300])
        return True, ""
    except Exception as e:
        err = str(e)
        diag("rd_account_check_failed", error=err[:500])
        return False, err

def _rd_size_from_info(info):
    """Devuelve (files_count, largest_or_total_gb) a partir de torrents/info."""
    if not isinstance(info, dict):
        return 0, 0.0
    files = info.get("files") or []
    total = 0
    largest = 0
    count = 0
    if isinstance(files, list):
        for f in files:
            if not isinstance(f, dict):
                continue
            try:
                b = int(f.get("bytes") or f.get("filesize") or 0)
            except Exception:
                b = 0
            if b:
                count += 1
                total += b
                largest = max(largest, b)
    for key in ("bytes", "original_bytes"):
        try:
            total = max(total, int(info.get(key) or 0))
        except Exception:
            pass
    best = total or largest
    return count, (best / (1024 ** 3) if best else 0.0)

def rd_delete_torrent(tid, token, why="", release_slot=False):
    if not tid:
        return False
    ctx = get_rd_runtime()
    released = False

    def release_once():
        nonlocal released
        if released or not release_slot:
            return
        if ctx and ctx.slots:
            if not ctx.mark_released(tid):
                released = True
                return
            ctx.slots.on_release()
        released = True

    attempts = max(1, int(CONFIG.get("rd_delete_retry_attempts", 5) or 5))
    base_sec = float(CONFIG.get("rd_delete_retry_base_sec", 0.8) or 0.8)
    max_sec = float(CONFIG.get("rd_delete_retry_max_sec", 4.0) or 4.0)
    try:
        rd_call_with_retry(
            "DELETE",
            f"/torrents/delete/{tid}",
            token,
            op_name="delete",
            attempts=attempts,
            retry_context=ctx,
            base_sec=base_sec,
            max_sec=max_sec,
        )
        diag("rd_delete_torrent", id=tid, why=why, attempts=attempts)
        if ctx:
            ctx.record_cleanup_done(tid, "deleted")
        release_once()
        return True
    except RDAPIError as e:
        if e.status_code == 404:
            diag("rd_delete_torrent_missing", id=tid, why=why)
            if ctx:
                ctx.record_cleanup_done(tid, "missing")
            release_once()
            return True
        if ctx:
            ctx.record_cleanup_pending(tid, why=why, release_slot=release_slot)
        diag("rd_delete_torrent_error", id=tid, why=why, code=e.status_code, error_code=e.error_code, error=str(e)[:300])
        return False
    except Exception as e:
        if ctx:
            ctx.record_cleanup_pending(tid, why=why, release_slot=release_slot)
        diag("rd_delete_torrent_error", id=tid, why=why, error=str(e)[:300])
        return False

def rd_existing_torrents(token):
    global RD_EXISTING_TORRENTS_CACHE
    if not token or not CONFIG.get("rd_check_existing_torrents", True):
        return []
    with RD_EXISTING_LOCK:
        if RD_EXISTING_TORRENTS_CACHE is not None:
            return RD_EXISTING_TORRENTS_CACHE
    try:
        limit = max(10, int(CONFIG.get("rd_existing_torrents_limit", 1000) or 1000))
        data = rd_call_with_retry("GET", f"/torrents?limit={limit}", token, op_name="existing_list", attempts=3, retry_context=get_rd_runtime())
        rows = data if isinstance(data, list) else []
        with RD_EXISTING_LOCK:
            RD_EXISTING_TORRENTS_CACHE = rows
            total = len(RD_EXISTING_TORRENTS_CACHE)
        diag("rd_existing_list", total=total, limit=limit)
    except Exception as e:
        with RD_EXISTING_LOCK:
            RD_EXISTING_TORRENTS_CACHE = []
        diag("rd_existing_list_error", error=str(e)[:300])
    with RD_EXISTING_LOCK:
        return list(RD_EXISTING_TORRENTS_CACHE or [])

def _rd_selected_total_gb(info):
    total = 0
    files = info.get("files") if isinstance(info, dict) else []
    if isinstance(files, list):
        for f in files:
            if not isinstance(f, dict) or not f.get("selected"):
                continue
            try:
                total += int(f.get("bytes") or f.get("filesize") or 0)
            except Exception:
                pass
    return total / (1024 ** 3) if total else 0.0

def _rd_existing_info_score(info, terms=None):
    if not isinstance(info, dict):
        return -1, "", 0.0, "info_invalida"
    links = info.get("links") or []
    if str(info.get("status") or "") != "downloaded" or not links:
        return -1, "", 0.0, "sin_links_descargados"
    terms = list(terms if terms is not None else query_terms_for_match())
    title = str(info.get("filename") or "")
    title_ratio, title_hits = _match_ratio(terms, title)
    score = 100 + int(title_ratio * 500)
    best_path = ""
    best_gb = 0.0
    best_hits = []
    files = info.get("files") or []
    if isinstance(files, list):
        for f in files:
            if not isinstance(f, dict) or not f.get("selected"):
                continue
            path = _file_path(f)
            if not path or not video_ext_ok(path):
                continue
            gb = _file_size_gb(f)
            ratio, hits = _match_ratio(terms, path)
            item_score = int(ratio * 1200) + int(min(300, gb * 8))
            if ratio >= 1.0:
                item_score += 900
            if item_score > score:
                score = item_score
                best_path = path
                best_gb = gb
                best_hits = hits
    if terms and score < 500 and title_ratio < 1.0:
        return -1, "", 0.0, "existente_no_coincide_query"
    reason = "titulo=" + ",".join(title_hits or []) + " archivo=" + ",".join(best_hits or [])
    return score, best_path, best_gb, reason

def rd_find_existing_downloaded_by_hash(h, token, ctx=None, terms=None):
    h = (h or "").lower()
    if not h:
        return None
    if ctx and getattr(ctx, "existing", None) and CONFIG.get("rd_existing_preload_enabled", True):
        return ctx.existing.find_downloaded_by_hash(h, terms=terms)
    best = None
    for item in rd_existing_torrents(token):
        if not isinstance(item, dict):
            continue
        if str(item.get("hash") or "").lower() != h:
            continue
        if str(item.get("status") or "") != "downloaded" or not (item.get("links") or []):
            continue
        tid = str(item.get("id") or "")
        if not tid:
            continue
        try:
            info = rd_call_with_retry("GET", f"/torrents/info/{tid}", token, op_name="info", attempts=3, retry_context=ctx)
        except Exception as e:
            diag("rd_existing_info_error", id=tid, hash=h, error=str(e)[:300])
            continue
        score, path, gb, reason = _rd_existing_info_score(info, terms=terms)
        if score < 0:
            continue
        candidate = (score, item, info, path, gb, reason)
        if best is None or candidate[0] > best[0]:
            best = candidate
    return best

def rd_mark_existing_ok(r, found, idx=0, total=0):
    score, item, info, path, gb, reason = found
    links = info.get("links") or item.get("links") or []
    files_count, size_gb = _rd_size_from_info(info)
    selected_total = _rd_selected_total_gb(info)
    r.rd_status = "RD_OK"
    r.rd_existing = True
    r.rd_torrent_id = str(item.get("id") or info.get("id") or "")
    r.rd_links = len(links)
    r.rd_files = files_count
    r.rd_largest_gb = selected_total or size_gb or r.rd_largest_gb
    r.size_gb = selected_total or size_gb or r.size_gb
    if path:
        r.selected_file_name = path
        r.selected_file_size_gb = gb or 0.0
    r.reason = "Ya estaba descargado en Real-Debrid con link directo. " + reason
    diag(
        "rd_existing_ok",
        n=idx,
        total=total,
        id=r.rd_torrent_id,
        hash=r.hash,
        links=len(links),
        selected_file=path[:240],
        selected_size_gb=round(float(gb or 0), 3),
        size_gb=round(float(r.size_gb or 0), 3),
        title=r.title[:180],
    )
    return r


def video_ext_ok(path):
    p = normalize(path or "")
    return bool(re.search(r"\.(mkv|mp4|avi|m4v|mov|wmv|m2ts|ts)($|[^a-z0-9])", p))

def _file_bytes(f):
    try:
        return int(f.get("bytes") or f.get("filesize") or f.get("size") or 0)
    except Exception:
        return 0

def _file_size_gb(f):
    b = _file_bytes(f)
    return b / (1024 ** 3) if b else 0.0

def _file_id(f):
    return str(f.get("id") or f.get("file_id") or f.get("index") or "").strip()

def _file_path(f):
    return str(f.get("path") or f.get("name") or f.get("filename") or "").strip()

def _basename_norm(path):
    return normalize(str(path or "").replace("\\", "/").rsplit("/", 1)[-1])

def _is_extra_video_path(path):
    base = _basename_norm(path)
    return bool(re.search(r"(^|[^a-z0-9])(sample|trailer|extra|extras|featurette|preview)([^a-z0-9]|$)", base))

_PACK_STOP_WORDS = {
    "the", "and", "con", "los", "las", "una", "uno", "para", "from", "www", "com",
    "movie", "movies", "film", "films", "peli", "pelicula", "torrent", "bluray", "blu", "ray",
    "bdrip", "brrip", "dvdrip", "hdrip", "web", "webrip", "webdl", "dl", "remux", "uhd",
    "hevc", "x265", "h265", "x264", "h264", "2160p", "1080p", "720p", "4k", "hdr",
    "10bit", "10bits", "dts", "truehd", "atmos", "ac3", "aac", "es", "en", "espanol", "español",
    "castellano", "spanish", "ingles", "subs", "dual", "multi", "multisubs", "multisub",
    "multiaudio", "vf2", "vff", "truefrench", "rip", "proper", "repack"
}

def terms_from_query_for_match(query):
    q = normalize(query or "")
    # Quita adornos y separadores para quedarnos con palabras reales de búsqueda.
    # OJO: mantenemos números como 3 y años tipo 2008 porque ayudan a no mezclar títulos.
    q = re.sub(r"\b\d{3,4}p\b|\b\d+bits?\b", " ", q)
    words = []
    for raw in re.findall(r"[a-z0-9]+", q):
        if raw in _PACK_STOP_WORDS:
            continue
        parts = re.findall(r"[a-z]+|\d{1,4}", raw)
        if len(parts) > 1:
            words.extend(parts)
        else:
            words.append(raw)
    out = []
    for w in words:
        if w in _PACK_STOP_WORDS:
            continue
        # Esto sí son adornos técnicos, no identidad de la película/serie.
        if re.fullmatch(r"\d{3,4}p|\d+bits?", w):
            continue
        if re.fullmatch(r"[a-z]+", w) and len(w) < 3:
            continue
        if w not in out:
            out.append(w)
    return out[:8]

def query_terms_for_match(query=None):
    return terms_from_query_for_match((CURRENT_QUERY if query is None else query) or "")

def _match_ratio(terms, text):
    if not terms:
        return 0.0, []
    nt = normalize(text or "")
    hits = []
    for t in terms:
        if _word_hit(t, nt) or _year_covered_by_range(t, nt):
            hits.append(t)
    return len(hits) / max(1, len(terms)), hits

def _year_covered_by_range(term, normalized_text):
    if not re.fullmatch(r"(?:19|20)\d{2}", str(term or "")):
        return False
    try:
        year = int(term)
    except Exception:
        return False
    text = normalize(normalized_text or "")
    for a, b in re.findall(r"\b((?:19|20)\d{2})\s*[-_/]\s*((?:19|20)\d{2})\b", text):
        start, end = int(a), int(b)
        if start > end:
            start, end = end, start
        if start <= year <= end:
            return True
    return False

def _title_strong_match_for_current_query(r):
    terms = query_terms_for_match()
    if not terms:
        return True
    ratio, _hits = _match_ratio(terms, getattr(r, "title", "") or "")
    return ratio >= 1.0

def _append_reason(r, text):
    if text:
        r.reason = (r.reason + ", " if r.reason else "") + text

def _match_context_for_result(r):
    """
    Contexto bruto para criba.
    No usamos solo reason porque luego se convierte en motivo visible/puntuacion.
    """
    parts = []
    raw = getattr(r, "raw_context", "") or ""
    if raw:
        parts.append(raw)
    elif getattr(r, "reason", ""):
        parts.append(r.reason)
    for value in (getattr(r, "btdigg_file_name", ""), getattr(r, "selected_file_name", "")):
        if value:
            parts.append(value)
    return "\n".join(parts)

def choose_internal_files(info, wanted_title="", wanted_terms=None):
    """
    Escoge archivos internos seguros.
    Regla clave: nunca selecciona todo a ciegas. En packs busca el archivo que coincide con la búsqueda.
    """
    files = info.get("files") if isinstance(info, dict) else []
    if not isinstance(files, list) or not files:
        return "", "", 0.0, "sin_lista_archivos"

    terms = list(wanted_terms if wanted_terms is not None else query_terms_for_match())
    if not terms and wanted_title:
        terms = query_terms_for_match(wanted_title)

    candidates = []
    fallback_videos = []
    total_files = len(files)
    total_gb = 0.0
    title_ratio, title_hits = _match_ratio(terms, wanted_title or "")
    min_video_gb = float(CONFIG.get("pack_min_video_gb", 0.3) or 0.3)
    fallback_min_gb = max(min_video_gb, float(CONFIG.get("pack_title_fallback_min_video_gb", 1.0) or 1.0), _current_min_size_gb())
    for f in files:
        path = _file_path(f)
        fid = _file_id(f)
        gb = _file_size_gb(f)
        total_gb += gb
        if not fid or not path:
            continue
        if CONFIG.get("pack_only_video_files", True) and not video_ext_ok(path):
            continue
        is_extra = _is_extra_video_path(path)
        if gb and gb < min_video_gb:
            continue
        if not is_extra and (gb or 0) >= fallback_min_gb:
            fallback_videos.append({"id": fid, "path": path, "gb": gb})
        ratio, hits = _match_ratio(terms, path)
        quality = score_result(Result(title=path, size_gb=gb), 0).score
        # Penaliza samples y extras.
        if is_extra:
            quality -= 100
        # En torrents con varios archivos, si hay términos claros de búsqueda,
        # el archivo elegido debe coincidir con la búsqueda; el tamaño solo decide entre coincidencias.
        is_multi_file = total_files > 1
        if is_multi_file and terms and ratio < float(CONFIG.get("pack_query_match_min_ratio", 0.55) or 0.55):
            continue
        # En torrents pequeños sin términos claros, el vídeo grande gana.
        score = quality + int(min(60, gb * 2)) + int(ratio * 120)
        candidates.append({"id": fid, "path": path, "gb": gb, "score": score, "ratio": ratio, "hits": hits})

    if not candidates:
        if (
            CONFIG.get("pack_allow_title_single_video_fallback", True)
            and terms
            and title_ratio >= 1.0
            and len(fallback_videos) == 1
        ):
            best = fallback_videos[0]
            note = (
                f"fallback_titulo_un_video={best['path']} | {best['gb']:.2f} GB | "
                f"hits_titulo={','.join(title_hits) or '-'} | files_total={total_files}"
            )
            return best["id"], best["path"], best["gb"], note
        # Si no hay candidato, NO seleccionar all: eso era lo peligroso.
        return "", "", 0.0, f"sin_candidato_video_pack files={total_files} terms={','.join(terms)}"

    candidates.sort(key=lambda x: (x["score"], x["gb"]), reverse=True)
    best = candidates[0]
    # Si hay varios trozos reales del mismo título, no hacemos inventos; elegimos el mejor vídeo.
    note = f"archivo_interno={best['path']} | {best['gb']:.2f} GB | hits={','.join(best['hits']) or '-'} | files_total={total_files}"
    return best["id"], best["path"], best["gb"], note

def _rd_status_blob(info):
    if not isinstance(info, dict):
        return ""
    parts = []
    for key in ("status", "error", "message", "warning"):
        value = info.get(key)
        if value:
            parts.append(str(value))
    return normalize(" | ".join(parts))

def _rd_info_seeders(info):
    if not isinstance(info, dict):
        return None
    for key in ("seeders", "seeds"):
        if key in info:
            try:
                return int(float(info.get(key) or 0))
            except Exception:
                return None
    return None

def _rd_info_progress(info):
    if not isinstance(info, dict):
        return 0.0
    try:
        return float(info.get("progress") or 0)
    except Exception:
        return 0.0

def rd_fast_discard_decision(info, candidate, stage):
    if not CONFIG.get("rd_fast_discard_enabled", True):
        return {"discard": False}
    if not isinstance(info, dict):
        return {"discard": False}
    links = info.get("links") or []
    if links:
        return {"discard": False}
    status_raw = str(info.get("status") or "").strip()
    status = normalize(status_raw)
    blob = _rd_status_blob(info)
    stage = str(stage or "").lower()
    if status == "waiting_files_selection":
        return {"discard": False, "needs_select_logic": True}
    if CONFIG.get("rd_fast_discard_dead_status_enabled", True):
        dead_status = {
            "magnet_error": ("RD_FAIL", "magnet_error"),
            "dead": ("RD_FAIL", "dead"),
            "virus": ("RD_FAIL", "virus"),
            "error": ("RD_FAIL", "error"),
            "corrupted": ("RD_FAIL", "corrupted"),
        }
        if status in dead_status:
            mapped_status, reason = dead_status[status]
            return {"discard": True, "reason": reason, "status": mapped_status, "delete_now": True, "stage": stage, "rd_status": status_raw}
    if CONFIG.get("rd_fast_discard_message_match_enabled", True):
        if "no seeders are available" in blob or "no seeders" in blob:
            return {"discard": True, "reason": "no_seeders", "status": "NO_INSTANT", "delete_now": True, "stage": stage, "rd_status": status_raw}
        if "invalid" in blob or status in {"invalid", "invalid_magnet"}:
            return {"discard": True, "reason": "invalid_magnet", "status": "NO_INSTANT", "delete_now": True, "stage": stage, "rd_status": status_raw}
        if "corrupted" in blob:
            return {"discard": True, "reason": "corrupted", "status": "RD_FAIL", "delete_now": True, "stage": stage, "rd_status": status_raw}
        if "magnet_error" in blob:
            return {"discard": True, "reason": "magnet_error", "status": "RD_FAIL", "delete_now": True, "stage": stage, "rd_status": status_raw}
        if " dead" in f" {blob} ":
            return {"discard": True, "reason": "dead", "status": "RD_FAIL", "delete_now": True, "stage": stage, "rd_status": status_raw}
        if " virus" in f" {blob} ":
            return {"discard": True, "reason": "virus", "status": "RD_FAIL", "delete_now": True, "stage": stage, "rd_status": status_raw}
        if " error" in f" {blob} ":
            return {"discard": True, "reason": "error", "status": "RD_FAIL", "delete_now": True, "stage": stage, "rd_status": status_raw}
    if CONFIG.get("rd_fast_discard_zero_progress_enabled", True) and stage == "post_select":
        progress = _rd_info_progress(info)
        seeders = _rd_info_seeders(info)
        useful_status = status in {"downloaded", "compressing", "uploading"} or progress >= 100.0
        if not useful_status and progress <= 0 and seeders in (None, 0):
            return {"discard": True, "reason": "zero_progress_post_select", "status": "NO_INSTANT", "delete_now": True, "stage": stage, "rd_status": status_raw}
    return {"discard": False}

def _rd_apply_fast_discard(r, tid, decision, token, idx=0, total=0, ctx=None):
    status = str(decision.get("status") or "RD_FAIL")
    reason = str(decision.get("reason") or "fast_discard")
    stage = str(decision.get("stage") or "")
    delete_now = bool(decision.get("delete_now", True))
    r.rd_status = status
    if reason == "waiting_files_no_match":
        r.reason = "Pack/torrent sin archivo interno seguro: " + str(decision.get("note") or "")
        r.pack_note = str(decision.get("note") or "")
    elif reason == "zero_progress_post_select":
        r.reason = "Descartado rapido RD: post-select sin links ni progreso util"
    elif reason == "no_seeders":
        r.reason = "Descartado rapido RD: sin seeders disponibles"
    elif reason == "invalid_magnet":
        r.reason = "Descartado rapido RD: magnet invalido"
    else:
        r.reason = "Descartado rapido RD: " + reason
    if ctx and tid:
        ctx.record_failed(tid, reason)
    diag("rd_fast_discard", n=idx, total=total, id=tid, stage=stage, reason=reason, status=status, delete_now=delete_now, title=r.title[:160])
    diag("rd_fast_discard_reason", n=idx, total=total, id=tid, reason=reason, status=status, stage=stage)
    if delete_now and tid and CONFIG.get("cleanup_failed_verifications", True):
        diag("rd_fast_discard_delete", n=idx, total=total, id=tid, reason=reason, status=status)
        if reason == "waiting_files_no_match":
            diag("rd_waiting_files_no_match_fast_delete", n=idx, total=total, id=tid, note=str(decision.get("note") or "")[:500], title=r.title[:160])
        elif reason == "invalid_magnet":
            diag("rd_invalid_magnet_fast_delete", n=idx, total=total, id=tid, title=r.title[:160])
        elif reason == "no_seeders":
            diag("rd_no_seeders_fast_delete", n=idx, total=total, id=tid, title=r.title[:160])
        elif reason == "zero_progress_post_select":
            diag("rd_zero_progress_fast_delete", n=idx, total=total, id=tid, title=r.title[:160])
        rd_delete_torrent(tid, token, reason, release_slot=True)
    return r

def _rd_mark_verify_ok(r, tid, links, idx=0, total=0, ctx=None):
    r.rd_status = "RD_OK"
    r.rd_links = len(links)
    shown_size = r.selected_file_size_gb or r.size_gb or r.rd_largest_gb
    if r.selected_file_name:
        r.reason = f"Verificado con addMagnet: {len(links)} link(s). Archivo interno: {r.selected_file_name} ({shown_size:.1f} GB)"
        if "  ==>  " not in r.title:
            r.title = f"{r.title}  ==>  {r.selected_file_name}"
    else:
        r.reason = f"Verificado con addMagnet: {len(links)} link(s), {shown_size:.1f} GB" if shown_size else f"Verificado con addMagnet: {len(links)} link(s)"
    if ctx:
        ctx.record_ok(tid)
    diag("rd_verify_ok", n=idx, total=total, id=tid, links=len(links), size_gb=round(float(shown_size or 0), 3), selected_file=r.selected_file_name[:240], title=r.title[:220])
    return r

def rd_verify_by_addmagnet(r, token, idx=0, total=0, ctx=None):
    """
    Verificación seria v2.1:
    - Añade magnet a RD.
    - Si pide selección, NO selecciona todo.
    - En packs elige solo el archivo interno que coincide con la búsqueda.
    - Solo marca RD_OK cuando RD entrega link real.
    """
    cancel_checkpoint("rd_verify_by_addmagnet.before")
    if not r.magnet:
        r.rd_status = "SIN_MAGNET"
        r.reason = "No hay magnet para verificar"
        return r

    attempts = int(CONFIG.get("verify_wait_attempts", 1) or 1)
    wait_sec = float(CONFIG.get("verify_wait_sec", 0.25) or 0.25)
    tid = ""
    last_status = ""
    last_progress = None
    selected_once = False
    terms = list(getattr(ctx, "terms", None) or query_terms_for_match())
    reserved_for_add = False
    try:
        diag("rd_verify_add_start", n=idx, total=total, hash=r.hash, title=r.title[:160])
        existing = rd_find_existing_downloaded_by_hash(r.hash, token, ctx=ctx, terms=terms)
        if existing:
            if ctx:
                _score, item, info_existing, _path, _gb, _reason = existing
                ctx.record_existing(str(item.get("id") or info_existing.get("id") or ""))
            return rd_mark_existing_ok(r, existing, idx, total)
        res = None
        retries = max(1, int(CONFIG.get("rd_temp_error_retries", 3) or 3))
        retry_429_attempts = max(retries, int(CONFIG.get("rd_429_retry_attempts", 6) or 6))
        try:
            if ctx and ctx.slots and not reserved_for_add:
                ctx.slots.refresh(force=False)
                while not ctx.slots.try_reserve_for_add():
                    sleep_interruptible(float(CONFIG.get("rd_active_slots_wait_sec", 0.35) or 0.35), where="rd_active_slots_wait")
                    ctx.slots.refresh(force=True)
                reserved_for_add = True
            cancel_checkpoint("rd_verify_by_addmagnet.before_add")
            res = rd_call_with_retry("POST", "/torrents/addMagnet", token, data={"magnet": r.magnet}, op_name="addMagnet", attempts=retries, retry_context=ctx, retry_429_attempts=retry_429_attempts)
            if ctx and ctx.slots and reserved_for_add:
                ctx.slots.on_add_success()
                reserved_for_add = False
        except RDAPIError as e:
            if ctx and ctx.slots and reserved_for_add:
                ctx.slots.on_add_failure()
                reserved_for_add = False
            if e.is_already_active and CONFIG.get("rd_retry_33_resolve_existing", True):
                diag("rd_verify_already_active", n=idx, total=total, hash=r.hash, title=r.title[:120])
                if ctx and ctx.existing:
                    try:
                        ctx.existing.refresh_active_only()
                        found = ctx.existing.find_downloaded_by_hash(r.hash, terms=terms)
                        if found:
                            return rd_mark_existing_ok(r, found, idx, total)
                        active = ctx.existing.find_any_by_hash(r.hash)
                        if active:
                            item, _info = active
                            tid = str(item.get("id") or "")
                            if tid:
                                res = {"id": tid}
                                diag("rd_verify_already_active_resolved", n=idx, total=total, id=tid, hash=r.hash)
                    except Exception as lookup_error:
                        diag("rd_verify_already_active_lookup_error", n=idx, total=total, error=str(lookup_error)[:300], hash=r.hash)
            elif e.is_infringing:
                r.rd_status = "RD_FAIL"
                r.reason = "Real-Debrid rechaza este torrent por infraccion o bloqueo legal"
                diag("rd_verify_infringing", n=idx, total=total, code=e.status_code, error_code=e.error_code, title=r.title[:160])
                return r
            elif _is_rd_temp_error_msg(e) or e.is_active_limit:
                return _mark_rd_temp_error(r, e, idx, total, tid)
            else:
                raise
        except Exception as e:
            if ctx and ctx.slots and reserved_for_add:
                ctx.slots.on_add_failure()
                reserved_for_add = False
            if _is_rd_temp_error_msg(e):
                return _mark_rd_temp_error(r, e, idx, total, tid)
            raise
        if not isinstance(res, dict) or not res.get("id"):
            raise RuntimeError(f"addMagnet sin id: {res}")
        tid = str(res.get("id"))
        r.rd_torrent_id = tid
        if ctx:
            ctx.record_temp(tid, "addMagnet", r)
        diag("rd_verify_added", n=idx, total=total, id=tid, hash=r.hash)
        visible_pause = max(0.0, float(CONFIG.get("rd_visible_pause_after_add_sec", 0) or 0))
        if visible_pause:
            sleep_interruptible(visible_pause, where="rd_visible_pause_after_add")

        for attempt in range(1, attempts + 1):
            cancel_checkpoint("rd_verify_by_addmagnet.poll")
            info = rd_call_with_retry("GET", f"/torrents/info/{tid}", token, op_name="existing_info", attempts=3, retry_context=get_rd_runtime(), retry_429_attempts=retry_429_attempts)
            if not isinstance(info, dict):
                raise RuntimeError(f"info inesperada: {info}")
            status = str(info.get("status") or "")
            progress = info.get("progress")
            links = info.get("links") or []
            last_status = status
            last_progress = progress
            files_count, size_gb = _rd_size_from_info(info)
            if files_count:
                r.rd_files = files_count
                r.is_pack = files_count > 20
            if size_gb and not r.selected_file_size_gb:
                r.rd_largest_gb = size_gb
                if not r.size_gb:
                    r.size_gb = size_gb

            diag(
                "rd_verify_poll",
                n=idx,
                total=total,
                id=tid,
                attempt=attempt,
                status=status,
                progress=progress,
                links=len(links) if isinstance(links, list) else 0,
                files=files_count,
                size_gb=round(float(size_gb or 0), 3),
                selected_file=r.selected_file_name[:180],
                selected_size_gb=round(float(r.selected_file_size_gb or 0), 3),
                title=r.title[:120],
            )

            decision = rd_fast_discard_decision(info, r, stage="initial")
            if decision.get("discard"):
                return _rd_apply_fast_discard(r, tid, decision, token, idx, total, ctx=ctx)

            if status == "waiting_files_selection" and not selected_once:
                ids, fname, fgb, note = choose_internal_files(info, r.title, wanted_terms=terms)
                if not ids:
                    diag("rd_verify_pack_skip", id=tid, n=idx, note=note, title=r.title[:160])
                    return _rd_apply_fast_discard(
                        r,
                        tid,
                        {
                            "discard": True,
                            "reason": "waiting_files_no_match",
                            "status": "PACK_SIN_COINCIDENCIA",
                            "delete_now": True,
                            "stage": "waiting_files_selection",
                            "note": note,
                        },
                        token,
                        idx,
                        total,
                        ctx=ctx,
                    )
                r.selected_file_ids = ids
                r.selected_file_name = fname
                r.selected_file_size_gb = fgb
                r.size_gb = fgb or r.size_gb
                r.rd_largest_gb = fgb or r.rd_largest_gb
                r.pack_note = note
                try:
                    cancel_checkpoint("rd_verify_by_addmagnet.before_select")
                    rd_call_with_retry("POST", f"/torrents/selectFiles/{tid}", token, data={"files": ids}, op_name="selectFiles", attempts=retries, retry_context=ctx, retry_429_attempts=retry_429_attempts)
                    selected_once = True
                    diag("rd_verify_select_files", id=tid, n=idx, files=ids, file_name=fname[:240], file_size_gb=round(float(fgb or 0), 3), note=note[:500])
                except Exception as e:
                    diag("rd_verify_select_error", id=tid, n=idx, error=str(e)[:300])
                    raise
                post_wait = float(CONFIG.get("rd_post_select_poll_sec", 0.25) or 0.25)
                sleep_interruptible(post_wait, where="rd_post_select_poll")
                if CONFIG.get("rd_post_select_extra_poll_enabled", True):
                    info2 = rd_call_with_retry("GET", f"/torrents/info/{tid}", token, op_name="info_post_select", attempts=retries, retry_context=ctx, retry_429_attempts=retry_429_attempts)
                    if isinstance(info2, dict):
                        status2 = str(info2.get("status") or "")
                        progress2 = info2.get("progress")
                        links2 = info2.get("links") or []
                        last_status = status2
                        last_progress = progress2
                        files_count2, size_gb2 = _rd_size_from_info(info2)
                        if files_count2:
                            r.rd_files = files_count2
                            r.is_pack = files_count2 > 20
                        if size_gb2 and not r.selected_file_size_gb:
                            r.rd_largest_gb = size_gb2
                            if not r.size_gb:
                                r.size_gb = size_gb2
                        diag(
                            "rd_verify_post_select_poll",
                            n=idx,
                            total=total,
                            id=tid,
                            status=status2,
                            progress=progress2,
                            links=len(links2) if isinstance(links2, list) else 0,
                            files=files_count2,
                            size_gb=round(float(size_gb2 or 0), 3),
                            selected_file=r.selected_file_name[:180],
                            title=r.title[:120],
                        )
                        if links2 and (status2 in ("downloaded", "compressing", "uploading") or str(progress2) in ("100", "100.0")):
                            return _rd_mark_verify_ok(r, tid, links2, idx, total, ctx=ctx)
                        decision2 = rd_fast_discard_decision(info2, r, stage="post_select")
                        if decision2.get("discard"):
                            return _rd_apply_fast_discard(r, tid, decision2, token, idx, total, ctx=ctx)
                        if status2 in ("magnet_error", "error", "virus", "dead"):
                            r.rd_status = "RD_FAIL"
                            r.reason = f"Real-Debrid no lo acepta: {status2}"
                            if ctx:
                                ctx.record_failed(tid, "fallo_post_select")
                            if CONFIG.get("cleanup_failed_verifications", True):
                                rd_delete_torrent(tid, token, "fallo_post_select", release_slot=True)
                            return r
                continue

            if links and (status in ("downloaded", "compressing", "uploading") or str(progress) in ("100", "100.0")):
                return _rd_mark_verify_ok(r, tid, links, idx, total, ctx=ctx)

            if status in ("magnet_error", "error", "virus", "dead"):
                r.rd_status = "RD_FAIL"
                r.reason = f"Real-Debrid no lo acepta: {status}"
                if ctx:
                    ctx.record_failed(tid, "fallo")
                if CONFIG.get("cleanup_failed_verifications", True):
                    rd_delete_torrent(tid, token, "fallo", release_slot=True)
                return r

            sleep_interruptible(wait_sec, where="rd_verify_wait")

        r.rd_status = "NO_INSTANT"
        r.reason = f"No entrega link instantáneo. Estado: {last_status}, progreso: {last_progress}"
        if ctx:
            ctx.record_failed(tid, "no_instant")
        if CONFIG.get("cleanup_failed_verifications", True):
            rd_delete_torrent(tid, token, "no_instant", release_slot=True)
        diag("rd_verify_not_instant", n=idx, total=total, id=tid, status=last_status, progress=last_progress, selected_file=r.selected_file_name[:240], title=r.title[:160])
        return r

    except UserCancelled:
        if ctx and tid:
            ctx.record_failed(tid, "cancelled")
        if tid and CONFIG.get("cleanup_failed_verifications", True):
            with non_cancelable_cleanup():
                rd_delete_torrent(tid, token, "cancelled", release_slot=True)
        raise
    except Exception as e:
        if _is_rd_temp_error_msg(e):
            if ctx and tid:
                ctx.record_failed(tid, "rd_temp_error")
            if tid and CONFIG.get("cleanup_failed_verifications", True):
                rd_delete_torrent(tid, token, "rd_temp_error", release_slot=True)
            return _mark_rd_temp_error(r, e, idx, total, tid)
        r.rd_status = "RD_ERROR"
        r.reason = str(e)[:500]
        if ctx and tid:
            ctx.record_failed(tid, "error")
        if tid and CONFIG.get("cleanup_failed_verifications", True):
            rd_delete_torrent(tid, token, "error", release_slot=True)
        diag("rd_verify_error", n=idx, total=total, id=tid, error=str(e)[:500], title=r.title[:160])
        return r

def rd_verify_by_torrent_url(r, token, idx=0, total=0):
    """
    Verifica un enlace .torrent real con Real-Debrid.
    Solo marca RD_OK cuando addTorrent + selectFiles + unrestrict entregan enlaces.
    """
    if not r.torrent_url:
        r.rd_status = "SIN_TORRENT"
        r.reason = "No hay URL .torrent para verificar"
        return r
    tid = ""
    try:
        diag("rd_verify_torrent_url_start", n=idx, total=total, url=r.torrent_url[:240], title=r.title[:160])
        raw = download_binary(r.torrent_url)
        if not raw or len(raw) < 32:
            raise RuntimeError("El .torrent descargado está vacío o es demasiado pequeño")
        res = rd_api("PUT", "/torrents/addTorrent", token, raw=raw, content_type="application/x-bittorrent")
        if not isinstance(res, dict) or not res.get("id"):
            raise RuntimeError(f"addTorrent sin id: {res}")
        tid = str(res.get("id"))
        r.rd_torrent_id = tid
        downloads = rd_torrent_id_to_downloads(tid, token, r.selected_file_ids, r.title)
        if not downloads:
            raise RuntimeError("Real-Debrid no entregó enlaces descargables")
        r.rd_status = "RD_OK"
        r.rd_links = len(downloads)
        r.reason = f"Verificado con addTorrent: {len(downloads)} enlace(s) descargable(s)"
        diag("rd_verify_torrent_url_ok", n=idx, total=total, id=tid, links=len(downloads), title=r.title[:160])
        return r
    except Exception as e:
        msg = str(e)[:500]
        if _is_rd_temp_error_msg(msg):
            _mark_rd_temp_error(r, msg, idx, total, tid)
            if tid and CONFIG.get("cleanup_failed_verifications", True):
                rd_delete_torrent(tid, token, "torrent_url_temp_error")
            diag("rd_verify_torrent_url_error", n=idx, total=total, id=tid, error=msg, title=r.title[:160])
            return r
        if "Sin links" in msg or "todavía" in msg or "todavia" in msg:
            r.rd_status = "NO_INSTANT"
        else:
            r.rd_status = "RD_ERROR"
        r.reason = msg
        if tid and CONFIG.get("cleanup_failed_verifications", True):
            rd_delete_torrent(tid, token, "torrent_url_error")
        diag("rd_verify_torrent_url_error", n=idx, total=total, id=tid, error=msg, title=r.title[:160])
        return r

def _rd_build_batch_context(token, batch):
    ctx = RDVerifyBatchContext(
        token=token,
        batch=batch,
        slots=RDActiveSlotsController(token),
        existing=RDExistingIndex(token),
        terms=query_terms_for_match(),
    )
    try:
        if ctx.slots.enabled:
            ctx.slots.refresh(force=True)
            diag("rd_active_count_before", **ctx.slots.snapshot())
    except Exception as e:
        diag("rd_slots_refresh_error", error=str(e)[:300])
    try:
        if CONFIG.get("rd_existing_preload_enabled", True):
            ctx.existing.preload()
    except Exception as e:
        diag("rd_existing_preload_error", error=str(e)[:300])
    return ctx


def rd_emit_rate_summary(label=""):
    if not CONFIG.get("rd_diag_rate_wait_summary_enabled", True):
        return
    with RD_RUNTIME_LOCK:
        limiter = RD_RATE_LIMITER
    if limiter:
        diag("rd_rate_summary", label=label, **limiter.snapshot())
    rd_emit_endpoint_pacer_summary(label)


def _rd_cleanup_final_impl(ctx, token):
    if not ctx or not CONFIG.get("rd_final_cleanup_enabled", True):
        return
    attempts = max(1, int(CONFIG.get("rd_final_cleanup_attempts", 3) or 3))
    wait_sec = max(0.0, float(CONFIG.get("rd_final_cleanup_wait_sec", 1.5) or 1.5))
    with ctx.lock:
        resolved = (set(ctx.cleanup_deleted) | set(ctx.cleanup_missing)) if CONFIG.get("rd_cleanup_final_skip_already_deleted", True) else set()
        candidates = sorted(((set(ctx.temp_ids) | set(ctx.failed_ids)) - resolved | set(ctx.cleanup_pending.keys())) - set(ctx.ok_ids) - set(ctx.existing_ids))
    diag("rd_cleanup_final_start", total=len(candidates), context=ctx.snapshot())
    for tid in candidates:
        if not tid:
            continue
        resolved = False
        pending_meta = ctx.cleanup_pending.get(tid, {}) if isinstance(ctx.cleanup_pending, dict) else {}
        release_slot = bool(pending_meta.get("release_slot", True))
        why = str(pending_meta.get("why") or ctx.temp_meta.get(tid, {}).get("reason") or "cleanup_final")
        for attempt in range(1, attempts + 1):
            try:
                info = rd_call_with_retry("GET", f"/torrents/info/{tid}", token, op_name="cleanup_info", attempts=2, retry_context=ctx)
                status = str((info or {}).get("status") or "") if isinstance(info, dict) else ""
                diag("rd_cleanup_final_leftover", id=tid, attempt=attempt, status=status, why=why)
            except RDAPIError as e:
                if e.status_code == 404:
                    ctx.record_cleanup_done(tid, "missing")
                    diag("rd_cleanup_final_missing", id=tid, attempt=attempt, why=why)
                    resolved = True
                    break
                diag("rd_cleanup_final_retry", id=tid, attempt=attempt, code=e.status_code, error_code=e.error_code, error=str(e)[:260])
                if attempt < attempts:
                    time.sleep(wait_sec)
                continue
            except Exception as e:
                diag("rd_cleanup_final_retry", id=tid, attempt=attempt, error=str(e)[:260])
                if attempt < attempts:
                    time.sleep(wait_sec)
                continue

            ok = rd_delete_torrent(tid, token, f"cleanup_final:{why}", release_slot=release_slot)
            diag("rd_cleanup_final_delete", id=tid, attempt=attempt, ok=bool(ok), why=why)
            if attempt < attempts:
                time.sleep(wait_sec)

        if resolved:
            continue
        try:
            rd_call_with_retry("GET", f"/torrents/info/{tid}", token, op_name="cleanup_verify", attempts=2, retry_context=ctx)
            with ctx.lock:
                ctx.cleanup_leftover.add(tid)
            diag("rd_cleanup_final_leftover", id=tid, final=True, why=why)
        except RDAPIError as e:
            if e.status_code == 404:
                ctx.record_cleanup_done(tid, "missing")
                diag("rd_cleanup_final_missing", id=tid, final=True, why=why)
            else:
                with ctx.lock:
                    ctx.cleanup_leftover.add(tid)
                diag("rd_cleanup_final_leftover", id=tid, final=True, code=e.status_code, error_code=e.error_code, why=why)
        except Exception as e:
            with ctx.lock:
                ctx.cleanup_leftover.add(tid)
            diag("rd_cleanup_final_leftover", id=tid, final=True, error=str(e)[:260], why=why)
    try:
        if ctx.slots.enabled:
            ctx.slots.refresh(force=True)
            diag("rd_active_count_after", **ctx.slots.snapshot())
    except Exception as e:
        diag("rd_active_count_after_error", error=str(e)[:300])
    diag("rd_cleanup_final_end", **ctx.snapshot())
    rd_emit_rate_summary("cleanup_final")


def rd_cleanup_final(ctx, token):
    with non_cancelable_cleanup():
        return _rd_cleanup_final_impl(ctx, token)


def rd_verify_addmagnet_queue(batch, token, maxv):
    summary = {}
    if not batch:
        return summary
    workers = max(1, int(CONFIG.get("rd_verify_parallel_workers", 1) or 1))
    workers = min(workers, len(batch))
    ctx = _rd_build_batch_context(token, batch)
    set_rd_runtime(ctx)
    started = time.monotonic()
    diag(
        "rd_verify_queue_start",
        verifying=len(batch),
        workers=workers,
        slots=ctx.slots.snapshot(),
        terms=",".join(ctx.terms),
        config={
            "verify_max_candidates": CONFIG.get("verify_max_candidates"),
            "rd_verify_parallel_workers": CONFIG.get("rd_verify_parallel_workers"),
            "verify_wait_attempts": CONFIG.get("verify_wait_attempts"),
            "verify_wait_sec": CONFIG.get("verify_wait_sec"),
            "rd_temp_error_retries": CONFIG.get("rd_temp_error_retries"),
            "rd_429_retry_attempts": CONFIG.get("rd_429_retry_attempts"),
            "rd_api_rate_limit_per_min": CONFIG.get("rd_api_rate_limit_per_min"),
            "rd_api_rate_limit_burst": CONFIG.get("rd_api_rate_limit_burst"),
            "rd_api_429_cooldown_sec": CONFIG.get("rd_api_429_cooldown_sec"),
        },
    )
    done_count = 0
    next_index = 0
    active = {}
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            while next_index < len(batch) or active:
                while next_index < len(batch) and len(active) < workers:
                    cancel_checkpoint("rd_verify_queue.submit")
                    cand = batch[next_index]
                    idx = next_index + 1
                    fut = ex.submit(rd_verify_by_addmagnet, cand, token, idx, maxv, ctx)
                    active[fut] = (idx, cand)
                    diag("rd_verify_queue_submit", n=idx, total=maxv, active=len(active), title=cand.title[:120])
                    next_index += 1
                done, _pending = wait(active, timeout=0.25, return_when=FIRST_COMPLETED)
                cancel_checkpoint("rd_verify_queue.wait")
                if not done:
                    continue
                for fut in done:
                    idx, cand = active.pop(fut)
                    done_count += 1
                    try:
                        fut.result()
                    except Exception as e:
                        cand.rd_status = "RD_ERROR"
                        cand.reason = str(e)[:500]
                        diag("rd_verify_queue_worker_error", n=idx, title=cand.title[:120], error=str(e)[:400])
                    summary[cand.rd_status] = summary.get(cand.rd_status, 0) + 1
                    display_name = _result_display_name(cand)[:100]
                    if cand.rd_status == "RD_OK":
                        print(f"  RD OK {idx}/{maxv}: {display_name}")
                    else:
                        print(f"  Verificando {idx}/{maxv}: {display_name}")
                    diag(
                        "rd_verify_queue_done_item",
                        n=idx,
                        total=maxv,
                        done=done_count,
                        status=cand.rd_status,
                        active=len(active),
                        slots=ctx.slots.snapshot(),
                        title=cand.title[:120],
                    )
        diag(
            "rd_verify_queue_end",
            **summary,
            verifying=len(batch),
            workers=workers,
            seconds=round(time.monotonic() - started, 2),
            slots=ctx.slots.snapshot(),
            context=ctx.snapshot(),
        )
        rd_emit_rate_summary("queue_end")
        return summary
    finally:
        try:
            with non_cancelable_cleanup():
                rd_cleanup_final(ctx, token)
        except Exception as e:
            diag("rd_cleanup_final_error", error=str(e)[:500])
        clear_rd_runtime()


def rd_verify_addmagnet_batch(rd_candidates, token, maxv):
    """
    Verifica magnets con addMagnet sin saltarse candidatos.
    Paralelismo moderado: acelera el lote, pero mantiene el mismo criterio serio.
    """
    maxv = min(len(rd_candidates), int(maxv or 0))
    batch = rd_candidates[:maxv]
    summary = {}
    if not batch:
        return summary
    if CONFIG.get("rd_verify_queue_enabled", False):
        summary = rd_verify_addmagnet_queue(batch, token, maxv)
        for cand in rd_candidates[maxv:]:
            cand.rd_status = "NO_VERIFICADO"
            cand.reason = "No verificado por limite de seguridad"
            summary[cand.rd_status] = summary.get(cand.rd_status, 0) + 1
        return summary

    workers = max(1, int(CONFIG.get("rd_verify_parallel_workers", 1) or 1))
    workers = min(workers, len(batch))
    if workers <= 1:
        for j, cand in enumerate(batch, 1):
            cancel_checkpoint("rd_verify_batch.item")
            print(f"  Verificando {j}/{maxv}: {_result_display_name(cand)[:100]}")
            rd_verify_by_addmagnet(cand, token, j, maxv)
            summary[cand.rd_status] = summary.get(cand.rd_status, 0) + 1
            sleep_interruptible(float(CONFIG.get("delay_between_rd_checks_sec", 0.0)), where="rd_verify_batch.delay")
    else:
        print(f"  Verificacion RD en paralelo prudente: {workers} a la vez.")
        diag("rd_verify_batch_parallel_start", verifying=maxv, workers=workers)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {
                ex.submit(rd_verify_by_addmagnet, cand, token, j, maxv): (j, cand)
                for j, cand in enumerate(batch, 1)
            }
            done = 0
            for fut in as_completed(futs):
                cancel_checkpoint("rd_verify_batch.worker")
                j, cand = futs[fut]
                done += 1
                try:
                    fut.result()
                except Exception as e:
                    cand.rd_status = "RD_ERROR"
                    cand.reason = str(e)[:500]
                    diag("rd_verify_batch_worker_error", n=j, title=cand.title[:120], error=str(e)[:400])
                summary[cand.rd_status] = summary.get(cand.rd_status, 0) + 1
                if cand.rd_status == "RD_OK":
                    print(f"  RD OK {j}/{maxv}: {_result_display_name(cand)[:100]}")
                elif done == len(batch) or done % workers == 0:
                    print(f"  RD comprobados: {done}/{len(batch)}")
        diag("rd_verify_batch_parallel_end", **summary, verifying=maxv, workers=workers)

    for cand in rd_candidates[maxv:]:
        cand.rd_status = "NO_VERIFICADO"
        cand.reason = "No verificado por limite de seguridad"
        summary[cand.rd_status] = summary.get(cand.rd_status, 0) + 1
    return summary

def rd_instant_disabled_cached():
    with RD_RUNTIME_LOCK:
        return bool(RD_INSTANT_DISABLED_UNTIL and time.time() < RD_INSTANT_DISABLED_UNTIL)


def rd_mark_instant_disabled(error_text=""):
    global RD_INSTANT_DISABLED_UNTIL
    ttl = max(0, int(CONFIG.get("rd_instant_disabled_cache_ttl_sec", 900) or 0))
    with RD_RUNTIME_LOCK:
        RD_INSTANT_DISABLED_UNTIL = time.time() + ttl if ttl else 0.0
        until = RD_INSTANT_DISABLED_UNTIL
    diag("rd_cache_api_disabled_cached_set", ttl_sec=ttl, until=round(until, 3), error=str(error_text)[:500])


def _rd_batchable_magnet_candidates(candidates):
    blocked = {"TORRENT_NO_VALIDO", "DIRECT_NO_VALIDO", "DIRECT_ERROR", "RD_OK", "RD_INSTANT"}
    return [r for r in candidates if getattr(r, "magnet", "") and getattr(r, "rd_status", "") not in blocked]


def _rd_verify_batch_when_instant_api_off(rd_candidates, token, summary, cached_disabled=False):
    if CONFIG.get("verify_candidates_when_api_off", True):
        batch_candidates = _rd_batchable_magnet_candidates(rd_candidates)
        maxv = min(len(batch_candidates), int(CONFIG.get("verify_max_candidates", 30) or 30))
        print(f"Paso serio: verifico de verdad con addMagnet los {maxv} mejores candidatos.")
        diag("rd_verify_batch_start", total=len(batch_candidates), verifying=maxv, cached_disabled=bool(cached_disabled))
        batch_summary = rd_verify_addmagnet_batch(batch_candidates, token, maxv)
        for k, v in batch_summary.items():
            summary[k] = summary.get(k, 0) + v
        diag("rd_verify_batch_end", **summary, total=len(rd_candidates), cached_disabled=bool(cached_disabled))
        return

    for cand in rd_candidates:
        cand.rd_status = "RD_API_OFF"
        cand.reason = "Real-Debrid tiene desactivada instantAvailability"


def rd_check_availability(results, token):
    cancel_checkpoint("rd_check_availability.before")
    validate_direct_links(results)
    materialize_torrent_candidates(results)
    rd_candidates = [r for r in results if not _is_direct_candidate_result(r)]
    if not rd_candidates:
        diag("rd_check_skipped", reason="solo_enlaces_directos", total=len(results))
        return results

    if not token:
        print("\nAVISO: No hay token en rd_token.txt. No puedo consultar Real-Debrid.")
        for r in rd_candidates:
            r.rd_status = "SIN_TOKEN"
            r.reason = "No hay token en rd_token.txt"
        diag("rd_check_skipped", reason="sin_token", total=len(results))
        return results

    print("\nComprobando token Real-Debrid...")
    ok_token, token_error = rd_token_healthcheck(token)
    if not ok_token:
        print("\nReal-Debrid no acepta el token o no responde.")
        print(f"Detalle: {token_error[:250]}")
        for r in rd_candidates:
            r.rd_status = "RD_TOKEN_ERROR"
            r.reason = token_error[:500]
        diag("rd_check_aborted", reason="token_error", error=token_error[:500], total=len(results))
        return results

    print("\nConsultando Real-Debrid cache/instantáneo...")
    diag("rd_check_start", total=len(rd_candidates))
    summary = {"RD_INSTANT": 0, "NO_CACHE": 0, "SIN_HASH": 0, "RD_ERROR": 0, "RD_ERROR_TEMPORAL": 0, "RD_API_OFF": 0, "RD_OK": 0, "NO_INSTANT": 0, "RD_FAIL": 0, "TORRENT_NO_VALIDO": 0, "NO_VERIFICADO": 0}
    first_error = ""
    torrent_checks = 0
    max_torrent_checks = int(CONFIG.get("verify_max_candidates", 30) or 30)

    for i, r in enumerate(rd_candidates, 1):
        cancel_checkpoint("rd_check_availability.item")
        if r.rd_status in ("TORRENT_NO_VALIDO", "DIRECT_NO_VALIDO", "DIRECT_ERROR"):
            summary[r.rd_status] = summary.get(r.rd_status, 0) + 1
            continue
        if r.torrent_url:
            if torrent_checks >= max_torrent_checks:
                r.rd_status = "NO_VERIFICADO"
                r.reason = "No verificado por límite de seguridad de .torrent"
                summary[r.rd_status] = summary.get(r.rd_status, 0) + 1
                continue
            torrent_checks += 1
            print(f"  Verificando .torrent {torrent_checks}/{max_torrent_checks}: {r.title[:100]}")
            rd_verify_by_torrent_url(r, token, torrent_checks, max_torrent_checks)
            summary[r.rd_status] = summary.get(r.rd_status, 0) + 1
            continue
        if not r.hash:
            r.rd_status = "SIN_HASH"
            r.reason = "No se pudo sacar hash del magnet/torrent"
            summary["SIN_HASH"] += 1
            continue
        if rd_instant_disabled_cached():
            first_error = first_error or "Real-Debrid instantAvailability desactivado en cache temporal"
            diag("rd_cache_api_disabled_cached_hit", checked=i, total=len(rd_candidates))
            print("\nAviso: Real-Debrid tiene instantAvailability desactivado; uso addMagnet directo.")
            _rd_verify_batch_when_instant_api_off(rd_candidates, token, summary, cached_disabled=True)
            break
        try:
            h = (r.hash or "").lower()
            data = rd_call_with_retry("GET", f"/torrents/instantAvailability/{h}", token, op_name="instantAvailability", attempts=2, retry_context=get_rd_runtime())
            root = None
            if isinstance(data, dict):
                root = data.get(h) or data.get(h.lower()) or data.get(h.upper())

            if root:
                r.rd_status = "RD_INSTANT"
                r.reason = "Cache instantánea confirmada por instantAvailability"
                total_files = 0
                largest = 0
                try:
                    for hoster, variants in root.items():
                        if not isinstance(variants, list):
                            continue
                        for variant in variants:
                            if isinstance(variant, dict):
                                total_files = max(total_files, len(variant))
                                total = 0
                                for _, meta in variant.items():
                                    if isinstance(meta, dict):
                                        total += int(meta.get("filesize") or 0)
                                largest = max(largest, total)
                except Exception as e:
                    diag("rd_instant_size_error", hash=h, error=str(e)[:300])
                r.rd_files = total_files
                r.rd_largest_gb = largest / (1024**3) if largest else 0.0
                if r.rd_largest_gb and not r.size_gb:
                    r.size_gb = r.rd_largest_gb
                if CONFIG.get("verify_instant_results_with_addmagnet", True):
                    diag("rd_instant_verify_addmagnet", n=i, total=len(rd_candidates), hash=h, title=r.title[:160])
                    rd_verify_by_addmagnet(r, token, i, len(rd_candidates))
                    summary[r.rd_status] = summary.get(r.rd_status, 0) + 1
                else:
                    summary["RD_INSTANT"] += 1
            else:
                r.rd_status = "NO_CACHE"
                r.reason = "Real-Debrid responde, pero no aparece cache instantánea para este hash"
                summary["NO_CACHE"] += 1

        except Exception as e:
            error_text = str(e)
            disabled_endpoint = (isinstance(e, RDAPIError) and e.is_disabled_endpoint) or "disabled_endpoint" in error_text or "error_code\": 37" in error_text or "error_code': 37" in error_text
            if disabled_endpoint:
                rd_mark_instant_disabled(error_text)
                first_error = first_error or error_text
                summary["RD_API_OFF"] = 0
                diag("rd_cache_api_disabled", error=error_text[:500], checked=i, total=len(rd_candidates))
                print("\nAviso: Real-Debrid tiene desactivada instantAvailability.")
                _rd_verify_batch_when_instant_api_off(rd_candidates, token, summary)
                break

            r.rd_status = "RD_ERROR"
            r.reason = error_text[:500]
            summary["RD_ERROR"] += 1
            first_error = first_error or error_text
            log(f"RD availability error {r.hash}: {error_text}")

        if CONFIG.get("diagnostic_rd_items", True):
            diag("rd_check_item", n=i, total=len(rd_candidates), status=r.rd_status, hash=r.hash, score=r.score, size_gb=round(float(r.size_gb or 0), 3), rd_largest_gb=round(float(r.rd_largest_gb or 0), 3), reason=(r.reason or "")[:500], title=r.title[:160])

        sleep_interruptible(float(CONFIG.get("delay_between_rd_checks_sec", 0.0)), where="rd_check_availability.delay")

    # Resumen real recalculado, porque en modo addMagnet se actualizan estados después.
    final = {}
    for r in results:
        final[r.rd_status] = final.get(r.rd_status, 0) + 1
    diag("rd_check_summary", **final, total=len(results), first_error=first_error[:500])
    print("\nResumen RD: " + " | ".join(f"{k}={v}" for k, v in sorted(final.items())))
    return results

def _is_working_status(status):
    return status in ("RD_OK", "RD_INSTANT", "DIRECT_OK")

def _is_useful_result(r):
    return _is_working_status(getattr(r, "rd_status", "")) or _is_qbt_working_status(getattr(r, "qbt_status", ""))


def _prepare_query_prefilter(scored):
    discarded_query = []
    rescue_query = []
    if not CONFIG.get("strict_query_prefilter", True):
        return list(scored), rescue_query, discarded_query

    before = len(scored)
    relevant = []
    for r in scored:
        cancel_checkpoint("prepare_results.prefilter")
        bucket = _query_relevance_bucket(r)
        if bucket == "primary":
            relevant.append(r)
        elif bucket == "rescue":
            rescue_query.append(r)
        else:
            discarded_query.append(r)
    diag(
        "prepare_after_query_prefilter",
        before=before,
        after=len(relevant),
        removed=len(discarded_query),
        rescue=len(rescue_query),
        terms=",".join(query_terms_for_match()),
    )
    print(f"Criba búsqueda seria: {len(relevant)}/{before} coinciden en el mismo título/archivo.")
    if rescue_query:
        print(f"Rescate RD pendiente por titulo/pack dudoso: {len(rescue_query)}")
    if discarded_query:
        print(f"Descartados antes de verificar por no coincidir: {len(discarded_query)}")
    return relevant, rescue_query, discarded_query


def prepare_results(results, mode, token):
    global LAST_QBIT_EXTRAS, LAST_RD_TEMP_ERRORS
    LAST_QBIT_EXTRAS = []
    LAST_RD_TEMP_ERRORS = []
    cancel_checkpoint("prepare_results.start")
    diag("prepare_results_start", incoming=len(results), mode=mode, min_size_gb=_current_min_size_gb())
    print(f"\nAspiradora terminada: {len(results)} resultados únicos encontrados.")
    scored = [score_result(r, mode) for r in results]
    diag("prepare_after_scoring", total=len(scored))
    if mode != 0:
        before = len(scored)
        scored = [r for r in scored if r.score > -500]
        diag("prepare_after_filter", before=before, after=len(scored), removed=before-len(scored))
        print(f"Filtro aplicado: {len(scored)}/{before} siguen como candidatos.")
    else:
        diag("prepare_after_filter", before=len(scored), after=len(scored), removed=0, mode="sin_filtro")
        print("Modo sin filtro: no descarto por idioma/calidad, pero SÍ ordeno por calidad.")

    # Criba seria antes de gastar tiempo en Real-Debrid/qBittorrent.
    # Evita Mercedes/Krawall/Mägo/etc cuando la búsqueda era Venganza 2008.
    discarded_size = []
    scored, rescue_query, discarded_query = _prepare_query_prefilter(scored)

    # Ordena antes de verificar, para gastar la comprobación seria en los mejores primero.
    scored, size_drop = _apply_current_min_size_filter(scored, "before_rd")
    discarded_size.extend(size_drop)

    cancel_checkpoint("prepare_results.before_rd")
    scored.sort(key=lambda r: (r.score, _effective_result_size_gb(r)), reverse=True)
    checked_core = rd_check_availability(scored, token)
    cancel_checkpoint("prepare_results.after_rd")
    checked_core, size_drop = _apply_current_min_size_filter(checked_core, "after_rd")
    if token and CONFIG.get("cleanup_failed_verifications", True):
        for r in size_drop:
            if r.rd_torrent_id and not getattr(r, "rd_existing", False):
                rd_delete_torrent(r.rd_torrent_id, token, "descartado_por_tamano")
    discarded_size.extend(size_drop)

    if CONFIG.get("rd_rescue_enabled", True) and rescue_query:
        cancel_checkpoint("prepare_results.before_rd_rescue")
        has_rd_ok = any(_is_working_status(r.rd_status) for r in checked_core)
        only_if_no_ok = bool(CONFIG.get("rd_rescue_only_if_no_rd_ok", True))
        rescue_allowed = (not only_if_no_ok) or (not has_rd_ok)
        rescue_candidates, size_drop = _apply_current_min_size_filter(rescue_query, "rescue_before_rd")
        discarded_size.extend(size_drop)
        rescue_candidates.sort(key=lambda r: (r.score, _effective_result_size_gb(r)), reverse=True)
        max_rescue = max(0, int(CONFIG.get("rd_rescue_max_candidates", 5) or 5))
        rescue_candidates = rescue_candidates[:max_rescue]
        if rescue_allowed and rescue_candidates:
            print(f"\nRescate RD: verifico {len(rescue_candidates)} candidatos dudosos fuertes.")
            diag("rd_rescue_start", total=len(rescue_candidates), only_if_no_ok=only_if_no_ok)
            rescue_checked = rd_check_availability(rescue_candidates, token)
            rescue_checked, size_drop = _apply_current_min_size_filter(rescue_checked, "rescue_after_rd")
            if token and CONFIG.get("cleanup_failed_verifications", True):
                for r in size_drop:
                    if r.rd_torrent_id and not getattr(r, "rd_existing", False):
                        rd_delete_torrent(r.rd_torrent_id, token, "rescate_descartado_por_tamano")
            discarded_size.extend(size_drop)
            checked_core.extend(rescue_checked)
            diag("rd_rescue_end", checked=len(rescue_checked))
        else:
            for r in rescue_query:
                r.rd_status = "RESCATE_NO_VERIFICADO"
                if not r.reason:
                    r.reason = "Rescate no verificado: ya habia resultado RD valido o no supera filtros."
            discarded_query.extend(rescue_query)

    # Segunda lista: torrents con vida por qBittorrent aunque NO sean directos por Real-Debrid/JDownloader.
    cancel_checkpoint("prepare_results.before_qbit")
    checked_core = qbt_probe_candidates(checked_core)
    LAST_QBIT_EXTRAS = sorted(
        [r for r in checked_core if _is_qbt_working_status(r.qbt_status) and not _is_working_status(r.rd_status)],
        key=lambda r: (r.score, r.qbt_size_gb or _effective_result_size_gb(r)),
        reverse=True,
    )
    LAST_RD_TEMP_ERRORS = sorted(
        [r for r in checked_core if r.rd_status == "RD_ERROR_TEMPORAL"],
        key=lambda r: (r.score, r.size_gb or r.rd_largest_gb),
        reverse=True,
    )
    diag("prepare_qbit_extras", total=len(LAST_QBIT_EXTRAS))
    diag("prepare_rd_temp_errors", total=len(LAST_RD_TEMP_ERRORS))

    checked_all = checked_core + discarded_size + (discarded_query if CONFIG.get("strict_query_prefilter_keep_discarded_in_exports", True) else [])
    checked = checked_core
    if CONFIG.get("hide_non_working_results", True) and (token or any(_is_direct_candidate_result(r) for r in checked_core)):
        before = len(checked_core)
        working = [r for r in checked_core if _is_useful_result(r)]
        rd_working = [r for r in working if _is_working_status(r.rd_status)]
        diag("prepare_after_working_filter", before=before, after=len(working), removed=before-len(working), qbit_extras=len(LAST_QBIT_EXTRAS), rd_valid=len(rd_working))
        print(f"Resultados válidos para JDownloader/RD: {len(rd_working)}/{before}", flush=True)
        print(f"Lista extra qBittorrent vivos reales: {len(LAST_QBIT_EXTRAS)}", flush=True)
        if LAST_RD_TEMP_ERRORS:
            print(f"Pendientes por error temporal RD (no se dan por muertos): {len(LAST_RD_TEMP_ERRORS)}", flush=True)
        checked = working

    checked.sort(key=lambda r: (1 if _is_working_status(r.rd_status) else 0, 1 if _is_qbt_working_status(r.qbt_status) else 0, r.score, _effective_result_size_gb(r)), reverse=True)
    cancel_checkpoint("prepare_results.before_export")
    export_results(checked_all, checked)
    return checked

def display_results(results):
    cancel_checkpoint("display_results.start")
    top_n = int(CONFIG.get("max_results_to_show", 30))
    shown = results[:top_n]
    print("\n" + "=" * 72)
    print(" TOP LIMPIO")
    print("=" * 72)
    if not shown:
        print("No hay resultados limpios.")
        if not LAST_QBIT_EXTRAS and not LAST_RD_TEMP_ERRORS:
            export_results(results, shown, write_all_json=False)
            return []
    for idx, r in enumerate(shown, 1):
        if r.rd_status == "RD_INSTANT":
            rd = "INSTANT"
        elif r.rd_status == "RD_OK":
            rd = "OK"
        elif r.rd_status == "DIRECT_OK":
            rd = "DIRECTO"
        elif r.rd_status == "TORRENT_PENDIENTE":
            rd = "TORRENT"
        elif r.rd_status == "NO_CACHE":
            rd = "NO_CACHE"
        elif r.rd_status == "RD_API_OFF":
            rd = "API_OFF"
        else:
            rd = r.rd_status
        size = f"{r.size_gb:.1f} GB" if r.size_gb else (f"{r.rd_largest_gb:.1f} GB" if r.rd_largest_gb else "? GB")
        title = r.title[:95]
        print(f"[{idx:02d}] RD:{rd:12} SCORE:{r.score:4d} SIZE:{size:>9}  {title}")
        if r.btdigg_file_name:
            bf_size = r.btdigg_file_size_gb or 0
            print(f"     archivo BTDigg: {r.btdigg_file_name[:100]} ({bf_size:.1f} GB)")
        if r.selected_file_name:
            sf_size = r.selected_file_size_gb or r.size_gb or 0
            print(f"     archivo RD: {r.selected_file_name[:108]} ({sf_size:.1f} GB)")
        if _is_qbt_working_status(r.qbt_status):
            print(f"     qBit vivo: {r.qbt_status} | seeds={r.qbt_seeds} peers={r.qbt_peers} | {r.qbt_reason[:90]}")
        if r.rd_status == "DIRECT_OK":
            print(f"     enlace: {r.source_url[:118]}")
        if r.torrent_url:
            print(f"     torrent: {r.torrent_url[:117]}")
        if r.tracker_name or r.tracker_seeders or r.tracker_leechers:
            print(f"     tracker: {r.tracker_name or '-'} | seeds={r.tracker_seeders} leechers={r.tracker_leechers} | {r.tracker_category or '-'}")
    shown_keys = set((r.hash or r.magnet or r.torrent_url or r.source_url) for r in shown)
    qbit_extra_display = [
        r for r in LAST_QBIT_EXTRAS
        if (r.hash or r.magnet or r.torrent_url or r.source_url) not in shown_keys
    ]
    if qbit_extra_display:
        print("=" * 72)
        print(" EXTRA QBITTORRENT VIVOS / NO DIRECTOS RD")
        print("=" * 72)
        for qidx, r in enumerate(qbit_extra_display[:int(CONFIG.get("max_results_to_show", 30))], 1):
            qsize = r.qbt_size_gb or r.size_gb or r.rd_largest_gb
            size = f"{qsize:.1f} GB" if qsize else "? GB"
            title = r.btdigg_file_name or r.selected_file_name or r.title
            print(f"[Q{qidx:02d}] QBT:{r.qbt_status:10} SIZE:{size:>9}  {title[:95]}")
            print(f"      {r.qbt_reason[:118]}")
        print("      Lista completa con magnets en: exports\\ULTIMO_QBIT_VIVOS.txt")
    if LAST_RD_TEMP_ERRORS:
        print("=" * 72)
        print(" PENDIENTES POR ERROR TEMPORAL RD  (NO confirmados, NO muertos)")
        print("=" * 72)
        for tidx, r in enumerate(LAST_RD_TEMP_ERRORS[:10], 1):
            tsize = r.size_gb or r.rd_largest_gb
            size = f"{tsize:.1f} GB" if tsize else "? GB"
            print(f"[T{tidx:02d}] RD:TEMPORAL SIZE:{size:>9}  {r.title[:95]}")
            print(f"      {r.reason[:118]}")
        print("      Lista completa con magnets en: exports\\ULTIMO_RD_TEMPORAL.txt")
    print("=" * 72)
    print("Elige: 1 | 1,4,7 | A=todos los válidos RD | T=todos mostrados RD/qBit | S=salir")
    export_results(results, shown, write_all_json=False)
    return shown

def prepare_quick_btdigg_results(results, mode):
    global LAST_QBIT_EXTRAS, LAST_RD_TEMP_ERRORS
    LAST_QBIT_EXTRAS = []
    LAST_RD_TEMP_ERRORS = []
    diag("quick_btdigg_prepare_start", incoming=len(results), mode=mode, min_size_gb=_current_min_size_gb())
    scored = [score_result(r, mode) for r in results]
    if mode != 0:
        before = len(scored)
        scored = [r for r in scored if r.score > -500]
        diag("quick_btdigg_after_mode_filter", before=before, after=len(scored), removed=before-len(scored))

    discarded = []
    if CONFIG.get("strict_query_prefilter", True):
        relevant = []
        for r in scored:
            if _result_relevant_to_current_query(r):
                relevant.append(r)
            else:
                discarded.append(r)
        scored = relevant

    scored, size_drop = _apply_current_min_size_filter(scored, "quick_btdigg")
    discarded.extend(size_drop)

    scored.sort(key=lambda r: (r.score, _effective_result_size_gb(r)), reverse=True)
    diag(
        "quick_btdigg_prepare_end",
        relevant=len(scored),
        discarded=len(discarded),
        terms=",".join(query_terms_for_match()),
    )
    return scored, discarded

def export_quick_btdigg_results(query, mode, relevant, discarded):
    if not CONFIG.get("write_exports", True):
        return
    try:
        txt_file = EXPORT_DIR / "ULTIMA_PRUEBA_BTDIGG.txt"
        json_file = EXPORT_DIR / "ULTIMA_PRUEBA_BTDIGG.json"
        rows = []
        for status, group in (("RELEVANTE", relevant), ("DESCARTADO", discarded)):
            for i, r in enumerate(group, 1):
                rows.append({
                    "grupo": status,
                    "n": i,
                    "title": r.title,
                    "hash": r.hash,
                    "size_gb": round(float(r.size_gb or 0), 3),
                    "score": r.score,
                    "btdigg_file_name": r.btdigg_file_name,
                    "btdigg_file_size_gb": round(float(r.btdigg_file_size_gb or 0), 3),
                    "same_file_match": r.same_file_match,
                    "same_file_reason": r.same_file_reason,
                    "reason": r.reason,
                    "raw_context": (getattr(r, "raw_context", "") or "")[:4000],
                    "magnet": r.magnet,
                    "source_url": r.source_url,
                })
        json_file.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

        lines = []
        lines.append("RD Turbo Pro - prueba rapida BTDigg")
        lines.append("=" * 80)
        lines.append(f"Busqueda: {query}")
        lines.append(f"Modo: {mode}")
        if _current_min_size_gb() > 0:
            lines.append(f"Minimo calidad: {_current_min_size_text()}")
        lines.append(f"Relevantes: {len(relevant)} | Descartados: {len(discarded)}")
        lines.append("")
        lines.append("CANDIDATOS RELEVANTES")
        lines.append("-" * 80)
        for i, r in enumerate(relevant[:int(CONFIG.get("max_results_to_show", 30))], 1):
            size = f"{(r.size_gb or r.btdigg_file_size_gb):.1f} GB" if (r.size_gb or r.btdigg_file_size_gb) else "? GB"
            lines.append(f"[{i:02d}] SCORE:{r.score:4d} SIZE:{size:>9} HASH:{r.hash}")
            lines.append(f"     {r.title}")
            if r.btdigg_file_name:
                lines.append(f"     ARCHIVO BTDIGG: {r.btdigg_file_name} ({(r.btdigg_file_size_gb or 0):.1f} GB)")
            lines.append(f"     CRIBA: {r.same_file_reason}")
            lines.append(f"     MAGNET: {r.magnet}")
            lines.append("")
        lines.append("DESCARTADOS POR CRIBA")
        lines.append("-" * 80)
        for i, r in enumerate(discarded[:50], 1):
            lines.append(f"[D{i:02d}] SCORE:{r.score:4d} HASH:{r.hash}")
            lines.append(f"      {r.title}")
            lines.append(f"      MOTIVO: {r.same_file_reason or r.reason[:220]}")
            lines.append("")
        txt_file.write_text("\n".join(lines), encoding="utf-8")
        diag("quick_btdigg_export", txt=str(txt_file), json=str(json_file), relevant=len(relevant), discarded=len(discarded))
    except Exception as e:
        log(f"export_quick_btdigg_results error: {e}")
        diag("quick_btdigg_export_error", error=str(e)[:300])

def display_quick_btdigg_results(relevant, discarded):
    top_n = int(CONFIG.get("max_results_to_show", 30))
    print("\n" + "=" * 72)
    print(" PRUEBA RAPIDA BTDIGG - SIN RD / SIN QBIT")
    print("=" * 72)
    print(f"Candidatos relevantes: {len(relevant)} | Descartados por criba: {len(discarded)}")
    shown = relevant[:top_n]
    if not shown:
        print("No hay candidatos relevantes para verificar.")
    for idx, r in enumerate(shown, 1):
        size = f"{(r.size_gb or r.btdigg_file_size_gb):.1f} GB" if (r.size_gb or r.btdigg_file_size_gb) else "? GB"
        print(f"[{idx:02d}] SCORE:{r.score:4d} SIZE:{size:>9}  {r.title[:95]}")
        if r.btdigg_file_name:
            print(f"     archivo BTDigg: {r.btdigg_file_name[:105]} ({(r.btdigg_file_size_gb or 0):.1f} GB)")
        if r.same_file_reason:
            print(f"     criba: {r.same_file_reason[:118]}")
    print("=" * 72)
    print("Exportado en: exports\\ULTIMA_PRUEBA_BTDIGG.txt")
    print("JSON completo: exports\\ULTIMA_PRUEBA_BTDIGG.json")

def select_results(shown):
    if not shown:
        return []
    choice = input("\nTu elección: ").strip().lower()
    if choice in ("s", "salir", "0", ""):
        return []
    if choice in ("a", "instant", "instantaneos", "validos", "valid"):
        valid = [r for r in shown if _is_working_status(r.rd_status)]
        if not valid:
            print("No hay resultados válidos en el TOP mostrado. Elige números concretos o T para todos los mostrados.")
        return valid
    if choice in ("t", "todos", "all"):
        return shown[:]
    selected = []
    for part in re.split(r"[,;\s]+", choice):
        if part and part.isdigit():
            idx = int(part)
            if 1 <= idx <= len(shown):
                selected.append(shown[idx - 1])
    out = []
    seen = set()
    for r in selected:
        k = r.hash or r.magnet or r.torrent_url or r.source_url
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out

def cleanup_unselected_verified(shown, selected, token):
    if not token or not CONFIG.get("cleanup_unselected_verified", True):
        return
    keep = set((r.rd_torrent_id or "") for r in selected)
    for r in shown:
        if getattr(r, "rd_existing", False):
            continue
        tid = r.rd_torrent_id or ""
        if tid and tid not in keep:
            rd_delete_torrent(tid, token, "no_seleccionado")

def convert_selected_to_download_links(selected, token):
    if not selected:
        return []
    needs_token = [
        r for r in selected
        if not (r.rd_status == "DIRECT_OK" and r.source_url)
        and not (_is_qbt_working_status(r.qbt_status) and r.magnet)
    ]
    if not token and needs_token:
        print("No hay token Real-Debrid. Edita rd_token.txt.")
        return []
    downloads = []
    for r in selected:
        print(f"\nPreparando: {r.title[:80]}")
        try:
            if _is_working_status(r.rd_status) and r.rd_torrent_id:
                downloads.extend(rd_torrent_id_to_downloads(r.rd_torrent_id, token, r.selected_file_ids, r.title))
            elif _is_working_status(r.rd_status) and r.magnet:
                downloads.extend(rd_magnet_to_downloads(r.magnet, token))
            elif _is_working_status(r.rd_status) and r.torrent_url:
                downloads.extend(rd_torrent_url_to_downloads(r.torrent_url, token))
            elif r.rd_status == "DIRECT_OK" and r.source_url:
                downloads.append(r.source_url)
            elif _is_qbt_working_status(r.qbt_status) and r.magnet:
                print("  qBit vivo confirmado: entrego magnet útil.")
                downloads.append(r.magnet)
            elif r.source_url:
                d = rd_unrestrict(r.source_url, token)
                if d:
                    downloads.append(d)
        except Exception as e:
            print(f"  ERROR: {e}")
            log(f"convert error {r.title}: {e}")
    return list(dict.fromkeys([x for x in downloads if x]))

def rd_magnet_to_downloads(magnet, token):
    res = rd_api("POST", "/torrents/addMagnet", token, data={"magnet": magnet})
    if not isinstance(res, dict) or not res.get("id"):
        raise RuntimeError(f"Respuesta inesperada addMagnet: {res}")
    tid = res["id"]
    print(f"  RD torrent id: {tid}")
    return rd_torrent_id_to_downloads(tid, token, "", magnet_title(magnet) or "")

def rd_torrent_url_to_downloads(url, token):
    raw = download_binary(url)
    res = rd_api("PUT", "/torrents/addTorrent", token, raw=raw, content_type="application/x-bittorrent")
    if not isinstance(res, dict) or not res.get("id"):
        raise RuntimeError(f"Respuesta inesperada addTorrent: {res}")
    return rd_torrent_id_to_downloads(res["id"], token, "", url.split("/")[-1])

def rd_torrent_id_to_downloads(tid, token, selected_ids="", wanted_title=""):
    info = None
    for attempt in range(1, 16):
        info = rd_api("GET", f"/torrents/info/{tid}", token)
        status = info.get("status") if isinstance(info, dict) else "?"
        links = info.get("links") if isinstance(info, dict) else []
        print(f"  Estado RD: {status} intento {attempt}/15")
        if isinstance(info, dict) and status == "waiting_files_selection":
            try:
                ids = selected_ids
                if not ids:
                    ids, fname, fgb, note = choose_internal_files(info, wanted_title)
                    if not ids:
                        raise RuntimeError("No selecciono todo el pack: " + note)
                    print(f"  Archivo interno seleccionado: {fname} ({fgb:.1f} GB)")
                rd_api("POST", f"/torrents/selectFiles/{tid}", token, data={"files": ids})
                print(f"  Archivos seleccionados: {ids}")
            except Exception as e:
                log(f"selectFiles warning {tid}: {e}")
                raise
        elif links:
            break
        sleep_interruptible(2, where="rd_select_all_pack.wait")
    if not isinstance(info, dict):
        raise RuntimeError("No pude leer info del torrent")
    links = info.get("links") or []
    if not links:
        raise RuntimeError(f"Sin links todavía. Estado: {info.get('status')}")
    downloads = []
    for link in links:
        d = rd_unrestrict(link, token)
        if d:
            downloads.append(d)
    return downloads

def rd_unrestrict(link, token):
    res = rd_api("POST", "/unrestrict/link", token, data={"link": link})
    if isinstance(res, dict):
        return res.get("download") or ""
    if isinstance(res, list):
        for item in res:
            if isinstance(item, dict) and item.get("download"):
                return item["download"]
    return ""

def download_binary(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 RD-Turbo-Pro/1.0"})
    with urlopen(req, timeout=int(CONFIG.get("request_timeout_sec", 20))) as resp:
        return resp.read()


def _run_powershell(command, timeout=12, sta=False):
    exe = "powershell"
    args = [exe, "-NoProfile"]
    if sta:
        args.append("-STA")
    args.extend(["-Command", command])
    try:
        r = subprocess.run(
            args,
            text=True,
            capture_output=True,
            timeout=timeout,
            encoding="utf-8",
            errors="ignore",
        )
        if r.returncode == 0:
            return r.stdout or ""
        log(f"powershell rc={r.returncode}: {r.stderr[:300] if r.stderr else ''}")
    except Exception as e:
        log(f"powershell error: {e}")
    return ""

def get_clipboard_text():
    """
    Lee el portapapeles en modo robusto:
    - Texto normal.
    - HTML Format de Windows, que suele conservar los href="magnet:..."
      aunque en pantalla el texto visible salga recortado.
    """
    if os.name != "nt":
        return ""

    raw = _run_powershell(
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Get-Clipboard -Raw",
        timeout=10,
        sta=False,
    )

    html_clip = _run_powershell(
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d=[System.Windows.Forms.Clipboard]::GetData('HTML Format'); "
        "if($null -ne $d){ [Console]::OutputEncoding=[System.Text.Encoding]::UTF8; [Console]::Write($d) }",
        timeout=10,
        sta=True,
    )

    unicode_text = _run_powershell(
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d=[System.Windows.Forms.Clipboard]::GetText(); "
        "if($null -ne $d){ [Console]::OutputEncoding=[System.Text.Encoding]::UTF8; [Console]::Write($d) }",
        timeout=10,
        sta=True,
    )

    diag("clipboard_read", raw_chars=len(raw or ""), html_chars=len(html_clip or ""), text_chars=len(unicode_text or ""))

    parts = []
    for p in (raw, unicode_text, html_clip):
        if p and p not in parts:
            parts.append(p)
    return "\n\n".join(parts)

def open_in_browser(url):
    try:
        import webbrowser
        webbrowser.open(url)
        return True
    except Exception as e:
        log(f"open browser error: {e}")
        return False

def browser_rescue_btdigg(query, pages):
    print("\nBTDigg está bloqueando al script directo con HTTP 429.")
    print("Activo MODO RESCATE NAVEGADOR.")
    print("Clave: copia la página desde el navegador para que Windows guarde también el HTML con los href.")
    all_results = []
    max_rescue_pages = min(len(pages), int(CONFIG.get("browser_rescue_max_pages", 3) or 3))

    for page in pages[:max_rescue_pages]:
        url = build_url("https://en.btdig.com/search?q={query_quote}&p={page0}", query, page)
        print(f"\nPágina {page}: {url}")
        open_in_browser(url)
        print("1) Espera a que cargue la página.")
        print("2) Haz clic dentro de la zona blanca de resultados.")
        print("3) Pulsa CTRL+A y luego CTRL+C.")
        print("4) Vuelve aquí y pulsa ENTER.")
        input("Listo...")
        txt = get_clipboard_text()
        diag("browser_rescue_clipboard", page=page, url=url, chars=len(txt))
        results = extract_magnets_from_text(txt, source_url=url)
        print(f"  Magnets leídos del portapapeles: {len(results)}")
        all_results.extend(results)

        if not results:
            print("  No he leído magnets. Puede ser que el navegador copiara solo texto visible y no HTML.")
            print("  Plan B manual: copia directamente varios enlaces magnet o usa la opción 3 del menú.")
            seguir = input("¿Probar otra página? [s/N]: ").strip().lower()
            if seguir != "s":
                break

    return dedupe_results(all_results)

def set_clipboard(text):
    if not text.strip():
        return False
    if os.name == "nt":
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as e:
            log(f"clipboard powershell error: {e}")
        try:
            subprocess.run(["clip"], input=text, text=True, check=True)
            return True
        except Exception as e:
            log(f"clipboard clip.exe error: {e}")
    return False

def deliver_to_jdownloader(download_links):
    if not download_links:
        print("\nNo hay enlaces finales para entregar.")
        return
    text = "\n".join(download_links)
    if CONFIG.get("write_last_links_txt", True):
        LAST_LINKS_FILE.write_text(text, encoding="utf-8")
        print(f"\nEnlaces/magnets guardados en: {LAST_LINKS_FILE}")
    if CONFIG.get("jdownloader_clipboard_mode", True):
        if set_clipboard(text):
            print("Enlaces/magnets copiados al portapapeles.")
            print("Si JDownloader está abierto y el Capturador está activo, debería pillarlos solo.")
        else:
            print("No pude copiar al portapapeles. Abre last_links.txt y copia manualmente.")

def _parse_gb_input(raw):
    raw = str(raw or "").strip().lower().replace(",", ".")
    raw = raw.replace("gigas", "").replace("giga", "").replace("gb", "").replace("g", "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except Exception:
        return 0.0

def ask_quality_min_size():
    try:
        raw = input("Minimo de tamano en GB para calidad pura [ENTER=sin minimo]: ").strip()
    except EOFError:
        raw = ""
    value = _parse_gb_input(raw)
    if value > 0:
        print(f"Filtro calidad pura: tamano aproximado, {value:g} GB o mas.")
    else:
        print("Filtro calidad pura: sin minimo de GB.")
    return value

def ask_mode():
    global CURRENT_MIN_SIZE_GB
    CURRENT_MIN_SIZE_GB = 0.0
    print("\nModo:")
    print("  0) Sin requisitos / sin filtro")
    print("  1) Calidad pura")
    print("  2) Castellano preferente")
    print("  3) Castellano obligatorio")
    raw = input(f"Elige modo [{CONFIG.get('default_mode', 2)}]: ").strip()
    if not raw:
        mode = int(CONFIG.get("default_mode", 2))
    elif raw in ("0", "1", "2", "3"):
        mode = int(raw)
    else:
        mode = int(CONFIG.get("default_mode", 2))
    if mode == 1:
        CURRENT_MIN_SIZE_GB = ask_quality_min_size()
    return mode

def flow_results(results, mode, token):
    if not results:
        print("\nNo he encontrado magnets/enlaces útiles.")
        pause()
        return
    print(f"\nEncontrados {len(results)} resultados brutos. Filtrando...")
    prepared = prepare_results(results, mode, token)
    shown = display_results(prepared)
    selected = select_results(shown)
    if not selected:
        cleanup_unselected_verified(prepared, [], token)
        print("\nNo se manda nada.")
        pause()
        return
    cleanup_unselected_verified(prepared, selected, token)
    print(f"\nSeleccionados: {len(selected)}")
    downloads = convert_selected_to_download_links(selected, token)
    deliver_to_jdownloader(downloads)
    pause()

def menu_search_btdigg(token):
    global CURRENT_QUERY
    clear(); banner()
    print("Buscar en BTDigg con navegador automático")
    query = input("\nBúsqueda: ").strip()
    if not query:
        return
    CURRENT_QUERY = query
    pages = input(f"Páginas a revisar [ej {CONFIG.get('default_pages', '1-5')} | 0=auto con límite]: ").strip() or str(CONFIG.get("default_pages", "1-5"))
    mode = ask_mode()
    try:
        results = search_btdigg_browser_auto_quality_aware(query, pages, mode)
    except Exception as e:
        print(f"\nERROR buscando: {e}")
        log(f"search_btdigg error: {e}")
        pause()
        return
    flow_results(results, mode, token)

def menu_quick_test_btdigg():
    global CURRENT_QUERY
    clear(); banner()
    print("Prueba rapida BTDigg (sin Real-Debrid ni qBittorrent)")
    query = input("\nBusqueda: ").strip()
    if not query:
        return
    CURRENT_QUERY = query
    pages = input(f"Paginas a revisar [ej {CONFIG.get('quick_test_default_pages', '1')}]: ").strip() or str(CONFIG.get("quick_test_default_pages", "1"))
    mode = ask_mode()
    try:
        results = search_btdigg_browser_auto_quality_aware(query, pages, mode)
    except Exception as e:
        print(f"\nERROR buscando: {e}")
        log(f"quick_test_btdigg error: {e}")
        pause()
        return
    print(f"\nEncontrados {len(results)} resultados brutos. Cribando sin verificar RD/qBit...")
    relevant, discarded = prepare_quick_btdigg_results(results, mode)
    export_quick_btdigg_results(query, mode, relevant, discarded)
    display_quick_btdigg_results(relevant, discarded)
    pause()

def menu_search_authorized_direct(token):
    global CURRENT_QUERY
    clear(); banner()
    print("Buscar .torrent con Jackett/Torznab o web autorizada")
    if not torznab_is_configured():
        print("\nAVISO: Torznab/Jackett no está configurado.")
        print("Sin Torznab el programa solo puede intentar leer la web; no tendrá seeds como Jackett.")
        configure_torznab_interactive()
    base_url = input("\nWeb principal: ").strip()
    if not base_url:
        return
    query = input("Búsqueda: ").strip()
    if not query:
        return
    CURRENT_QUERY = query
    reset_step2_diag()
    diag("authorized_direct_search_start", query=query, base_url=base_url)
    print(f"\nBuscando en: {normalize_base_url(base_url)}")
    try:
        results = search_authorized_site_for_torrents(base_url, query)
        results = dedupe_results(results)
        diag("authorized_direct_search", query=query, base_url=base_url, direct_links=len(results))
        print(f"\nCandidatos .torrent/enlace detectados: {len(results)}")
    except Exception as e:
        print(f"\nERROR leyendo web autorizada: {e}")
        log(f"authorized_direct_search error: {e}")
        pause()
        return
    flow_results(results, 0, token)

def menu_paste_url(token):
    global CURRENT_QUERY
    clear(); banner()
    print("Pegar URL de resultados / página con magnets")
    url = input("\nURL: ").strip()
    if not url:
        return
    try:
        CURRENT_QUERY = unquote(parse_qs(urlparse(url).query).get("q", [""])[0]).strip()
    except Exception:
        CURRENT_QUERY = ""
    mode = ask_mode()
    try:
        text = http_get_text(url)
        results = extract_magnets_from_text(text, source_url=url)
        if not results and url.lower().split("?")[0].endswith(".torrent"):
            results = [Result(title=url.split("/")[-1], torrent_url=url, source_url=url, hash="")]
    except Exception as e:
        print(f"\nERROR leyendo URL: {e}")
        log(f"paste_url error: {e}")
        pause()
        return
    flow_results(results, mode, token)

def menu_paste_text(token):
    clear(); banner()
    print("Pegar texto con magnets/enlaces")
    print("Pega el bloque. Cuando termines, escribe una línea solo con FIN y ENTER.")
    lines = []
    while True:
        line = input()
        if line.strip().upper() == "FIN":
            break
        lines.append(line)
    text = "\n".join(lines)
    mode = ask_mode()
    results = extract_magnets_from_text(text, source_url="PEGADO")
    for url in extract_urls_from_text(text):
        if not url.lower().startswith("magnet:") and not any(r.source_url == url for r in results):
            results.append(Result(title=unquote(Path(urlparse(url).path).name) or url, source_url=url, score=0, rd_status="DIRECT_PENDIENTE"))
    flow_results(results, mode, token)

def menu_clipboard_page(token):
    clear(); banner()
    print("Leer página copiada del navegador")
    print("1) Abre una página con resultados.")
    print("2) Haz clic dentro de la página.")
    print("3) Pulsa CTRL+A y CTRL+C.")
    print("4) Vuelve aquí.")
    input("\nPulsa ENTER cuando ya la tengas copiada...")
    text = get_clipboard_text()
    diag("clipboard_page_read", chars=len(text))
    if not text.strip():
        print("\nNo he leído texto del portapapeles.")
        pause()
        return
    mode = ask_mode()
    results = extract_magnets_from_text(text, source_url="PORTAPAPELES_NAVEGADOR")
    print(f"\nMagnets detectados en la página copiada: {len(results)}")
    flow_results(results, mode, token)


def menu_settings():
    clear(); banner()
    print("Ajustes")
    print(f"\nCarpeta: {APP_DIR}")
    print(f"Config:  {CONFIG_FILE}")
    print(f"Token:   {TOKEN_FILE}")
    if LEGACY_MOTOR_LOGS:
        print(f"Logs legacy: {LOG_DIR}")
        print(f"Diagnostico legacy: {DIAG_FILE}")
        print(f"Log legacy de esta ejecucion: {RUN_LOG_FILE}")
    else:
        print("Logs legacy: desactivados")
        print("Diagnostico: caja negra web en data/diagnostics/btdigg")
    print("Para afinar palabras buenas/malas, edita config.json con Bloc de notas.")
    print("Para poner token, edita rd_token.txt y pega solo el token.")
    pause()

def main():
    token = read_token()
    while True:
        clear(); banner()
        if not token:
            print("AVISO: Falta token Real-Debrid en rd_token.txt")
            print("       Podrás buscar, pero no consultar/convertir con RD hasta ponerlo.\n")
        print("1) Buscar en BTDigg con navegador automático")
        print("2) Buscar .torrent con Jackett/Torznab o web autorizada")
        print("3) Pegar URL de resultados ya abierta")
        print("4) Pegar texto con magnets/enlaces")
        print("5) Leer página copiada del navegador")
        print("6) Ajustes")
        print("7) Prueba rapida BTDigg (sin RD/qBit)")
        print("0) Salir")
        try:
            op = input("\nElige: ").strip().lower()
        except EOFError:
            break
        token = read_token()
        if op == "1":
            menu_search_btdigg(token)
        elif op == "2":
            menu_search_authorized_direct(token)
        elif op == "3":
            menu_paste_url(token)
        elif op == "4":
            menu_paste_text(token)
        elif op == "5":
            menu_clipboard_page(token)
        elif op == "6":
            menu_settings()
        elif op == "7":
            menu_quick_test_btdigg()
        elif op in ("0", "s", "salir"):
            break
        else:
            print("Opción no válida.")
            sleep_interruptible(1, where="main_loop.wait")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCerrado por el usuario.")
    except Exception as e:
        diag("fatal", error=repr(e))
        log(f"FATAL: {e}")
        print(f"\nERROR FATAL: {e}")
        print(f"Diagnóstico: {DIAG_FILE}")
        pause()
