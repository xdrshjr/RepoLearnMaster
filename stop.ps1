# RepoLearn shutdown script. Idempotent: safe to run twice, and safe to run when
# nothing was started.
#
#   .\stop.ps1            # kill recorded PIDs, then sweep the ports
#   .\stop.ps1 -Quiet     # no output (for scripts)
#
# NOTE: ASCII-only on purpose (PowerShell 5.1 + ANSI code page, see start.ps1).
#
# Strategy, in order:
#   1. read .run/*.pid and taskkill /T /F -- kills the whole process tree, which
#      matters because `pnpm dev` spawns node children;
#   2. sweep the three known ports -- covers the case where the PID file was lost
#      (e.g. the machine was rebooted, or the service was started by hand);
#   3. delete the PID files.
#
# Step 2 is what makes this reliable: a PID file is a *hint*, a listening socket
# is the *fact*.

param(
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$runDir = Join-Path $root ".run"

function Say([string]$Message, [string]$Color = "Gray") {
    if (-not $Quiet) { Write-Host $Message -ForegroundColor $Color }
}

$stopped = 0

# ---------------------------------------------------------------------- step 1
Say "Stopping recorded services..."
foreach ($name in @("web", "api", "kernel")) {
    $pidFile = Join-Path $runDir "$name.pid"
    if (-not (Test-Path $pidFile)) { continue }
    $raw = (Get-Content $pidFile -Raw).Trim()
    if ($raw -notmatch "^\d+$") {
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        continue
    }
    $targetPid = [int]$raw
    $proc = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
    if ($null -ne $proc) {
        Say "  $name (pid $targetPid)"
        & taskkill /PID $targetPid /T /F 2>&1 | Out-Null
        $stopped = $stopped + 1
    }
    else {
        Say "  $name (pid $targetPid) already gone"
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------- step 2
Say "Sweeping ports 3000 / 8000 / 8787 (and any configured overrides)..."
$ports = @(3000, 8000, 8787)
$portsFile = Join-Path $runDir "ports.json"
if (Test-Path $portsFile) {
    try {
        $cfg = Get-Content $portsFile -Raw | ConvertFrom-Json
        foreach ($key in @("web", "api", "kernel")) {
            $value = $cfg.$key
            if ($null -ne $value -and [int]$value -gt 0) { $ports += [int]$value }
        }
    }
    catch { }
}
$ports = $ports | Select-Object -Unique

foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $ownerPid = $conn.OwningProcess
        if ($ownerPid -le 4) { continue }   # System / Idle: never touch
        $proc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
        if ($null -eq $proc) { continue }
        Say "  port $port held by $($proc.ProcessName) (pid $ownerPid) -> killing"
        & taskkill /PID $ownerPid /T /F 2>&1 | Out-Null
        $stopped = $stopped + 1
    }
}

# ---------------------------------------------------------------------- step 3
Get-ChildItem -Path $runDir -Filter "*.pid" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $runDir "ports.json") -Force -ErrorAction SilentlyContinue

if ($stopped -gt 0) {
    Say "Stopped $stopped process(es)." "Green"
}
else {
    Say "Nothing was running." "Green"
}
Say "Note: .run/preflight.json is kept so start.ps1 can show the last Gate 0 result."
exit 0
