from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
PYTEST_DATA_DIR = PROJECT_ROOT / "_codex_runtime" / "test-data" / "pytest-session"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

os.environ.setdefault("DATA_DIR", str(PYTEST_DATA_DIR))
PYTEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR_SENSITIVE_MODULES = (
    "api.btdigg_rd.config",
    "api.btdigg_rd.history",
    "api.btdigg_rd.blackbox",
    "api.btdigg_rd.retention",
    "api.btdigg_rd.results",
    "api.btdigg_rd.ui_state",
    "api.btdigg_rd.send",
    "api.btdigg_rd.jobs",
    "api.btdigg_rd.routes",
)


def reload_data_dir_module_stack(*extra_module_names: str) -> None:
    importlib.invalidate_caches()
    for module_name in DATA_DIR_SENSITIVE_MODULES + tuple(extra_module_names):
        module = sys.modules.get(module_name)
        if module is not None:
            importlib.reload(module)


def load_app_module():
    module_name = "_btdigg_pytest_app"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, APP_DIR / "app.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("No se pudo cargar app.py para pytest")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def reload_data_dir_modules():
    return reload_data_dir_module_stack


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture
def app(isolated_data_dir, reload_data_dir_modules):
    reload_data_dir_modules()
    app_module = load_app_module()
    return app_module.create_app()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()
