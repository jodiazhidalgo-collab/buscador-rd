from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from .public_diagnostics import export_public_diagnostics


_LOCK = threading.Lock()
_TRUE_VALUES = {"1", "true", "yes", "on"}


class PublishError(RuntimeError):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


def _enabled() -> bool:
    return os.environ.get("BTDIGG_PROJECT_PUSH_ENABLED", "").strip().lower() in _TRUE_VALUES


def _project_root() -> Path:
    configured = os.environ.get("BTDIGG_PROJECT_ROOT", "").strip()
    if not configured:
        raise PublishError("push no configurado: falta BTDIGG_PROJECT_ROOT", 503)
    root = Path(configured).resolve()
    if not (root / ".git").exists():
        raise PublishError("push no configurado: el repo git no esta montado", 503)
    return root


def _prepare_ssh_key() -> Path | None:
    configured = os.environ.get("BTDIGG_PROJECT_PUSH_SSH_KEY", "").strip()
    if not configured:
        return None
    source = Path(configured)
    if not source.exists():
        raise PublishError("push no configurado: falta la deploy key", 503)
    dest = Path(tempfile.gettempdir()) / "btdigg_project_push_key"
    data = source.read_bytes()
    if not dest.exists() or dest.read_bytes() != data:
        dest.write_bytes(data)
    dest.chmod(0o600)
    return dest


def _command_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_AUTHOR_NAME", "Buscador RD Web")
    env.setdefault("GIT_AUTHOR_EMAIL", "buscador-rd-web@users.noreply.github.com")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    if not env.get("GIT_SSH_COMMAND"):
        key = _prepare_ssh_key()
        if key:
            known_hosts = Path(tempfile.gettempdir()) / "btdigg_project_push_known_hosts"
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {key} -o IdentitiesOnly=yes "
                f"-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={known_hosts}"
            )
    return env


def _run_raw(args: list[str], root: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(root),
        env=_command_env(),
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _tail(text: str, limit: int = 600) -> str:
    cleaned = "\n".join(line.rstrip() for line in str(text or "").splitlines() if line.strip())
    return cleaned[-limit:]


def _run(args: list[str], root: Path, timeout: int = 120) -> str:
    result = _run_raw(args, root, timeout=timeout)
    if result.returncode != 0:
        output = _tail((result.stdout or "") + "\n" + (result.stderr or ""))
        raise PublishError(f"fallo en {' '.join(args[:2])}: {output or result.returncode}")
    return result.stdout or ""


def _require_tool(name: str) -> None:
    if not shutil.which(name):
        raise PublishError(f"{name} no esta disponible en el contenedor", 503)


def _safe_git_setup(root: Path) -> None:
    _require_tool("git")
    _run(["git", "config", "--global", "--add", "safe.directory", str(root)], root)


def _current_branch(root: Path) -> str:
    branch = _run(["git", "branch", "--show-current"], root).strip()
    return branch or "master"


def _refresh_origin_branch(root: Path, remote: str, branch: str) -> None:
    refspec = f"refs/heads/{branch}:refs/remotes/origin/{branch}"
    _run(["git", "fetch", remote, refspec], root, timeout=180)
    head = _run(["git", "rev-parse", "HEAD"], root).strip()
    origin_head = _run(["git", "rev-parse", f"refs/remotes/origin/{branch}"], root).strip()
    if head != origin_head:
        raise PublishError(f"push no confirmado: origin/{branch} no coincide con HEAD")


def _staged_names(root: Path) -> list[str]:
    result = _run_raw(["git", "diff", "--cached", "--name-only", "-z"], root)
    if result.returncode != 0:
        raise PublishError("no se pudo leer el stage de git")
    return [item for item in result.stdout.split("\0") if item]


def publish_project() -> dict[str, Any]:
    if not _enabled():
        raise PublishError("push desactivado en este contenedor", 503)
    if not _LOCK.acquire(blocking=False):
        raise PublishError("push ya en marcha", 409)
    try:
        root = _project_root()
        _safe_git_setup(root)

        summary = export_public_diagnostics(trigger="web-push")

        _run(["git", "diff", "--check"], root)
        _run(["git", "add", "-A"], root)
        staged = _staged_names(root)

        commit_created = False
        staged_check = _run_raw(["git", "diff", "--cached", "--quiet"], root)
        if staged_check.returncode not in (0, 1):
            raise PublishError("no se pudo comprobar el stage de git")
        if staged_check.returncode == 1:
            message = os.environ.get("BTDIGG_PROJECT_PUSH_MESSAGE", "").strip() or "chore: publish diagnostics from web"
            _run(["git", "commit", "-m", message], root)
            commit_created = True

        branch = _current_branch(root)
        remote = os.environ.get("BTDIGG_PROJECT_PUSH_REMOTE", "").strip()
        if not remote:
            remote = _run(["git", "remote", "get-url", "origin"], root).strip()
        _run(["git", "push", remote, f"HEAD:{branch}"], root, timeout=180)
        _refresh_origin_branch(root, remote, branch)

        head = _run(["git", "rev-parse", "--short", "HEAD"], root).strip()
        return {
            "ok": True,
            "status": "pushed",
            "branch": branch,
            "head": head,
            "commit_created": commit_created,
            "staged_files": len(staged),
            "diagnostics": summary,
        }
    finally:
        _LOCK.release()
