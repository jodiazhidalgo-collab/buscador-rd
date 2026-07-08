$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")
$diagRoot = Join-Path $root "config\btdigg-rd\data\diagnostics\btdigg"

if (-not (Test-Path -LiteralPath $diagRoot)) {
    Write-Output "SIN_DIAGNOSTICOS: no existe config\btdigg-rd\data\diagnostics\btdigg"
    exit 0
}

$summary = Get-ChildItem -LiteralPath $diagRoot -Filter "summary.json" -Recurse -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $summary) {
    Write-Output "SIN_SUMMARY: no hay summary.json bajo config\btdigg-rd\data\diagnostics\btdigg"
    exit 0
}

$dir = Split-Path -Parent $summary.FullName
$json = Get-Content -LiteralPath $summary.FullName -Raw | ConvertFrom-Json

Write-Output "DIAGNOSTICO: $dir"
Write-Output "SUMMARY: $($summary.LastWriteTime)"

foreach ($name in @("status", "state", "ok", "success", "job_id", "stage", "error", "warning")) {
    if ($json.PSObject.Properties.Name -contains $name) {
        $value = $json.$name
        if ($null -ne $value) { Write-Output ("{0}: {1}" -f $name.ToUpperInvariant(), $value) }
    }
}

foreach ($fileName in @("errors.jsonl", "warnings.jsonl", "events.jsonl")) {
    $file = Join-Path $dir $fileName
    if (Test-Path -LiteralPath $file) {
        $count = (Get-Content -LiteralPath $file | Measure-Object -Line).Lines
        Write-Output "$($fileName.ToUpperInvariant()): $count lineas"
        Get-Content -LiteralPath $file -Tail 3 | ForEach-Object {
            $_ -replace '(token|password|pass|secret|api_key|apikey)["=: ]+[^", ]+', '$1=***'
        }
    }
}
