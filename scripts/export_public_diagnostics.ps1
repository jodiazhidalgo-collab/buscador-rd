$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$AppDir = Join-Path $Root "services\btdigg-rd\app"
$PublicDir = Join-Path $Root "diagnostics_public"

$env:DATA_DIR = Join-Path $Root "config\btdigg-rd\data"
$env:BTDIGG_PUBLIC_DIAGNOSTICS_DIR = $PublicDir
$env:BTDIGG_PUBLIC_DIAGNOSTICS_TRIGGER = "manual-script"

$Extra = @()
$CloudflaredData = Join-Path $Root "config\cloudflared\data"
$CloudflaredLogs = Join-Path $Root "config\cloudflared\logs"
$WhisperLogs = Join-Path $Root "config\whisper\logs"
if (Test-Path -LiteralPath $CloudflaredData) { $Extra += "$CloudflaredData=cloudflared/data" }
if (Test-Path -LiteralPath $CloudflaredLogs) { $Extra += "$CloudflaredLogs=cloudflared/logs" }
if (Test-Path -LiteralPath $WhisperLogs) { $Extra += "$WhisperLogs=whisper/logs" }
$env:BTDIGG_PUBLIC_DIAGNOSTICS_EXTRA_ROOTS = ($Extra -join ";")

Push-Location $AppDir
try {
    python -m api.btdigg_rd.public_diagnostics
}
finally {
    Pop-Location
}
