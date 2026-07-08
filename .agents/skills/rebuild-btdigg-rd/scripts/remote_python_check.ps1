param(
    [string]$HostName = "lacabra@192.168.1.159",
    [string]$Python = "python3",
    [string]$ScriptPath,
    [string]$Code,
    [switch]$ProbeOnly
)

$ErrorActionPreference = "Stop"

function Invoke-RemotePython([string]$Payload) {
    $clean = $Payload -replace "`r", ""
    $clean | ssh $HostName $Python -
}

$probe = @'
print("REMOTE_STDIN_OK")
'@

Write-Host "Validando canal Python por stdin..."
$probeResult = Invoke-RemotePython $probe
$probeResult
if (($probeResult -join "`n") -notmatch "REMOTE_STDIN_OK") {
    throw "No se valido el canal remoto por stdin."
}

if ($ProbeOnly) {
    return
}

if ($ScriptPath) {
    if (-not (Test-Path -LiteralPath $ScriptPath)) {
        throw "No existe ScriptPath: $ScriptPath"
    }
    $Code = Get-Content -LiteralPath $ScriptPath -Raw
}

if ([string]::IsNullOrWhiteSpace($Code)) {
    throw "Indica -ProbeOnly, -ScriptPath o -Code."
}

Write-Host "Ejecutando Python remoto por stdin..."
Invoke-RemotePython $Code
