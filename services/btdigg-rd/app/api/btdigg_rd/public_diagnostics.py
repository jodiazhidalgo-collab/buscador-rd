from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA, PROJECT_ROOT


REDACTED = "***REDACTED***"
REDACTED_FILE = "***REDACTED_FILE***\n"

TEXT_EXTENSIONS = {
    ".csv",
    ".env",
    ".ini",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".seq",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
SECRET_PATH_MARKERS = (
    ".env",
    "secret",
    "secrets",
    "token",
    "password",
    "passwd",
    "credential",
    "private_key",
)
SECRET_KEY_MARKERS = (
    "token",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "secret",
    "credential",
    "client_secret",
    "access_token",
    "refresh_token",
    "gateway_key",
    "private_key",
)

SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z0-9_.-]*(?:TOKEN|PASSWORD|PASSWD|PASSWORD|API[_-]?KEY|APIKEY|AUTHORIZATION|BEARER|COOKIE|SECRET|CREDENTIAL|CLIENT[_-]?SECRET|ACCESS[_-]?TOKEN|REFRESH[_-]?TOKEN|GATEWAY[_-]?KEY|PRIVATE[_-]?KEY)[A-Z0-9_.-]*)\s*([:=])\s*([^\s,\"'<>]+)"
)
AUTH_HEADER_RE = re.compile(r"(?i)\b(authorization|bearer)\s*[:=]\s*([^\s,\"'<>]+)")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")


def default_public_dir() -> Path:
    configured = os.environ.get("BTDIGG_PUBLIC_DIAGNOSTICS_DIR", "").strip()
    if configured:
        return Path(configured)
    try:
        return PROJECT_ROOT.parents[1] / "diagnostics_public"
    except IndexError:
        return PROJECT_ROOT / "diagnostics_public"


def _safe_label(label: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(label or "").strip())
    value = value.strip("._")
    return value or "source"


def _configured_sources() -> list[tuple[str, Path]]:
    sources: list[tuple[str, Path]] = [("btdigg", DATA)]
    raw = os.environ.get("BTDIGG_PUBLIC_DIAGNOSTICS_EXTRA_ROOTS", "").strip()
    if not raw:
        return sources
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            path_text, label = item.split("=", 1)
        else:
            path_text, label = item, Path(item).name
        path = Path(path_text.strip())
        if path.exists():
            sources.append((_safe_label(label), path))
    return sources


def _is_secret_key(key: Any) -> bool:
    text = str(key or "").strip().lower().replace("-", "_")
    if not text:
        return False
    return any(marker in text for marker in SECRET_KEY_MARKERS)


def _is_secret_path(path: Path) -> bool:
    lowered_parts = [part.lower() for part in path.parts]
    for part in lowered_parts:
        if any(marker in part for marker in SECRET_PATH_MARKERS):
            return True
    return False


def _sanitize_text(text: str) -> tuple[str, int]:
    count = 0

    def repl_assignment(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}{match.group(2)}{REDACTED}"

    text = SECRET_ASSIGNMENT_RE.sub(repl_assignment, text)

    def repl_auth(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}: {REDACTED}"

    text = AUTH_HEADER_RE.sub(repl_auth, text)

    def repl_jwt(_: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return REDACTED

    text = JWT_RE.sub(repl_jwt, text)
    return text, count


def _sanitize_json(value: Any, parent_key: str = "") -> tuple[Any, int]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        total = 0
        for key, child in value.items():
            if _is_secret_key(key):
                out[str(key)] = "" if child in ("", None) else REDACTED
                if child not in ("", None):
                    total += 1
                continue
            out[str(key)], child_count = _sanitize_json(child, str(key))
            total += child_count
        return out, total
    if isinstance(value, list):
        out_list = []
        total = 0
        for child in value:
            cleaned, child_count = _sanitize_json(child, parent_key)
            out_list.append(cleaned)
            total += child_count
        return out_list, total
    if isinstance(value, str):
        cleaned, count = _sanitize_text(value)
        return cleaned, count
    return value, 0


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _write_text(path: Path, text: str) -> None:
    text = "\n".join(line.rstrip(" \t") for line in text.splitlines())
    if text:
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _export_json(path: Path, dest: Path) -> int:
    text = _read_text(path)
    try:
        data = json.loads(text)
    except Exception:
        cleaned, count = _sanitize_text(text)
        _write_text(dest, cleaned)
        return count
    cleaned, count = _sanitize_json(data)
    _write_text(dest, json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return count


def _export_jsonl(path: Path, dest: Path) -> int:
    lines: list[str] = []
    count = 0
    for line in _read_text(path).splitlines():
        if not line.strip():
            lines.append("")
            continue
        try:
            data = json.loads(line)
            cleaned, item_count = _sanitize_json(data)
            lines.append(json.dumps(cleaned, ensure_ascii=False, sort_keys=True))
            count += item_count
        except Exception:
            cleaned_line, item_count = _sanitize_text(line)
            lines.append(cleaned_line)
            count += item_count
    _write_text(dest, "\n".join(lines) + ("\n" if lines else ""))
    return count


def _sqlite_table_names(db_path: Path) -> list[str]:
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"
        ).fetchall()
    return [str(row[0]) for row in rows]


def _export_sqlite(db_path: Path, dest_dir: Path) -> tuple[int, int]:
    redactions = 0
    rows_written = 0
    dest_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        schema_rows = conn.execute(
            "select type, name, tbl_name, sql from sqlite_master where sql is not null order by type, name"
        ).fetchall()
        schema = [
            {"type": row[0], "name": row[1], "table": row[2], "sql": row[3]}
            for row in schema_rows
        ]
        cleaned_schema, count = _sanitize_json(schema)
        redactions += count
        _write_text(dest_dir / "schema.json", json.dumps(cleaned_schema, ensure_ascii=False, indent=2) + "\n")

        tables_dir = dest_dir / "tables"
        tables_dir.mkdir(parents=True, exist_ok=True)
        for table in _sqlite_table_names(db_path):
            columns_info = conn.execute(f'pragma table_info("{table}")').fetchall()
            columns = [str(row[1]) for row in columns_info]
            output_lines: list[str] = []
            for row in conn.execute(f'select * from "{table}"'):
                item = {columns[i]: row[i] for i in range(len(columns))}
                cleaned, count = _sanitize_json(item)
                redactions += count
                output_lines.append(json.dumps(cleaned, ensure_ascii=False, sort_keys=True))
                rows_written += 1
            _write_text(tables_dir / f"{_safe_label(table)}.jsonl", "\n".join(output_lines) + ("\n" if output_lines else ""))
    return redactions, rows_written


def _repo_snapshot(root: Path) -> dict[str, Any]:
    try:
        repo_root = PROJECT_ROOT.parents[1]
    except IndexError:
        repo_root = PROJECT_ROOT
    snapshot: dict[str, Any] = {"root": str(repo_root)}
    try:
        head = subprocess.check_output(["git", "-C", str(repo_root), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
        tracked = subprocess.check_output(["git", "-C", str(repo_root), "ls-files"], text=True, stderr=subprocess.DEVNULL).splitlines()
        snapshot.update({"head": head, "tracked_files_count": len(tracked)})
    except Exception:
        snapshot.update({"head": "", "tracked_files_count": 0})
    snapshot["public_dir"] = str(root)
    return snapshot


def _prepare_output_dir(path: Path, sources: list[tuple[str, Path]]) -> Path:
    output = path.resolve()
    for _, source in sources:
        try:
            resolved_source = source.resolve()
        except Exception:
            continue
        if output == resolved_source or resolved_source in output.parents:
            raise RuntimeError(f"Directorio publico inseguro dentro de la fuente: {output}")
    if len(output.parts) < 3:
        raise RuntimeError(f"Directorio publico demasiado amplio: {output}")
    if output.exists():
        for child in output.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    else:
        output.mkdir(parents=True, exist_ok=True)
    return output


def export_public_diagnostics(trigger: str = "manual", current_run_id: str = "") -> dict[str, Any]:
    sources = _configured_sources()
    output = _prepare_output_dir(default_public_dir(), sources)
    manifest: list[dict[str, Any]] = []
    exported_files = 0
    skipped_files = 0
    redactions = 0
    sqlite_rows = 0

    for label, source in sources:
        if not source.exists():
            continue
        base_dest = output / _safe_label(label)
        files = [source] if source.is_file() else sorted(path for path in source.rglob("*") if path.is_file())
        for path in files:
            rel = Path(path.name) if source.is_file() else path.relative_to(source)
            dest = base_dest / rel
            item = {
                "source": _safe_label(label),
                "path": str(rel).replace("\\", "/"),
                "bytes": path.stat().st_size,
                "exported": False,
                "redacted": False,
                "note": "",
            }
            suffix = path.suffix.lower()
            try:
                if _is_secret_path(path):
                    _write_text(dest, REDACTED_FILE)
                    exported_files += 1
                    redactions += 1
                    item.update({"exported": True, "redacted": True, "note": "secret_path_redacted"})
                elif suffix == ".json":
                    count = _export_json(path, dest)
                    exported_files += 1
                    redactions += count
                    item.update({"exported": True, "redacted": count > 0})
                elif suffix == ".jsonl":
                    count = _export_jsonl(path, dest)
                    exported_files += 1
                    redactions += count
                    item.update({"exported": True, "redacted": count > 0})
                elif suffix in SQLITE_EXTENSIONS:
                    count, rows = _export_sqlite(path, dest.with_suffix(dest.suffix + "_export"))
                    exported_files += 1
                    redactions += count
                    sqlite_rows += rows
                    item.update({"exported": True, "redacted": count > 0, "note": "sqlite_exported_as_jsonl"})
                elif suffix in TEXT_EXTENSIONS:
                    cleaned, count = _sanitize_text(_read_text(path))
                    _write_text(dest, cleaned)
                    exported_files += 1
                    redactions += count
                    item.update({"exported": True, "redacted": count > 0})
                else:
                    skipped_files += 1
                    item["note"] = "binary_or_unknown_extension_listed_only"
            except Exception as exc:
                skipped_files += 1
                item["note"] = f"export_error:{type(exc).__name__}"
            manifest.append(item)

    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "generated_at": generated_at,
        "trigger": trigger,
        "current_run_id": current_run_id,
        "exported_files": exported_files,
        "skipped_files": skipped_files,
        "redactions": redactions,
        "sqlite_rows": sqlite_rows,
        "sources": [{"label": label, "path": str(path)} for label, path in sources],
        "repo": _repo_snapshot(output),
    }
    _write_text(output / "manifest.json", json.dumps({"summary": summary, "files": manifest}, ensure_ascii=False, indent=2) + "\n")
    _write_text(
        output / "README.md",
        "\n".join(
            [
                "# Diagnostico publico Buscador RD",
                "",
                "Esta carpeta es el espejo publico saneado para ChatGPT, Codex y revisiones externas.",
                "",
                "Incluye runtime, jobs, logs, JSON, seguimiento, historial y exportaciones legibles.",
                "Los tokens, passwords, API keys, Authorization, cookies y secretos parecidos se sustituyen por `***REDACTED***`.",
                "Los magnets, hashes, rutas, nombres, busquedas, URLs, estados RD/qB y errores se mantienen visibles.",
                "",
                "Entradas principales:",
                "",
                "- `btdigg/`: copia saneada de `config/btdigg-rd/data`.",
                "- `manifest.json`: lista completa de ficheros exportados, omitidos y redacciones.",
                "- `*_export/`: bases SQLite volcadas a JSON legible.",
                "",
                "Para que GitHub/ChatGPT vea cambios nuevos, hay que regenerar esta carpeta y hacer commit/push.",
                "",
            ]
        ),
    )
    return summary


def main() -> int:
    summary = export_public_diagnostics(trigger=os.environ.get("BTDIGG_PUBLIC_DIAGNOSTICS_TRIGGER", "manual"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
