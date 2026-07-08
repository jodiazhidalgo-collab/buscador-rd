param(
    [string]$Message = "",
    [switch]$NoCommit,
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"

function Assert-InRepoRoot {
    $inside = (git rev-parse --is-inside-work-tree).Trim()
    if ($inside -ne "true") {
        throw "No estoy dentro de un repositorio Git."
    }
    $prefix = (git rev-parse --show-prefix).Trim()
    if ($prefix) {
        $root = (git rev-parse --show-toplevel).Trim()
        throw "Ejecuta este cierre desde la raiz del proyecto: $root"
    }
    $cwd = (Get-Location).ProviderPath
    return [System.IO.Path]::GetFullPath($cwd)
}

function Remove-SafeGeneratedJunk {
    param([string]$Root)

    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $targets = @()
    $targets += Get-ChildItem -LiteralPath $Root -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue
    $targets += Get-ChildItem -LiteralPath $Root -Directory -Recurse -Force -Filter ".pytest_cache" -ErrorAction SilentlyContinue
    $targets += Get-ChildItem -LiteralPath $Root -File -Recurse -Force -Filter "*.pyc" -ErrorAction SilentlyContinue

    $removed = 0
    foreach ($target in $targets) {
        $full = [System.IO.Path]::GetFullPath($target.FullName)
        if (-not $full.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Ruta fuera del proyecto bloqueada: $full"
        }
        if (Test-Path -LiteralPath $full) {
            Remove-Item -LiteralPath $full -Recurse -Force
            $removed += 1
        }
    }
    return $removed
}

function Invoke-PushIfConfigured {
    param([switch]$SkipPush)

    if ($SkipPush) {
        Write-Host "NoPush activo: no hago push."
        return
    }

    $branch = (git branch --show-current).Trim()
    if (-not $branch) {
        Write-Host "Sin rama actual: no hago push."
        return
    }

    $remote = ""
    try {
        $remote = (git config --get "branch.$branch.remote").Trim()
    } catch {
        $remote = ""
    }
    if (-not $remote) {
        $remote = "origin"
    }

    $remoteUrl = ""
    try {
        $remoteUrl = (git remote get-url $remote).Trim()
    } catch {
        $remoteUrl = ""
    }
    if (-not $remoteUrl) {
        Write-Host "Sin remoto configurado para push."
        return
    }

    $upstream = ""
    try {
        $upstream = (git rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>$null).Trim()
    } catch {
        $upstream = ""
    }

    if ($upstream) {
        git push
    } else {
        git push -u $remote $branch
    }
}

$root = Assert-InRepoRoot

$residueScript = Join-Path $root ".agents\skills\limpiar-residuos-btdigg-rd\scripts\clean_residues.ps1"
if (Test-Path -LiteralPath $residueScript) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $residueScript
}

$removed = Remove-SafeGeneratedJunk -Root $root
Write-Host "Basura generada limpiada: $removed"

$status = @(git status --short)
if ($status.Count -eq 0) {
    Write-Host "Git limpio. No hay cambios que cerrar."
    Invoke-PushIfConfigured -SkipPush:$NoPush
    exit 0
}

Write-Host "--- cambios pendientes ---"
$status | ForEach-Object { Write-Host $_ }

if ($NoCommit) {
    Write-Host "NoCommit activo: no hago commit."
    exit 0
}

if (-not $Message.Trim()) {
    $Message = "chore: cierre local automatico"
}

git diff --check
git add -A

$staged = @(git diff --cached --name-only)
if ($staged.Count -eq 0) {
    Write-Host "No hay cambios stageables tras limpiar basura."
    exit 0
}

git commit -m $Message

Invoke-PushIfConfigured -SkipPush:$NoPush

$finalStatus = @(git status --short)
if ($finalStatus.Count -ne 0) {
    Write-Host "--- git sigue sucio ---"
    $finalStatus | ForEach-Object { Write-Host $_ }
    throw "Git no ha quedado limpio."
}

Write-Host "Git limpio tras commit y push."
