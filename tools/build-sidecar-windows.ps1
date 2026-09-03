#requires -Version 5.1
<#!
.SYNOPSIS
  Build the Windows sidecar executable via Nuitka (§K).
.DESCRIPTION
  Produces dist/sidecar/win32-x64/hypermixd.exe plus BUILD_INFO.json.
  Nuitka is optional; falls back to a portable python -m launcher if absent.
#>
[CmdletBinding()]
param(
    [string]$Root = "",
    [string]$VenvPython = ""
)

$ErrorActionPreference = "Stop"
if (-not $Root) { $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
if (-not $VenvPython) { $VenvPython = Join-Path $Root ".venv-hypermix\Scripts\python.exe" }
Set-Location $Root

$outDir = Join-Path $Root "dist\sidecar\win32-x64"
# Clean stale Nuitka artifacts (interrupted builds leave __main__.build/*.c which crash subsequent runs).
if (Test-Path $outDir) { Remove-Item $outDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# Check for Nuitka.
& $VenvPython -c "import nuitka" 2>$null
$hasNuitka = ($LASTEXITCODE -eq 0)

$buildInfo = [ordered]@{
    builtAt   = (Get-Date).ToUniversalTime().ToString("o")
    root      = $Root
    python    = (& $VenvPython --version 2>&1)
    method    = $null
    output    = $null
}

if ($hasNuitka) {
    Write-Host "==> Building hypermixd.exe with Nuitka (standalone folder)" -ForegroundColor Cyan
    $sidecarMain = Join-Path $Root "src\hypermix\sidecar\entry.py"
    & $VenvPython -m nuitka `
        --standalone `
        --output-dir=$outDir `
        --output-filename=hypermixd.exe `
        --assume-yes-for-downloads `
        --noinclude-numba-mode=nofollow `
        --include-package=src.hypermix `
        --include-package=src.hypermix.sidecar `
        --include-package=src.hypermix.compiler `
        --include-package=src.hypermix.transitions `
        --include-package=src.hypermix.analysis `
        --include-package=src.hypermix.cues `
        --include-package=src.hypermix.director `
        $sidecarMain
    if ($LASTEXITCODE -ne 0) { throw "Nuitka build failed" }
    # Nuitka names the folder after the entry module (__main__.dist); normalize layout.
    $distDir = Get-ChildItem -Path $outDir -Directory -Filter "*.dist" | Select-Object -First 1
    if ($distDir) {
        Get-ChildItem -Path $distDir.FullName | Move-Item -Destination $outDir -Force
        Remove-Item $distDir.FullName -Recurse -Force
    }
    $buildDir = Get-ChildItem -Path $outDir -Directory -Filter "*.build" | Select-Object -First 1
    if ($buildDir) { Remove-Item $buildDir.FullName -Recurse -Force }
    $buildInfo.method = "nuitka"
    $buildInfo.output = (Join-Path $outDir "hypermixd.exe")
    Write-Host "  [ok] hypermixd.exe" -ForegroundColor Green
} else {
    Write-Warning "Nuitka not installed; writing a portable launcher instead."
    $launcher = Join-Path $outDir "hypermixd.cmd"
    @"
@echo off
"%~dp0..\..\.venv-hypermix\Scripts\python.exe" -m src.hypermix.sidecar %*
"@ | Set-Content -Path $launcher -Encoding ASCII
    $buildInfo.method = "launcher"
    $buildInfo.output = $launcher
    Write-Host "  [ok] launcher hypermixd.cmd" -ForegroundColor Green
}

$buildInfo | ConvertTo-Json | Set-Content -Path (Join-Path $outDir "BUILD_INFO.json") -Encoding UTF8
Write-Host "Sidecar build complete -> $outDir" -ForegroundColor Green
