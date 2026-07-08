param(
    [string]$Url = "http://192.168.1.159:9007/",
    [int]$TimeoutMs = 30000,
    [switch]$SkipInstall
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

$skillRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$projectRoot = Resolve-Path (Join-Path $skillRoot "..\..\..")
$runtime = Join-Path $projectRoot "_codex_runtime\playwright-ui-check"
$artifactRoot = Join-Path $projectRoot "_codex_runtime\artifacts\ui-check"

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null

$nodePath = Get-ToolPath "node.exe"
$npmPath = Get-ToolPath "npm.cmd"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $runtime "ms-playwright"
$env:NODE_PATH = Join-Path $runtime "node_modules"

Push-Location $runtime
try {
    if (-not $SkipInstall) {
        if (-not (Test-Path (Join-Path $runtime "node_modules\playwright"))) {
            & $npmPath install playwright --no-audit --no-fund | Out-Host
        }

        $playwrightCmd = Join-Path $runtime "node_modules\.bin\playwright.cmd"
        if (-not (Test-Path $playwrightCmd)) {
            throw "No encuentro Playwright instalado en $playwrightCmd."
        }
        & $playwrightCmd install chromium | Out-Host
    }
}
finally {
    Pop-Location
}

$runnerPath = Join-Path $artifactRoot "btdigg-rd-ui-check.runner.js"
$resultPath = Join-Path $artifactRoot "btdigg-rd-ui-check.result.json"
$desktopShot = Join-Path $artifactRoot "btdigg-rd-desktop.png"
$mobileShot = Join-Path $artifactRoot "btdigg-rd-mobile.png"

$runner = @'
const { chromium } = require("playwright");
const fs = require("fs");

const url = process.argv[2];
const timeoutMs = Number(process.argv[3] || 30000);
const resultPath = process.argv[4];
const desktopShot = process.argv[5];
const mobileShot = process.argv[6];

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

async function inspectTarget(browser, target) {
  const context = await browser.newContext({
    viewport: target.viewport,
    isMobile: target.isMobile,
    hasTouch: target.hasTouch,
    deviceScaleFactor: target.isMobile ? 2 : 1
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

    await page.screenshot({ path: target.screenshot, fullPage: true });
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
    responseErrors.length === 0
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
    snapshot
  };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
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
    responseErrors: results.reduce((n, r) => n + r.responseErrors.length, 0)
  };

  const payload = {
    ok: results.every((r) => r.ok),
    checkedAt: new Date().toISOString(),
    url,
    timeoutMs,
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
    fatal: String(err && err.stack ? err.stack : err)
  };
  fs.writeFileSync(resultPath, JSON.stringify(payload, null, 2), "utf8");
  console.error(payload.fatal);
  process.exit(1);
});
'@

Set-Content -Path $runnerPath -Value $runner -Encoding UTF8

$raw = & $nodePath $runnerPath $Url $TimeoutMs $resultPath $desktopShot $mobileShot
$exit = $LASTEXITCODE
$result = Get-Content -Raw -Path $resultPath | ConvertFrom-Json

Write-Host "URL: $($result.url)"
foreach ($item in $result.results) {
    $state = if ($item.ok) { "OK" } else { "FALLO" }
    Write-Host ("{0}: {1} HTTP={2} APP={3} CAPTURA={4}" -f $item.name.ToUpperInvariant(), $state, $item.mainStatus, $item.appLoaded, $item.screenshot)
}
Write-Host ("CONSOLA_ERRORES: {0}" -f $result.totals.consoleErrors)
Write-Host ("CONSOLA_AVISOS: {0}" -f $result.totals.consoleWarnings)
Write-Host ("PAGINA_ERRORES: {0}" -f $result.totals.pageErrors)
Write-Host ("RED_FALLOS: {0}" -f ($result.totals.failedRequests + $result.totals.responseErrors))
Write-Host "RESULTADO_JSON: $resultPath"

if ($exit -ne 0) {
    exit $exit
}
