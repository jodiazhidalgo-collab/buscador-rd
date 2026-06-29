from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_text(path: Path, limit: int = 200_000) -> str:
    try:
        if not path.exists():
            return ""
        data = path.read_bytes()
        if len(data) > limit:
            data = data[-limit:]
        return data.decode("utf-8", errors="replace")
    except Exception as exc:
        return f"ERROR leyendo {path.name}: {exc}"


def read_json(path: Path) -> Any:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
