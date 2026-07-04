from __future__ import annotations

import shutil
from pathlib import Path

from ._runtime_dirs import JobRuntime


def promote_successful_artifacts(runtime: JobRuntime, motor_runtime_dir: Path) -> None:
    shared_exports = motor_runtime_dir / "exports"
    shared_exports.mkdir(parents=True, exist_ok=True)
    if runtime.shown_file.exists():
        shutil.copy2(runtime.shown_file, shared_exports / "EDITOR_MAESTRO_SHOWN.json")
    if runtime.exports_dir.exists():
        for path in runtime.exports_dir.iterdir():
            if path.is_file():
                shutil.copy2(path, shared_exports / path.name)
    if runtime.last_links_file.exists():
        shutil.copy2(runtime.last_links_file, motor_runtime_dir / "last_links.txt")
    if runtime.ordered_links_file.exists():
        shutil.copy2(runtime.ordered_links_file, motor_runtime_dir / "last_links_ordenado.txt")
