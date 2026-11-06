# RepoLearn one-command dev launcher (Windows PowerShell 5.1+).
#
#   .\start.ps1                # install if needed, migrate, start kernel+api+web
#   .\start.ps1 -SkipInstall   # fast restart (no pip/pnpm)
#   .\start.ps1 -NoWeb         # backend only (API + kernel)
#   .\start.ps1 -Prod          # next build && next start, REPOLEARN_ENV=production
#   .\start.ps1 -Port 3100     # change web port (API/kernel keep their own ports)
#
# NOTE: ASCII-only on purpose. PowerShell 5.1 reads .ps1 with the ANSI code page
# unless the file has a UTF-8 BOM, so non-ASCII here breaks on zh-CN Windows.
#
# Exit codes: 0 ok, 1 prerequisite missing, 2 port conflict, 3 service failed to
# become healthy (logs are dumped to the console in that case).

param(
    [switch]$SkipInstall,
    [switch]$NoWeb,
    [switch]$Prod,
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$runDir = Join-Path $root ".run"
$logDir = Join-Path $root "var\logs"
foreach ($d in @($runDir, $logDir, (Join-Path $root "var\data"), (Join-Path $root "var\objects"))) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

function Say([string]$Message, [string]$Color = "Gray") {
    Write-Host $Message -ForegroundColor $Color
}

function Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

# --------------------------------------------------------------------------
# 1. environment + Gate 0
# --------------------------------------------------------------------------
Step "Checking environment (node / python / pnpm / Gate 0)"
& (Join-Path $root "scripts\check_env.ps1")
if ($LASTEXITCODE -ne 0) {
    Say "Environment check failed. See the messages above." "Red"
    exit 1
}

$preflightPath = Join-Path $runDir "preflight.json"
if (Test-Path $preflightPath) {
    try {
        $pre = Get-Content $preflightPath -Raw | ConvertFrom-Json
        Say ("Gates: G1 agent-core={0}  G2 pdf={1}  G3 analysis={2}" -f $pre.gates.g1, $pre.gates.g2, $pre.gates.g3)
        if ($pre.gates.g1 -ne "ok") {
            Say "  ! Agent kernel unavailable -> generated courses will be the simplified (static) variant." "Yellow"
        }
        if ($pre.gates.g2 -ne "ok") {
            Say "  ! Chromium unavailable -> PDF export becomes a print view." "Yellow"
        }
        if ($pre.gates.g3 -ne "ok") {
            Say "  ! tree-sitter unavailable -> anchor confidence will be lower." "Yellow"
        }
    }
    catch {
        Say "  (preflight.json unreadable, continuing)" "Yellow"
    }
}

# --------------------------------------------------------------------------
# 2. secrets + .env
# --------------------------------------------------------------------------
Step "Preparing .env"
$envPath = Join-Path $root ".env"
$envExample = Join-Path $root ".env.example"
if (-not (Test-Path $envPath)) {
    Copy-Item $envExample $envPath
    Say "  created .env from .env.example"
}

function New-UrlSafeKey {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
}

function New-Token {
    $bytes = New-Object byte[] 24
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_").Replace("=", "")
}

$envText = Get-Content $envPath -Raw
$changed = $false
if ($envText -notmatch "(?m)^REPOLEARN_SECRET_KEY=.+") {
    $key = New-UrlSafeKey
    $envText = $envText -replace "(?m)^REPOLEARN_SECRET_KEY=.*$", "REPOLEARN_SECRET_KEY=$key"
    $changed = $true
    Say "  generated REPOLEARN_SECRET_KEY"
}
if ($envText -notmatch "(?m)^REPOLEARN_INTERNAL_TOKEN=.+") {
    $token = New-Token
    $envText = $envText -replace "(?m)^REPOLEARN_INTERNAL_TOKEN=.*$", "REPOLEARN_INTERNAL_TOKEN=$token"
    $changed = $true
    Say "  generated REPOLEARN_INTERNAL_TOKEN"
}
if ($Port -gt 0) {
    $envText = $envText -replace "(?m)^REPOLEARN_WEB_PORT=.*$", "REPOLEARN_WEB_PORT=$Port"
    $changed = $true
    Say "  web port set to $Port"
}
if ($Prod) {
    $envText = $envText -replace "(?m)^REPOLEARN_ENV=.*$", "REPOLEARN_ENV=production"
    $changed = $true
}
if ($changed) {
    Set-Content -Path $envPath -Value $envText -Encoding UTF8 -NoNewline
}

# parse the values we need in this script
$settings = @{}
foreach ($line in (Get-Content $envPath)) {
    if ($line -match "^\s*([A-Z0-9_]+)\s*=\s*(.*)$") {
        $settings[$Matches[1]] = $Matches[2].Trim()
    }
}
function SettingOr([string]$Name, [string]$Default) {
    if ($settings.ContainsKey($Name) -and $settings[$Name] -ne "") { return $settings[$Name] }
    return $Default
}

$apiPort = [int](SettingOr "REPOLEARN_API_PORT" "8000")
$kernelPort = [int](SettingOr "REPOLEARN_KERNEL_PORT" "8787")
$webPort = [int](SettingOr "REPOLEARN_WEB_PORT" "3000")
$internalToken = SettingOr "REPOLEARN_INTERNAL_TOKEN" ""

# Resolve the pnpm launcher once.
#
# On Windows every pnpm "executable" is a shim: `pnpm.cmd` (cmd) or `pnpm.ps1`
# (PowerShell). Start-Process cannot launch either one -- it fails with
# "%1 is not a valid Win32 application" -- so the web service is started through
# `cmd.exe /c "<shim>" ...`, which is exactly how a user would run it by hand.
$pnpmCmd = Get-Command pnpm -ErrorAction SilentlyContinue
$pnpmExe = ""
if ($null -ne $pnpmCmd) {
    $candidate = $pnpmCmd.Source
    if ($null -eq $candidate -or $candidate -eq "") { $candidate = $pnpmCmd.Path }
    $cmdShim = [System.IO.Path]::ChangeExtension($candidate, ".cmd")
    if (Test-Path $cmdShim) { $pnpmExe = $cmdShim }
    elseif ($null -ne $candidate) { $pnpmExe = $candidate }
}
if ($null -eq $pnpmExe -or $pnpmExe -eq "") {
    Say "pnpm not found. Run: corepack enable   (or: npm i -g pnpm)" "Red"
    exit 1
}

# --------------------------------------------------------------------------
# 3. port preflight (fail fast, leave nothing half-started)
# --------------------------------------------------------------------------
Step "Checking ports $webPort / $apiPort / $kernelPort"
$busy = @()
foreach ($p in @($webPort, $apiPort, $kernelPort)) {
    $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($conn) { $busy += $p }
}
if ($busy.Count -gt 0) {
    Say "Port(s) already in use: $($busy -join ', ')" "Red"
    Say "Run .\stop.ps1 to clean up RepoLearn processes, or pick another port with -Port." "Yellow"
    exit 2
}

# --------------------------------------------------------------------------
# 4. dependencies
# --------------------------------------------------------------------------
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$venvPip = Join-Path $root ".venv\Scripts\pip.exe"

if (-not $SkipInstall) {
    Step "Installing Python dependencies"
    if (-not (Test-Path $venvPython)) {
        & python -m venv .venv
        if ($LASTEXITCODE -ne 0) { Say "python -m venv failed" "Red"; exit 1 }
    }
    & $venvPip install -e ".[dev]" -q
    if ($LASTEXITCODE -ne 0) { Say "pip install failed. If this is a network issue you can retry with: $venvPip install -e . --no-deps" "Yellow" }

    Step "Installing Node dependencies (pnpm)"
    & pnpm install
    if ($LASTEXITCODE -ne 0) {
        Say "pnpm install failed." "Red"
        Say "If it complains about ignored build scripts, run: pnpm approve-builds --all --yes" "Yellow"
        Say "The API can still start without the Node side; continue with -NoWeb? (Ctrl+C to abort)" "Yellow"
        Start-Sleep -Seconds 5
    }
}
else {
    if (-not (Test-Path $venvPython)) {
        Say "-SkipInstall was given but .venv is missing. Run start.ps1 without -SkipInstall first." "Red"
        exit 1
    }
}

# --------------------------------------------------------------------------
# 5. migrate + seed
# --------------------------------------------------------------------------
Step "Running database migrations"
& $venvPython -m repolearn.cli migrate
if ($LASTEXITCODE -ne 0) { Say "migration failed" "Red"; exit 1 }

$seedFlag = Join-Path $runDir "seeded.flag"
if (-not (Test-Path $seedFlag)) {
    Step "Seeding offline demo course (so the UI is usable with no API key)"
    & $venvPython -m repolearn.cli seed-demo
    if ($LASTEXITCODE -eq 0) { Set-Content -Path $seedFlag -Value "ok" -Encoding UTF8 }
}

# --------------------------------------------------------------------------
# 6. launch services (order matters: kernel -> api -> web)
# --------------------------------------------------------------------------
function Save-Pid([string]$Name, [int]$ProcessId) {
    Set-Content -Path (Join-Path $runDir "$Name.pid") -Value $ProcessId -Encoding UTF8
}

function Wait-Http([string]$Url, [int]$TimeoutSeconds, [string]$Name) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) { return $true }
        }
        catch {
            Start-Sleep -Milliseconds 700
        }
    }
    Say "$Name did not become healthy within $TimeoutSeconds s" "Red"
    return $false
}

