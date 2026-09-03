#requires -Version 5.1
<#!
.SYNOPSIS
  Bootstrap the HyperMix compiler environment on Windows (§K).
.DESCRIPTION
  Detects Python, creates .venv-hypermix, installs requirements-hypermix.txt,
  verifies FFmpeg, and prints a diagnostics summary. Idempotent.
#>
[CmdletBinding()]
param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$VenvName = ".venv-hypermix"
)

$ErrorActionPreference = "Stop"
Set-Location $Root

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [ok] $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "  [warn] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  [fail] $msg" -ForegroundColor Red }

$report = [ordered]@{ python = $null; venv = $null; ffmpeg = $null; deps = $null }

# --- 1. Python detection ----------------------------------------------------
Write-Step "Detecting Python"
$python = $null
foreach ($cmd in @("python", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0) { $python = $cmd; $report.python = "$ver ($cmd)"; break }
    } catch { }
}
if (-not $python) { Write-Fail "Python 3.11+ not found on PATH"; exit 1 }
Write-Ok $report.python

# --- 2. Venv ----------------------------------------------------------------
Write-Step "Creating virtual environment $VenvName"
$venvPath = Join-Path $Root $VenvName
$venvPython = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $python -m venv $venvPath
    Write-Ok "created $VenvName"
} else {
    Write-Ok "already exists"
}
$report.venv = $venvPath

# --- 3. Dependencies --------------------------------------------------------
Write-Step "Installing requirements-hypermix.txt"
& $venvPython -m pip install --upgrade pip | Out-Null
& $venvPython -m pip install -r (Join-Path $Root "requirements-hypermix.txt")
if ($LASTEXITCODE -ne 0) { Write-Fail "dependency install failed"; exit 1 }
$report.deps = "installed"
Write-Ok "dependencies installed"

# --- 4. FFmpeg --------------------------------------------------------------
Write-Step "Verifying FFmpeg"
try {
    $ff = (ffmpeg -version 2>&1 | Select-Object -First 1)
    $report.ffmpeg = $ff
    Write-Ok $ff
} catch {
    Write-Warn2 "ffmpeg not on PATH; canonicalization will fail"
    $report.ffmpeg = "missing"
}

# --- 5. Import smoke test ---------------------------------------------------
Write-Step "Smoke test: import src.hypermix"
& $venvPython -c "import src.hypermix; print('hypermix', src.hypermix.__name__)"
if ($LASTEXITCODE -ne 0) { Write-Fail "import failed"; exit 1 }

Write-Host ""
Write-Host "Bootstrap complete." -ForegroundColor Green
$report.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-8} {1}" -f $_.Key, $_.Value) }
