from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any


PUBLIC_RUNTIME_DEFAULTS: dict[str, Any] = {
    "default_mode": 0,
    "default_pages": "1-3",
    "safe_max_pages_when_zero": 30,
    "max_results_to_show": 80,
    "min_size_gb": 0.0,
    "max_size_gb": 400.0,
    "request_timeout_sec": 30,
    "delay_between_btdigg_pages_sec": 3.0,
    "pack_query_match_min_ratio": 0.55,
    "verify_max_candidates": 60,
    "verify_wait_sec": 0.25,
    "qbit_probe_max_candidates": 40,
    "qbit_probe_wait_sec": 35,
    "qbit_same_file_min_ratio": 0.9,
    "qbit_probe_parallel_workers": 5,
    "hide_non_working_results": True,
    "rd_addmagnet_min_interval_sec": 1.0,
    "rd_selectfiles_min_interval_sec": 0.75,
    "rd_delete_min_interval_sec": 0.65,
    "rd_info_min_interval_sec": 0.1,
    "rd_addmagnet_max_concurrent": 1,
    "rd_selectfiles_max_concurrent": 1,
    "rd_delete_max_concurrent": 1,
    "rd_info_max_concurrent": 4,
    "rd_api_429_cooldown_sec": 3.0,
    "rd_endpoint_429_cooldown_sec": 6.0,
    "rd_429_retry_attempts": 6,
    "rd_api_rate_limit_per_min": 235,
    "rd_api_rate_limit_burst": 4,
}

TV_RULE_DEFAULTS: dict[str, list[str]] = {
    "tv_series_templates": [
        "SXXEXX",
        "SXEX",
        "SXX EXX",
        "XXxXX",
        "XxXX",
        "Temporada XX",
        "Temp XX",
        "Season XX",
        "Capitulo XX",
        "Capitulo X",
        "Episode XX",
        "Episodio XX",
        "Cap.XXX",
    ],
    "tv_series_words": [
        "capitulo",
        "capítulo",
        "episodio",
        "episode",
        "temporada",
        "temp",
        "season",
        "Cap.XXX",
    ],
}


def load_raw_runtime_config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_backup_candidate_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as archive:
                names = [
                    name
                    for name in archive.namelist()
                    if name.replace("\\", "/").endswith("app/motor/btdigg/config.json")
                ]
                if not names:
                    return {}
                data = json.loads(archive.read(names[0]).decode("utf-8-sig"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}
    return load_raw_runtime_config(path)


def load_effective_runtime_config(path: Path) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    cfg.update(PUBLIC_RUNTIME_DEFAULTS)
    cfg.update(TV_RULE_DEFAULTS)
    cfg.update(load_raw_runtime_config(path))
    return cfg


def repair_runtime_config_if_missing(path: Path, backup_candidate_path: Path | None = None) -> dict[str, Any]:
    raw = load_raw_runtime_config(path)
    base = _load_backup_candidate_config(backup_candidate_path)
    repaired: dict[str, Any] = {}
    repaired.update(PUBLIC_RUNTIME_DEFAULTS)
    repaired.update(TV_RULE_DEFAULTS)
    repaired.update(base)
    repaired.update(raw)

    missing_public = [key for key in PUBLIC_RUNTIME_DEFAULTS if key not in raw]
    missing_tv = [key for key in TV_RULE_DEFAULTS if key not in raw]
    if missing_public or missing_tv or repaired != raw:
        path.write_text(json.dumps(repaired, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return repaired
