# RepoLearn environment probe (Gate 0). Called by start.ps1; also runnable standalone.
#
# NOTE: This file is intentionally ASCII-only. Windows PowerShell 5.1 reads .ps1
# files with the system ANSI code page unless the file starts with a UTF-8 BOM,
# so non-ASCII text here would be mangled (or fail to parse) on a Chinese-locale
# Windows box -- which is exactly the machine this project targets.
#
# Exit codes:
#   0  environment OK (Gate results may still be "degraded"; that never blocks)
#   1  hard prerequisite missing (node/python version) -- start.ps1 must stop
#
# Writes .run/preflight.json:
#   { "node": "v20.x", "python": "3.12.x", "npm": "10.x", "pnpm": "x",
#     "gates": { "g1": "ok|missing|unknown", "g2": ..., "g3": ... },
#     "detail": { "g1": "...", "g2": "...", "g3": "..." } }

param(
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$runDir = Join-Path $root ".run"
if (-not (Test-Path $runDir)) { New-Item -ItemType Directory -Path $runDir | Out-Null }

# Python probe helper.
#
# WHY A FUNCTION: `$ErrorActionPreference = "Stop"` (set at the top of this file)
# turns ANY stderr output from a native command into a terminating error. Python
# writes its import traceback to stderr, so every G2/G3 probe landed in the catch
# block and reported only "Traceback (most recent call last):" -- useless. The
# helper flips the preference locally, captures the real exit code, and keeps the
# last stderr line for the detail string.
$venvPy = Join-Path $root ".venv\Scripts\python.exe"

function Invoke-PyProbe([string]$Code, [string]$OkNeedle) {
    $result = @{ ok = $false; detail = "" }
    if (-not (Test-Path $venvPy)) {
        $result.detail = "venv not created yet; it will be probed on the next start"
        return $result
    }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $venvPy -c $Code 2>&1
        $exitCode = $LASTEXITCODE
        $text = ($output | Out-String).Trim()
        if ($exitCode -eq 0 -and $text.Contains($OkNeedle)) {
            $result.ok = $true
            $result.detail = "ok"
        }
        else {
            $lines = @($text -split "`r?`n" | Where-Object { $_.Trim() -ne "" })
            $last = ""
            if ($lines.Count -gt 0) { $last = $lines[$lines.Count - 1].Trim() }
            $result.detail = $last
        }
    }
    catch {
        $result.detail = $_.Exception.Message
    }
    finally {
        $ErrorActionPreference = $previous
    }
    return $result
}

$problems = @()
$result = @{
    node   = $null
    python = $null
    npm    = $null
    pnpm   = $null
    gates  = @{ g1 = "unknown"; g2 = "unknown"; g3 = "unknown" }
    detail = @{}
}

function Write-Step([string]$Message) {
    if (-not $Quiet) { Write-Host "  $Message" }
}

# ---------------------------------------------------------------- node / npm
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($null -eq $nodeCmd) {
    $problems += "node not found. Install Node.js 20 LTS or newer: https://nodejs.org/"
}
else {
    $nodeVersion = (& node --version).Trim()
    $result.node = $nodeVersion
    $major = 0
    if ($nodeVersion -match "^v(\d+)") { $major = [int]$Matches[1] }
    if ($major -lt 20) {
        $problems += "node $nodeVersion is too old; Node.js 20+ is required (nvm install 20)."
    }
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($null -ne $npmCmd) { $result.npm = (& npm --version).Trim() }
    else { $problems += "npm not found (it ships with Node.js; reinstall Node)." }
}

$pnpmCmd = Get-Command pnpm -ErrorAction SilentlyContinue
if ($null -ne $pnpmCmd) {
    try { $result.pnpm = (& pnpm --version).Trim() } catch { $result.pnpm = "unknown" }
}
else {
    $problems += "pnpm not found. Run: corepack enable  (or: npm i -g pnpm)"
}

