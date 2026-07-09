from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def test_root_readme_declares_public_entrypoints_and_truth_source():
    text = read("README.md")

    for expected in (
        "services/btdigg-rd",
        "services/cloudflared",
        "docker-compose.example.yaml",
        "AGENTS.md",
        ".agents/skills/",
        ".agents/skills/investigacion-avanzada-buscador-rd/",
        "DATA_DIR",
        "diagnostics/btdigg",
        "docs/AI_REVIEW.md",
    ):
        assert expected in text


def test_ai_review_guide_points_to_ci_evidence_and_safe_boundaries():
    text = read("docs/AI_REVIEW.md")

    for expected in (
        "AGENTS.md",
        ".agents/skills/",
        ".agents/skills/investigacion-avanzada-buscador-rd/",
        "buscador-rd-pytest-evidence",
        "buscador-rd-pytest-junit.xml",
        "docker-compose.example.yaml",
        "config/btdigg-rd/data/",
        "config/cloudflared/config/secrets.env",
        "BTDIGG_LIVE=1",
    ):
        assert expected in text


def test_gitignore_keeps_runtime_backups_and_credentials_out_but_allows_public_skills():
    text = read(".gitignore")

    for expected in (
        "_backups/",
        "_codex_runtime/",
        ".agents/*",
        "!.agents/skills/",
        "!.agents/skills/**",
        ".codex/",
        "docker-compose.yaml",
        "config/btdigg-rd/data/",
        "config/cloudflared/config/secrets.env",
        "config/whisper/data/",
        "*.zip",
    ):
        assert expected in text

    assert "\nAGENTS.md" not in text


def test_pytest_public_diagnostics_are_sandboxed():
    configured = Path(os.environ["BTDIGG_PUBLIC_DIAGNOSTICS_DIR"])

    assert configured != PROJECT_ROOT / "diagnostics_public"
    assert "_codex_runtime" in configured.parts
    assert configured.name == "pytest-public-diagnostics"


def test_git_hooks_and_ci_are_present():
    hook = read(".githooks/pre-commit")
    workflow = read(".github/workflows/ci.yml")
    codeowners = read(".github/CODEOWNERS")

    assert "git diff --cached --check" in hook
    assert "compileall" in hook
    assert "pytest" in hook
    assert "services/btdigg-rd/requirements-dev.txt" in workflow
    assert "buscador-rd-pytest-evidence" in workflow
    assert "python -m pytest -q" in workflow
    assert "@jodiazhidalgo-collab" in codeowners


def test_advanced_investigation_skill_points_to_github_repo():
    agents = read("AGENTS.md")
    skill = read(".agents/skills/investigacion-avanzada-buscador-rd/SKILL.md")

    for text in (agents, skill):
        assert "investigacion-avanzada-buscador-rd" in text
        assert "jodiazhidalgo-collab/buscador-rd" in text
        assert "diagnostics_public/" in text

    assert "README.md" in skill
    assert "AGENTS.md" in skill
    assert "docs/AI_REVIEW.md" in skill
    assert ".agents/skills/" in skill
