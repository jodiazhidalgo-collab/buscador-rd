param(
    [string]$Url = "http://192.168.1.159:9007/",
    [int]$TimeoutMs = 30000,
    [switch]$SkipInstall,
    [switch]$AllowBundledChromium,
    [switch]$AllowExecutablePathFallback
)

$ErrorActionPreference = "Stop"

function Get-ToolPath {
    param([string]$Name)

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "No encuentro $Name en PATH."
    }
    return $cmd.Source
}

function Get-FileVersion {
    param([string]$Path)

    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
        return ""
    }

    $item = Get-Item -LiteralPath $Path
    return [string]$item.VersionInfo.ProductVersion
}

function New-BrowserInfo {
    param(
        [string]$Name,
        [string]$Channel,
        [string]$Path,
        [string]$Source
    )

    [pscustomobject]@{
        name = $Name
        channel = $Channel
        path = $Path
        source = $Source
        version = Get-FileVersion -Path $Path
    }
}

function Resolve-AppPathBrowser {
    param(
        [string]$RegistryPath,
        [string]$Name,
        [string]$Channel
    )

    if (-not (Test-Path -LiteralPath $RegistryPath)) {
        return $null
    }

    $item = Get-Item -LiteralPath $RegistryPath
    $exePath = [string]$item.GetValue("")
    if ($exePath -and (Test-Path -LiteralPath $exePath)) {
        return New-BrowserInfo -Name $Name -Channel $Channel -Path $exePath -Source $RegistryPath
    }

    return $null
}

