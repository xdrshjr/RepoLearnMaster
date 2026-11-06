# Syntax-only check for the PowerShell scripts (PowerShell 5.1 parser).
# Used by CI and by the test suite: a script that parses under 5.1 is a script
# that has a chance of running on a stock Windows box.
#
#   powershell -NoProfile -File scripts/parse_check.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

$files = @("start.ps1", "stop.ps1", "scripts\check_env.ps1", "scripts\parse_check.ps1")
$failed = 0

foreach ($rel in $files) {
    $path = Join-Path $root $rel
    if (-not (Test-Path $path)) {
        Write-Host "MISSING $rel" -ForegroundColor Red
        $failed = $failed + 1
        continue
    }
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    if ($null -ne $errors -and $errors.Count -gt 0) {
        Write-Host "PARSE ERRORS in $rel" -ForegroundColor Red
        foreach ($e in $errors) {
            Write-Host ("  line {0}: {1}" -f $e.Extent.StartLineNumber, $e.Message) -ForegroundColor Red
        }
        $failed = $failed + 1
    }
    else {
        Write-Host "OK $rel"
    }
}

if ($failed -gt 0) {
    Write-Host "$failed script(s) failed to parse" -ForegroundColor Red
    exit 1
}
Write-Host "All PowerShell scripts parse cleanly." -ForegroundColor Green
exit 0
