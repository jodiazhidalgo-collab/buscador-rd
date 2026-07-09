from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / ".agents/skills/playwright-ui-check-btdigg-rd/scripts/ui_check.ps1"
SKILL_PATH = PROJECT_ROOT / ".agents/skills/playwright-ui-check-btdigg-rd/SKILL.md"
WEB_JS_PATH = PROJECT_ROOT / "services/btdigg-rd/app/web/static/js/btdigg-rd.js"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ui_check_keeps_desktop_mobile_console_and_network_contract():
    script = read(SCRIPT_PATH)

    for expected in (
        'name: "desktop"',
        'name: "mobile"',
        'page.on("console"',
        'page.on("pageerror"',
        'page.on("requestfailed"',
        'page.on("response"',
        "response.status() >= 400",
    ):
        assert expected in script


def test_ui_check_uses_system_browser_before_bundled_chromium():
    script = read(SCRIPT_PATH)

    for expected in (
        "Resolve-SystemBrowser",
        "App Paths\\msedge.exe",
        "App Paths\\chrome.exe",
        'launchOptions.channel = launchConfig.channel',
        "AllowBundledChromium",
        "AllowExecutablePathFallback",
        "executablePath: launchConfig.path",
        "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD",
    ):
        assert expected in script

    assert "playwright install chromium" not in script.lower()
    assert "& $playwrightCmd install chromium" in script
    assert "if ($AllowBundledChromium)" in script

    allow_index = script.index("if ($AllowBundledChromium)")
    bundled_path_index = script.index('$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $runtime "ms-playwright"')
    bundled_install_index = script.index("& $playwrightCmd install chromium")
    assert allow_index < bundled_path_index < bundled_install_index


def test_ui_check_reports_overflow_and_persistence():
    script = read(SCRIPT_PATH)

    for expected in (
        "inspectOverflow",
        "document.documentElement.scrollWidth",
        "data-allow-horizontal-scroll",
        "allowedHorizontalScrolls",
        "overflowFailures",
        "inspectPersistence",
        "page.reload",
        "persistenceFailures",
    ):
        assert expected in script


def test_history_title_scroll_is_marked_as_allowed_horizontal_scroll():
    script = read(SCRIPT_PATH)
    web_js = read(WEB_JS_PATH)

    assert 'data-allow-horizontal-scroll="history-title"' in web_js
    assert 'closest("[data-allow-horizontal-scroll]")' in script
    assert "marker.scrollWidth > marker.clientWidth + 1" in script
    assert "allowedHorizontalScrolls" in script


def test_skill_documents_the_visible_ui_check_contract():
    skill = read(SKILL_PATH).lower()

    for expected in (
        "chrome/edge",
        "desktop",
        "mobile",
        "capturas",
        "consola js",
        "red",
        "overflow horizontal",
        "data-allow-horizontal-scroll",
        "persistencia",
        "allowbundledchromium",
        "fallback",
        "explicito",
        "no descargues chromium automaticamente",
    ):
        assert expected in skill
