from __future__ import annotations

import subprocess

import pytest


def test_project_publish_exports_scans_commits_and_pushes(tmp_path, monkeypatch):
    from api.btdigg_rd import project_publish

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".gitleaks.toml").write_text("", encoding="utf-8")
    (root / "diagnostics_public").mkdir()
    (root / "diagnostics_public" / "manifest.json").write_text("{}", encoding="utf-8")
    code_file = root / "services" / "btdigg-rd" / "app" / "x.py"
    code_file.parent.mkdir(parents=True)
    code_file.write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setenv("BTDIGG_PROJECT_PUSH_ENABLED", "1")
    monkeypatch.setenv("BTDIGG_PROJECT_ROOT", str(root))
    monkeypatch.setenv("BTDIGG_PROJECT_PUSH_REMOTE", "git@github.com:owner/repo.git")
    monkeypatch.setattr(project_publish, "export_public_diagnostics", lambda trigger: {"trigger": trigger, "exported_files": 1})

    commands: list[list[str]] = []
    gitleaks_targets = []

    def fake_run_gitleaks(run_root, target):
        assert run_root == root
        gitleaks_targets.append(target)

    def fake_run(args, run_root, timeout=120):
        assert run_root == root
        commands.append(args)
        if args == ["git", "branch", "--show-current"]:
            return "master\n"
        if args == ["git", "rev-parse", "HEAD"]:
            return "abc123456789\n"
        if args == ["git", "rev-parse", "refs/remotes/origin/master"]:
            return "abc123456789\n"
        if args == ["git", "rev-parse", "--short", "HEAD"]:
            return "abc123\n"
        return ""

    def fake_run_raw(args, run_root, timeout=120):
        assert run_root == root
        if args == ["git", "diff", "--cached", "--name-only", "-z"]:
            return subprocess.CompletedProcess(args, 0, "diagnostics_public/manifest.json\0services/btdigg-rd/app/x.py\0", "")
        if args == ["git", "diff", "--cached", "--quiet"]:
            return subprocess.CompletedProcess(args, 1, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(project_publish, "_run_gitleaks", fake_run_gitleaks)
    monkeypatch.setattr(project_publish, "_run", fake_run)
    monkeypatch.setattr(project_publish, "_run_raw", fake_run_raw)
    monkeypatch.setattr(project_publish, "_safe_git_setup", lambda run_root: None)

    result = project_publish.publish_project()

    assert result["ok"] is True
    assert result["commit_created"] is True
    assert result["staged_files"] == 2
    assert result["branch"] == "master"
    assert gitleaks_targets[0] == root / "diagnostics_public"
    assert len(gitleaks_targets) == 2
    assert ["git", "add", "-A"] in commands
    assert ["git", "commit", "-m", "chore: publish diagnostics from web"] in commands
    assert ["git", "push", "git@github.com:owner/repo.git", "HEAD:master"] in commands
    assert ["git", "fetch", "git@github.com:owner/repo.git", "refs/heads/master:refs/remotes/origin/master"] in commands


def test_project_publish_requires_enabled(monkeypatch):
    from api.btdigg_rd import project_publish

    monkeypatch.delenv("BTDIGG_PROJECT_PUSH_ENABLED", raising=False)

    with pytest.raises(project_publish.PublishError) as exc:
        project_publish.publish_project()

    assert exc.value.status_code == 503