Step "Starting agent kernel on 127.0.0.1:$kernelPort"
$kernelLog = Join-Path $logDir "kernel.log"
$kernelOut = Join-Path $logDir "kernel.out.log"
$kernelErr = Join-Path $logDir "kernel.err.log"
$kernelArgs = @("--experimental-strip-types", "src/server.ts")
$kernelProc = Start-Process -FilePath "node" -ArgumentList $kernelArgs `
    -WorkingDirectory (Join-Path $root "services\agent-kernel") `
    -RedirectStandardOutput $kernelOut -RedirectStandardError $kernelErr `
    -NoNewWindow -PassThru
Save-Pid "kernel" $kernelProc.Id
Say "  pid $($kernelProc.Id), log var/logs/kernel.log"

$kernelHealthy = Wait-Http "http://127.0.0.1:$kernelPort/healthz" 45 "agent kernel"
if (-not $kernelHealthy) {
    Say "Kernel failed to start (expected if @aragon-agent/core is unavailable)." "Yellow"
    Say "The API will fall back to template generation; courses will be the simplified variant." "Yellow"
}

Step "Starting API on 127.0.0.1:$apiPort"
$apiOut = Join-Path $logDir "api.out.log"
$apiErr = Join-Path $logDir "api.err.log"
$apiProc = Start-Process -FilePath $venvPython `
    -ArgumentList @("-m", "uvicorn", "repolearn.main:app", "--host", "127.0.0.1", "--port", "$apiPort", "--log-level", "info") `
    -WorkingDirectory $root `
    -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr `
    -NoNewWindow -PassThru
Save-Pid "api" $apiProc.Id
Say "  pid $($apiProc.Id), log var/logs/api.out.log"

if (-not (Wait-Http "http://127.0.0.1:$apiPort/healthz" 60 "api")) {
    Say "---- api.err.log (tail) ----" "Red"
    if (Test-Path $apiErr) { Get-Content $apiErr -Tail 40 | ForEach-Object { Write-Host $_ } }
    Say "---- api.out.log (tail) ----" "Red"
    if (Test-Path $apiOut) { Get-Content $apiOut -Tail 40 | ForEach-Object { Write-Host $_ } }
    Say "Run .\stop.ps1 to clean up, then fix the error above." "Yellow"
    exit 3
}

$webUrl = "http://localhost:$webPort"
if (-not $NoWeb) {
    Step "Starting web (Next.js) on $webUrl"
    $webDir = Join-Path $root "apps\web"
    $webOut = Join-Path $logDir "web.out.log"
    $webErr = Join-Path $logDir "web.err.log"
    # The BFF needs these at runtime; they must never reach the browser bundle.
    $env:REPOLEARN_API_BASE = "http://127.0.0.1:$apiPort"
    $env:REPOLEARN_INTERNAL_TOKEN = $internalToken
    $env:PORT = "$webPort"

    # NODE_ENV must be pinned explicitly.
    #
    # A dev machine very often has a GLOBAL NODE_ENV (this one does:
    # NODE_ENV=production, set for unrelated tooling). Next.js then prints
    # "You are using a non-standard NODE_ENV value" and, in `next dev`, the edge
    # middleware sandbox fails with:
    #     EvalError: Code generation from strings disallowed for this context
    # -- i.e. every single request 500s. Pinning the value here makes the launcher
    # independent of whatever the machine happens to have configured.
    if ($Prod) {
        $env:NODE_ENV = "production"
    }
    else {
        $env:NODE_ENV = "development"
    }

    if ($Prod) {
        Step "Building web for production (-Prod)"
        Push-Location $webDir
        try {
            & cmd.exe /c "`"$pnpmExe`" build"
            if ($LASTEXITCODE -ne 0) { Say "next build failed" "Red"; exit 3 }
        }
        finally { Pop-Location }
        $webArgs = @("start", "--port", "$webPort")
    }
    else {
        $webArgs = @("dev", "--port", "$webPort")
    }

    # Launch through cmd.exe: both `pnpm.cmd` and `pnpm.ps1` are shims that
    # Start-Process cannot execute directly (see the resolution block above).
    $argLine = '/c "' + $pnpmExe + '" ' + ($webArgs -join ' ')
    $webProc = Start-Process -FilePath "cmd.exe" -ArgumentList $argLine `
        -WorkingDirectory $webDir `
        -RedirectStandardOutput $webOut -RedirectStandardError $webErr `
        -NoNewWindow -PassThru
    Save-Pid "web" $webProc.Id
    Say "  pid $($webProc.Id), log var/logs/web.out.log"

    if (-not (Wait-Http $webUrl 120 "web")) {
        Say "---- web.err.log (tail) ----" "Red"
        if (Test-Path $webErr) { Get-Content $webErr -Tail 40 | ForEach-Object { Write-Host $_ } }
        Say "API is up; you can still use it directly at http://127.0.0.1:$apiPort/docs" "Yellow"
        exit 3
    }
}

# --------------------------------------------------------------------------
# 7. summary
# --------------------------------------------------------------------------
Step "RepoLearn is up"
Say ""
Say "  Web UI      $webUrl" "Green"
Say "  Setup       $webUrl/setup  (first run: configure an LLM provider)" "Green"
Say "  API         http://127.0.0.1:$apiPort/healthz" "Green"
Say "  API docs    http://127.0.0.1:$apiPort/docs" "Green"
Say "  Kernel      http://127.0.0.1:$kernelPort/healthz" "Green"
Say "  Logs        var/logs/" "Green"
Say ""
Say "  Demo course: open the web UI -- the seeded offline course is already available."
Say "  Stop:        .\stop.ps1"
Say ""
$ports = @{ web = $webPort; api = $apiPort; kernel = $kernelPort } | ConvertTo-Json
Set-Content -Path (Join-Path $runDir "ports.json") -Value $ports -Encoding UTF8
exit 0
