from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def test_root_readme_stays_minimal_and_points_to_review_docs():
    text = read("README.md")

    for expected in (
        "AGENTS.md",
        "docs/AI_REVIEW.md",
    ):
        assert expected in text

    for hidden_from_front_page in (
        "Real-Debrid",
        "qBittorrent",
        "services/btdigg-rd",
        "diagnostics_public/",
        "deploy key",
        "Push desde la web",
    ):
        assert hidden_from_front_page not in text


def test_ai_review_guide_points_to_ci_evidence_safe_boundaries_and_truth_source():
    text = read("docs/AI_REVIEW.md")

    for expected in (
        "services/btdigg-rd",
        "services/cloudflared",
        "AGENTS.md",
        ".agents/skills/",
        ".agents/skills/investigacion-avanzada-buscador-rd/",
        "DATA_DIR",
        "diagnostics/btdigg",
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


def test_read_only_policy_avoids_backups_cleanup_visual_checks_and_real_git_tests():
    agents = read("AGENTS.md").lower()
    backup_skill = read(".agents/skills/backup-btdigg-rd/SKILL.md").lower()
    cleanup_skill = read(".agents/skills/limpiar-residuos-btdigg-rd/SKILL.md").lower()
    ui_skill = read(".agents/skills/playwright-ui-check-btdigg-rd/SKILL.md").lower()

    for expected in (
        "un turno de solo lectura no crea absolutamente nada",
        "si no has modificado ningun archivo, no ejecutes",
        "pruebas sinteticas que ejecuten git real",
        "no hagas prueba visual para cambios no visuales",
    ):
        assert expected in agents

    assert "no usar esta skill en un turno de solo lectura" in backup_skill
    assert "-dryrun` debe ser totalmente lector" in backup_skill
    assert "no usar en un turno de solo lectura" in cleanup_skill
    assert "revisiones generales de solo lectura" in ui_skill


def test_backup_dry_run_and_git_close_are_side_effect_free_when_clean():
    backup_script = read(".agents/skills/backup-btdigg-rd/scripts/create_backup.ps1")
    close_script = read(".agents/skills/cerrar-git-btdigg-rd/scripts/close_git.ps1")
    close_skill = read(".agents/skills/cerrar-git-btdigg-rd/SKILL.md")

    dry_run_index = backup_script.index("if ($DryRun)")
    backup_dir_creation_index = backup_script.index(
        'New-Item -ItemType Directory -Path $backupDir'
    )
    assert dry_run_index < backup_dir_creation_index

    initial_status_index = close_script.index("$initialStatus = @(git status --short)")
    first_cleanup_index = close_script.index(
        'Invoke-ResidueCleanup -Root $root -Stage "pre-commit"'
    )
    assert initial_status_index < first_cleanup_index
    assert "Git limpio de inicio. No limpio, no hago commit y no hago push." in close_script
    assert 'Invoke-ResidueCleanup -Root $root -Stage "post-commit"' in close_script
    assert "if ($commitExit -ne 0)" in close_script
    assert "-ForceCleanup" in close_skill
