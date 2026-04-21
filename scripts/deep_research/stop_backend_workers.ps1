Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$statePath = Join-Path $repoRoot "backend\logs\deep_research_process_state.json"
$pids = @()
if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    foreach ($name in @("BackendPid", "DispatchPid", "NoncorePid")) {
        $value = $state.$name
        if ($value) {
            $pids += [int]$value
        }
    }
}

foreach ($procId in $pids) {
    try {
        $proc = Get-Process -Id $procId -ErrorAction Stop
        Stop-Process -Id $proc.Id -Force -ErrorAction Stop
    }
    catch {
        Write-Warning "停止进程失败 PID=${procId}: $($_.Exception.Message)"
    }
}

if (Test-Path -LiteralPath $statePath) {
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
}

[pscustomobject]@{
    StoppedAt = (Get-Date).ToString("o")
    StoppedProcessIds = @($pids)
} | ConvertTo-Json -Depth 3