# ------------------------------------------------------------------- python
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCmd) {
    $problems += "python not found. Install Python 3.11+ (tick 'Add python.exe to PATH')."
}
else {
    $pyVersion = (& python --version 2>&1).ToString().Trim()
    $result.python = $pyVersion
    $pyMajor = 0
    $pyMinor = 0
    if ($pyVersion -match "(\d+)\.(\d+)") {
        $pyMajor = [int]$Matches[1]
        $pyMinor = [int]$Matches[2]
    }
    if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 11)) {
        $problems += "$pyVersion is too old; Python 3.11+ is required."
    }
}

# ------------------------------------------------------- Gate G1: agent core
Write-Step "G1: probing @aragon-agent/core ..."
$kernelDir = Join-Path $root "services\agent-kernel"
$probeScript = Join-Path $root "scripts\probe_core.mjs"
$g1 = "missing"
$g1Detail = ""
if ((Test-Path $kernelDir) -and (Test-Path $probeScript)) {
    try {
        $raw = & node $probeScript $kernelDir 2>&1
        $code = $LASTEXITCODE
        $text = ($raw | Out-String).Trim()
        $parsed = $null
        try { $parsed = $text | ConvertFrom-Json } catch { }
        if ($code -eq 0 -and $null -ne $parsed -and $parsed.ok) {
            $g1 = "ok"
            $g1Detail = "@aragon-agent/core $($parsed.version)"
        }
        else {
            $g1 = "missing"
            if ($null -ne $parsed -and $parsed.reason) {
                $g1Detail = "$($parsed.reason) -> template fallback, course will be simplified"
            }
            else {
                $g1Detail = "$text -> template fallback, course will be simplified"
            }
        }
    }
    catch {
        $g1 = "missing"
        $g1Detail = "probe failed: $($_.Exception.Message)"
    }
}
else {
    $g1Detail = "services/agent-kernel or scripts/probe_core.mjs not found"
}
$result.gates.g1 = $g1
$result.detail.g1 = $g1Detail
Write-Step "G1 $g1 :: $g1Detail"

# --------------------------------------------------- Gate G2: PDF (chromium)
Write-Step "G2: probing Chromium for PDF ..."
$g2probe = Invoke-PyProbe "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop(); print('OK')" "OK"
if ($g2probe.ok) {
    $result.gates.g2 = "ok"
    $result.detail.g2 = "chromium launchable via playwright"
    Write-Step "G2 ok :: chromium launchable via playwright"
}
else {
    $result.gates.g2 = "missing"
    $result.detail.g2 = "run: .venv\Scripts\python.exe -m playwright install chromium  (else PDF export falls back to a print view) | $($g2probe.detail)"
    Write-Step "G2 missing :: $($result.detail.g2)"
}

# ------------------------------------------------ Gate G3: syntax analysis
Write-Step "G3: probing tree-sitter-language-pack ..."
$g3probe = Invoke-PyProbe "import tree_sitter_language_pack as p; print('OK')" "OK"
if ($g3probe.ok) {
    $result.gates.g3 = "ok"
    $result.detail.g3 = "tree-sitter-language-pack available"
    Write-Step "G3 ok :: tree-sitter-language-pack available"
}
else {
    $result.gates.g3 = "missing"
    $result.detail.g3 = "run: .venv\Scripts\pip install tree-sitter-language-pack  (else anchors fall back to regex) | $($g3probe.detail)"
    Write-Step "G3 missing :: $($result.detail.g3)"
}

# ------------------------------------------------------------------- persist
$json = $result | ConvertTo-Json -Depth 5
Set-Content -Path (Join-Path $runDir "preflight.json") -Value $json -Encoding UTF8

if ($problems.Count -gt 0) {
    Write-Host ""
    Write-Host "Environment check FAILED:" -ForegroundColor Red
    foreach ($p in $problems) { Write-Host "  - $p" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Fix the items above and run start.ps1 again." -ForegroundColor Yellow
    exit 1
}

if (-not $Quiet) {
    Write-Host "Environment OK: node $($result.node), python $($result.python), pnpm $($result.pnpm)" -ForegroundColor Green
}
exit 0
