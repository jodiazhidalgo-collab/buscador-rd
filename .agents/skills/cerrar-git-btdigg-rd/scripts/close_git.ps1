param(
    [string]$Message = "",
    [switch]$NoCommit,
    [switch]$NoPush,
    [switch]$ForceCleanup
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
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo al hacer push al remoto $remote."
    }
}

function Invoke-ResidueCleanup {
    param(
        [string]$Root,
        [string]$Stage
    )

    $residueScript = Join-Path $Root ".agents\skills\limpiar-residuos-btdigg-rd\scripts\clean_residues.ps1"
    if (Test-Path -LiteralPath $residueScript) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $residueScript
        if ($LASTEXITCODE -ne 0) {
            throw "Fallo la limpieza de residuos en la fase $Stage."
        }
    }

    $removed = Remove-SafeGeneratedJunk -Root $Root
    Write-Host "Basura generada limpiada ($Stage): $removed"
}

$root = Assert-InRepoRoot

$initialStatus = @(git status --short)
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo leer el estado inicial de Git."
}
if ($initialStatus.Count -eq 0 -and -not $ForceCleanup) {
    Write-Host "Git limpio de inicio. No limpio, no hago commit y no hago push."
    exit 0
}

Invoke-ResidueCleanup -Root $root -Stage "pre-commit"

$status = @(git status --short)
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo leer Git despues de limpiar."
}
if ($status.Count -eq 0) {
    Write-Host "No hay cambios versionables despues de la limpieza. No hago commit ni push."
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
if ($LASTEXITCODE -ne 0) {
    throw "git diff --check ha detectado errores."
}
git add -A
if ($LASTEXITCODE -ne 0) {
    throw "No se pudieron preparar los cambios para el commit."
}

$staged = @(git diff --cached --name-only)
if ($staged.Count -eq 0) {
    Write-Host "No hay cambios stageables tras limpiar basura."
    exit 0
}

$commitExit = 0
try {
    git commit -m $Message
    $commitExit = $LASTEXITCODE
}
finally {
    Invoke-ResidueCleanup -Root $root -Stage "post-commit"
}
if ($commitExit -ne 0) {
    throw "El commit fallo. Los residuos del hook se han limpiado."
}

Invoke-PushIfConfigured -SkipPush:$NoPush

$finalStatus = @(git status --short)
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo comprobar el estado final de Git."
}
if ($finalStatus.Count -ne 0) {
    Write-Host "--- git sigue sucio ---"
    $finalStatus | ForEach-Object { Write-Host $_ }
    throw "Git no ha quedado limpio."
}

Write-Host "Git limpio tras commit y push."