function Resolve-SystemBrowser {
    $registryCandidates = @(
        @{ Path = "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"; Name = "Microsoft Edge"; Channel = "msedge" },
        @{ Path = "HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"; Name = "Microsoft Edge"; Channel = "msedge" },
        @{ Path = "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"; Name = "Google Chrome"; Channel = "chrome" },
        @{ Path = "HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"; Name = "Google Chrome"; Channel = "chrome" }
    )

    foreach ($candidate in $registryCandidates) {
        $browser = Resolve-AppPathBrowser -RegistryPath $candidate.Path -Name $candidate.Name -Channel $candidate.Channel
        if ($browser) {
            return $browser
        }
    }

    $commonCandidates = @(
        @{ Path = Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"; Name = "Microsoft Edge"; Channel = "msedge" },
        @{ Path = Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"; Name = "Microsoft Edge"; Channel = "msedge" },
        @{ Path = Join-Path $env:LOCALAPPDATA "Microsoft\Edge\Application\msedge.exe"; Name = "Microsoft Edge"; Channel = "msedge" },
        @{ Path = Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"; Name = "Google Chrome"; Channel = "chrome" },
        @{ Path = Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"; Name = "Google Chrome"; Channel = "chrome" },
        @{ Path = Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe"; Name = "Google Chrome"; Channel = "chrome" }
    )

    foreach ($candidate in $commonCandidates) {
        if ($candidate.Path -and (Test-Path -LiteralPath $candidate.Path)) {
            return New-BrowserInfo -Name $candidate.Name -Channel $candidate.Channel -Path $candidate.Path -Source "common-path"
        }
    }

    return $null
}

$skillRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$projectRoot = Resolve-Path (Join-Path $skillRoot "..\..\..")
$runtime = Join-Path $projectRoot "_codex_runtime\playwright-ui-check"
$artifactRoot = Join-Path $projectRoot "_codex_runtime\artifacts\ui-check"

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null

$nodePath = Get-ToolPath "node.exe"
$npmPath = Get-ToolPath "npm.cmd"
$env:NODE_PATH = Join-Path $runtime "node_modules"

$browserInfo = Resolve-SystemBrowser
if (-not $browserInfo -and -not $AllowBundledChromium) {
    throw "No encuentro Chrome/Edge del sistema. Instala Chrome/Edge o ejecuta con -AllowBundledChromium para usar Chromium de Playwright."
}

Push-Location $runtime
try {
    if (-not $SkipInstall) {
        if (-not (Test-Path (Join-Path $runtime "node_modules\playwright"))) {
            $previousSkipBrowserDownload = $env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD
            $env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1"
            try {
                & $npmPath install playwright --no-audit --no-fund | Out-Host
            }
            finally {
                if ($null -eq $previousSkipBrowserDownload) {
                    Remove-Item Env:\PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD -ErrorAction SilentlyContinue
                } else {
                    $env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = $previousSkipBrowserDownload
                }
            }
        }
    }

    $playwrightCmd = Join-Path $runtime "node_modules\.bin\playwright.cmd"
    if (-not (Test-Path $playwrightCmd)) {
        throw "No encuentro Playwright instalado en $playwrightCmd."
    }

    if ($AllowBundledChromium) {
        $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $runtime "ms-playwright"
        & $playwrightCmd install chromium | Out-Host
        $browserInfo = [pscustomobject]@{
            name = "Playwright Chromium"
            channel = ""
            path = ""
            source = "bundled"
            version = ""
        }
    } else {
        Remove-Item Env:\PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}

$runnerPath = Join-Path $artifactRoot "btdigg-rd-ui-check.runner.js"
$resultPath = Join-Path $artifactRoot "btdigg-rd-ui-check.result.json"
$desktopShot = Join-Path $artifactRoot "btdigg-rd-desktop.png"
$mobileShot = Join-Path $artifactRoot "btdigg-rd-mobile.png"
$launchConfigPath = Join-Path $artifactRoot "btdigg-rd-ui-check.launch.json"

$launchConfig = @{
    mode = if ($AllowBundledChromium) { "bundled" } else { "system" }
    name = $browserInfo.name
    channel = $browserInfo.channel
    path = $browserInfo.path
    source = $browserInfo.source
    version = $browserInfo.version
    allowExecutablePathFallback = [bool]$AllowExecutablePathFallback
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($launchConfigPath, ($launchConfig | ConvertTo-Json -Depth 5), $utf8NoBom)

$runner = @'
const { chromium } = require("playwright");
const fs = require("fs");

const url = process.argv[2];
const timeoutMs = Number(process.argv[3] || 30000);
const resultPath = process.argv[4];
const desktopShot = process.argv[5];
const mobileShot = process.argv[6];
const launchConfigPath = process.argv[7];
const launchConfig = JSON.parse(fs.readFileSync(launchConfigPath, "utf8").replace(/^\uFEFF/, ""));

const targets = [
  {
    name: "desktop",
    screenshot: desktopShot,
    viewport: { width: 1366, height: 900 },
    isMobile: false,
    hasTouch: false
  },
  {
    name: "mobile",
    screenshot: mobileShot,
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true
  }
];

function shouldIgnoreUrl(rawUrl) {
  return /\/favicon\.ico(?:$|\?)/i.test(rawUrl || "");
}

async function inspectOverflow(page) {
  return page.evaluate(() => {
    const viewportWidth = window.innerWidth;
    const scrollWidth = document.documentElement.scrollWidth;
    const overflowAmount = Math.max(0, scrollWidth - viewportWidth);
    const offenders = Array.from(document.querySelectorAll("body *"))
      .map((el) => {
        const rect = el.getBoundingClientRect();
        return {
          tag: el.tagName,
          id: el.id || "",
          className: String(el.className || "").slice(0, 100),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
          text: (el.innerText || el.value || el.getAttribute("aria-label") || "").trim().slice(0, 140)
        };
      })
      .filter((item) => item.width > 0 && (item.right > viewportWidth + 1 || item.left < -1))
      .slice(0, 20);

    return {
      ok: overflowAmount <= 1 && offenders.length === 0,
      hasOverflow: overflowAmount > 1 || offenders.length > 0,
      viewportWidth,
      scrollWidth,
      overflowAmount,
      offenders
    };
  });
}

async function inspectPersistence(page, timeoutMs) {
  const result = {
    checked: false,
    ok: false,
    targetView: "settings",
    beforeReloadVisible: false,
    afterReloadVisible: false,
    storageViewBeforeReload: "",
    storageViewAfterReload: "",
    reason: ""
  };

  const hasSettingsToggle = await page.locator("#settingsToggle").count().catch(() => 0);
  const hasSettingsView = await page.locator("#settingsView").count().catch(() => 0);
  if (!hasSettingsToggle || !hasSettingsView) {
    result.reason = "settings view controls not found";
    return result;
  }

  result.checked = true;
  const alreadyVisible = await page.evaluate(() => {
    const el = document.querySelector("#settingsView");
    return !!el && !el.classList.contains("hidden") && getComputedStyle(el).display !== "none";
  });
  if (!alreadyVisible) {
    await page.click("#settingsToggle", { timeout: Math.min(timeoutMs, 5000) });
    await page.waitForTimeout(850);
  }

  result.beforeReloadVisible = await page.evaluate(() => {
    const el = document.querySelector("#settingsView");
    return !!el && !el.classList.contains("hidden") && getComputedStyle(el).display !== "none";
  });
  result.storageViewBeforeReload = await page.evaluate(() => {
    try { return localStorage.getItem("btdiggRd.view.v1") || ""; } catch (err) { return ""; }
  });

  await page.reload({ waitUntil: "domcontentloaded", timeout: timeoutMs });
  await page.waitForLoadState("networkidle", { timeout: Math.min(timeoutMs, 10000) }).catch(() => {});
  await page.waitForTimeout(850);

  result.afterReloadVisible = await page.evaluate(() => {
    const el = document.querySelector("#settingsView");
    return !!el && !el.classList.contains("hidden") && getComputedStyle(el).display !== "none";
  });
  result.storageViewAfterReload = await page.evaluate(() => {
    try { return localStorage.getItem("btdiggRd.view.v1") || ""; } catch (err) { return ""; }
  });
  result.ok = result.beforeReloadVisible && result.afterReloadVisible;
  if (!result.ok) {
    result.reason = "settings view did not persist after reload";
  }
  return result;
}

async function inspectTarget(browser, target) {
  const context = await browser.newContext({
    viewport: target.viewport,
    isMobile: target.isMobile,
    hasTouch: target.hasTouch,
    deviceScaleFactor: target.isMobile ? 2 : 1
  });

  let interceptedUiState = null;
  await context.route("**/api/ui-state", async (route) => {
    const request = route.request();
    const method = request.method().toUpperCase();
    if (method === "POST") {
      let body = {};
      try {
        body = JSON.parse(request.postData() || "{}");
      } catch (err) {
        body = {};
      }
      interceptedUiState = {
        ...(body.state || {}),
        client_id: body.client_id || "",
        client_updated_at: body.client_updated_at || Date.now(),
        server_updated_at: Date.now(),
        intercepted_by_ui_check: true
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, state: interceptedUiState })
      });
      return;
    }
    if (method === "GET" && interceptedUiState) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, state: interceptedUiState })
      });
      return;
    }
    await route.continue();
  });

  const page = await context.newPage();

  const consoleMessages = [];
  const pageErrors = [];
  const failedRequests = [];
  const responseErrors = [];

  page.on("console", (msg) => {
    if (["error", "warning"].includes(msg.type())) {
      consoleMessages.push({ type: msg.type(), text: msg.text().slice(0, 1000) });
    }
  });

  page.on("pageerror", (err) => {
    pageErrors.push(String(err && err.stack ? err.stack : err).slice(0, 1500));
  });

  page.on("requestfailed", (request) => {
    const requestUrl = request.url();
    if (!shouldIgnoreUrl(requestUrl)) {
      failedRequests.push({
        url: requestUrl,
        method: request.method(),
        failure: request.failure()
      });
    }
  });

  page.on("response", (response) => {
    const responseUrl = response.url();
    if (response.status() >= 400 && !shouldIgnoreUrl(responseUrl)) {
      responseErrors.push({
        url: responseUrl,
        status: response.status(),
        statusText: response.statusText()
      });
    }
  });

  let mainStatus = 0;
  let snapshot = {};
  let overflow = { ok: false, hasOverflow: true, reason: "not checked" };
  let persistence = { checked: false, ok: false, reason: "not checked" };
  try {
    const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
    mainStatus = response ? response.status() : 0;
    await page.waitForLoadState("networkidle", { timeout: Math.min(timeoutMs, 10000) }).catch(() => {});
    await page.waitForTimeout(750);

    snapshot = await page.evaluate(() => {
      const bodyText = (document.body && document.body.innerText || "").trim();
      const controls = Array.from(document.querySelectorAll(
        "button,a,input,select,textarea,[role=tab],[data-tab],[data-section],[data-view]"
      )).slice(0, 120).map((el) => ({
        tag: el.tagName,
        id: el.id || "",
        name: el.getAttribute("name") || "",
        type: el.getAttribute("type") || "",
        role: el.getAttribute("role") || "",
        text: (el.innerText || el.value || el.getAttribute("aria-label") || "").trim().slice(0, 120),
        dataTab: el.getAttribute("data-tab") || "",
        dataSection: el.getAttribute("data-section") || "",
        dataView: el.getAttribute("data-view") || ""
      }));
      const headings = Array.from(document.querySelectorAll("h1,h2,h3")).slice(0, 30)
        .map((el) => (el.innerText || "").trim()).filter(Boolean);
      const storage = {};
      try {
        for (let i = 0; i < localStorage.length; i += 1) {
          const key = localStorage.key(i);
          storage[key] = localStorage.getItem(key);
        }
      } catch (err) {
        storage.__error = String(err);
      }
      return {
        title: document.title || "",
        url: location.href,
        bodyChars: bodyText.length,
        bodySample: bodyText.slice(0, 1500),
        headings,
        controls,
        localStorage: storage
      };
    });

    overflow = await inspectOverflow(page);
    await page.screenshot({ path: target.screenshot, fullPage: true });
    persistence = await inspectPersistence(page, timeoutMs);
  } finally {
    await context.close();
  }

  const textForCheck = `${snapshot.title || ""}\n${snapshot.bodySample || ""}`;
  const appLoaded = snapshot.bodyChars >= 20 && /BTDigg|Real-Debrid|RD|Buscar|Limpiar/i.test(textForCheck);
  const ok = (
    mainStatus > 0 &&
    mainStatus < 400 &&
    appLoaded &&
    consoleMessages.filter((x) => x.type === "error").length === 0 &&
    pageErrors.length === 0 &&
    failedRequests.length === 0 &&
    responseErrors.length === 0 &&
    overflow.ok &&
    persistence.ok
  );

  return {
    name: target.name,
    ok,
    mainStatus,
    appLoaded,
    screenshot: target.screenshot,
    consoleMessages,
    pageErrors,
    failedRequests,
    responseErrors,
    overflow,
    persistence,
    snapshot
  };
}

