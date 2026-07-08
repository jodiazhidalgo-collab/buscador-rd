param(
    [switch]$DryRun,
    [int]$TmpRetentionDays = 2,
    [int]$ArtifactRetentionDays = 7
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    $inside = (git rev-parse --is-inside-work-tree).Trim()
    if ($inside -ne "true") {
        throw "No estoy dentro de un repositorio Git."
    }
    $prefix = (git rev-parse --show-prefix).Trim()
    if ($prefix) {
        $root = (git rev-parse --show-toplevel).Trim()
        throw "Ejecuta esta limpieza desde la raiz del proyecto: $root"
    }
    return [System.IO.Path]::GetFullPath((Get-Location).ProviderPath)
}

function Assert-UnderRoot {
    param([string]$Root, [string]$Path)

    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Ruta fuera del proyecto bloqueada: $full"
    }
    return $full
}

function Remove-Target {
    param([string]$Root, [System.IO.FileSystemInfo]$Target, [string]$Bucket)

    $full = Assert-UnderRoot -Root $Root -Path $Target.FullName
    if ($DryRun) {
        [pscustomobject]@{ Bucket = $Bucket; Action = "dry-run"; Path = $full }
        return
    }
    if (Test-Path -LiteralPath $full) {
        Remove-Item -LiteralPath $full -Recurse -Force
        [pscustomobject]@{ Bucket = $Bucket; Action = "removed"; Path = $full }
    }
}

function Ensure-CodexRuntime {
    param([string]$Root)

    $paths = @(
        (Join-Path $Root "_codex_runtime"),
        (Join-Path $Root "_codex_runtime\tmp"),
        (Join-Path $Root "_codex_runtime\test-data"),
        (Join-Path $Root "_codex_runtime\artifacts")
    )
    foreach ($path in $paths) {
        Assert-UnderRoot -Root $Root -Path $path | Out-Null
        if (-not $DryRun) {
            New-Item -ItemType Directory -Force -Path $path | Out-Null
        }
    }
}

function Get-SafePythonJunk {
    param([string]$Root)

    $items = @()
    $items += Get-ChildItem -LiteralPath $Root -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue
    $items += Get-ChildItem -LiteralPath $Root -Directory -Recurse -Force -Filter ".pytest_cache" -ErrorAction SilentlyContinue
    $items += Get-ChildItem -LiteralPath $Root -File -Recurse -Force -Filter "*.pyc" -ErrorAction SilentlyContinue
    return $items
}

function Get-SyntheticDataResidues {
    param([string]$Root)

    $patterns = @("job_cancel_*", "codex_test_*", "codex_tmp_*", "unit_test_*")
    $roots = @(
        (Join-Path $Root "config\btdigg-rd\data\jobs"),
        (Join-Path $Root "config\btdigg-rd\data\diagnostics\btdigg\jobs")
    )
    $items = @()
    foreach ($base in $roots) {
        if (-not (Test-Path -LiteralPath $base)) {
            continue
        }
        foreach ($pattern in $patterns) {
            $items += Get-ChildItem -LiteralPath $base -Directory -Recurse -Force -Filter $pattern -ErrorAction SilentlyContinue
        }
    }
    return $items
}

function Get-ExpiredRuntimeItems {
    param([string]$Root)

    $now = Get-Date
    $checks = @(
        @{ Path = (Join-Path $Root "_codex_runtime\tmp"); Days = $TmpRetentionDays; Bucket = "runtime-tmp" },
        @{ Path = (Join-Path $Root "_codex_runtime\test-data"); Days = $TmpRetentionDays; Bucket = "runtime-test-data" },
        @{ Path = (Join-Path $Root "_codex_runtime\artifacts"); Days = $ArtifactRetentionDays; Bucket = "runtime-artifacts" }
    )
    $items = @()
    foreach ($check in $checks) {
        if (-not (Test-Path -LiteralPath $check.Path)) {
            continue
        }
        $cutoff = $now.AddDays(-[int]$check.Days)
        Get-ChildItem -LiteralPath $check.Path -Force -ErrorAction SilentlyContinue | Where-Object {
            $_.LastWriteTime -lt $cutoff
        } | ForEach-Object {
            $items += [pscustomobject]@{ Target = $_; Bucket = $check.Bucket }
        }
    }
    return $items
}

function Get-EmptyRuntimeDirs {
    param([string]$Root)

    $runtimeRoot = Join-Path $Root "_codex_runtime"
    if (-not (Test-Path -LiteralPath $runtimeRoot)) {
        return @()
    }

    $keep = @(
        [System.IO.Path]::GetFullPath((Join-Path $runtimeRoot "tmp")).TrimEnd('\'),
        [System.IO.Path]::GetFullPath((Join-Path $runtimeRoot "test-data")).TrimEnd('\'),
        [System.IO.Path]::GetFullPath((Join-Path $runtimeRoot "artifacts")).TrimEnd('\')
    )

    $dirs = Get-ChildItem -LiteralPath $runtimeRoot -Directory -Recurse -Force -ErrorAction SilentlyContinue |
        Sort-Object { $_.FullName.Length } -Descending

    $empty = @()
    foreach ($dir in $dirs) {
        $full = [System.IO.Path]::GetFullPath($dir.FullName).TrimEnd('\')
        if ($keep -contains $full) {
            continue
        }
        $files = @(Get-ChildItem -LiteralPath $dir.FullName -File -Recurse -Force -ErrorAction SilentlyContinue)
        if ($files.Count -eq 0) {
            $empty += $dir
        }
    }
    return $empty
}

$root = Get-RepoRoot
Ensure-CodexRuntime -Root $root

$results = @()
foreach ($target in (Get-SafePythonJunk -Root $root)) {
    $results += Remove-Target -Root $root -Target $target -Bucket "python-junk"
}
foreach ($target in (Get-SyntheticDataResidues -Root $root)) {
    $results += Remove-Target -Root $root -Target $target -Bucket "synthetic-data"
}
foreach ($entry in (Get-ExpiredRuntimeItems -Root $root)) {
    $results += Remove-Target -Root $root -Target $entry.Target -Bucket $entry.Bucket
}
foreach ($target in (Get-EmptyRuntimeDirs -Root $root)) {
    $results += Remove-Target -Root $root -Target $target -Bucket "runtime-empty-dir"
}

$removed = @($results | Where-Object { $_.Action -eq "removed" }).Count
$dry = @($results | Where-Object { $_.Action -eq "dry-run" }).Count

if ($results.Count) {
    $results | Format-Table -AutoSize
}
Write-Host "Residuos limpiados: $removed"
if ($DryRun) {
    Write-Host "Residuos detectados en modo lectura: $dry"
}