async function launchBrowser() {
  const launchOptions = { headless: true };
  if (launchConfig.mode === "system" && launchConfig.channel) {
    launchOptions.channel = launchConfig.channel;
  }

  try {
    return await chromium.launch(launchOptions);
  } catch (err) {
    if (
      launchConfig.mode === "system" &&
      launchConfig.allowExecutablePathFallback &&
      launchConfig.path
    ) {
      launchConfig.channelLaunchError = String(err && err.message ? err.message : err).slice(0, 1000);
      launchConfig.usedExecutablePathFallback = true;
      return await chromium.launch({ headless: true, executablePath: launchConfig.path });
    }
    throw err;
  }
}

(async () => {
  const browser = await launchBrowser();
  const results = [];
  try {
    for (const target of targets) {
      results.push(await inspectTarget(browser, target));
    }
  } finally {
    await browser.close();
  }

  const totals = {
    consoleErrors: results.reduce((n, r) => n + r.consoleMessages.filter((x) => x.type === "error").length, 0),
    consoleWarnings: results.reduce((n, r) => n + r.consoleMessages.filter((x) => x.type === "warning").length, 0),
    pageErrors: results.reduce((n, r) => n + r.pageErrors.length, 0),
    failedRequests: results.reduce((n, r) => n + r.failedRequests.length, 0),
    responseErrors: results.reduce((n, r) => n + r.responseErrors.length, 0),
    overflowFailures: results.reduce((n, r) => n + (r.overflow.ok ? 0 : 1), 0),
    persistenceFailures: results.reduce((n, r) => n + (r.persistence.ok ? 0 : 1), 0)
  };

  const payload = {
    ok: results.every((r) => r.ok),
    checkedAt: new Date().toISOString(),
    url,
    timeoutMs,
    browser: launchConfig,
    totals,
    results
  };

  fs.writeFileSync(resultPath, JSON.stringify(payload, null, 2), "utf8");
  console.log(JSON.stringify(payload, null, 2));
  process.exit(payload.ok ? 0 : 1);
})().catch((err) => {
  const payload = {
    ok: false,
    checkedAt: new Date().toISOString(),
    url,
    browser: launchConfig,
    fatal: String(err && err.stack ? err.stack : err)
  };
  fs.writeFileSync(resultPath, JSON.stringify(payload, null, 2), "utf8");
  console.error(payload.fatal);
  process.exit(1);
});
'@

[System.IO.File]::WriteAllText($runnerPath, $runner, $utf8NoBom)

Remove-Item -LiteralPath $resultPath -ErrorAction SilentlyContinue
$raw = & $nodePath $runnerPath $Url $TimeoutMs $resultPath $desktopShot $mobileShot $launchConfigPath
$exit = $LASTEXITCODE
if (-not (Test-Path -LiteralPath $resultPath)) {
    exit $exit
}
$result = Get-Content -Raw -Path $resultPath | ConvertFrom-Json

Write-Host "URL: $($result.url)"
Write-Host ("NAVEGADOR: {0} CANAL={1} ORIGEN={2} VERSION={3}" -f $result.browser.name, $result.browser.channel, $result.browser.source, $result.browser.version)
foreach ($item in $result.results) {
    $state = if ($item.ok) { "OK" } else { "FALLO" }
    $overflowState = if ($item.overflow.ok) { "OK" } else { "FALLO" }
    $persistenceState = if ($item.persistence.ok) { "OK" } else { "FALLO" }
    Write-Host ("{0}: {1} HTTP={2} APP={3} OVERFLOW={4} PERSISTENCIA={5} CAPTURA={6}" -f $item.name.ToUpperInvariant(), $state, $item.mainStatus, $item.appLoaded, $overflowState, $persistenceState, $item.screenshot)
}
Write-Host ("CONSOLA_ERRORES: {0}" -f $result.totals.consoleErrors)
Write-Host ("CONSOLA_AVISOS: {0}" -f $result.totals.consoleWarnings)
Write-Host ("PAGINA_ERRORES: {0}" -f $result.totals.pageErrors)
Write-Host ("RED_FALLOS: {0}" -f ($result.totals.failedRequests + $result.totals.responseErrors))
Write-Host ("OVERFLOW_FALLOS: {0}" -f $result.totals.overflowFailures)
Write-Host ("PERSISTENCIA_FALLOS: {0}" -f $result.totals.persistenceFailures)
Write-Host "RESULTADO_JSON: $resultPath"

if ($exit -ne 0) {
    exit $exit
}
