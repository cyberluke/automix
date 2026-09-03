#requires -Version 5.1
<#!
.SYNOPSIS
  Assemble the HyperMix integration bundle for Kelvin / Zoo Code (§R).
.DESCRIPTION
  Produces dist/integration-bundle/ containing the built player + bridge,
  JSON schemas, the sidecar binary, docs, and a manifest.json.
#>
[CmdletBinding()]
param(
    [string]$Root = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
if (-not $Root) { $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
Set-Location $Root

if (-not $SkipBuild) {
    & (Join-Path $Root "tools\build-player.ps1")
    & (Join-Path $Root "tools\build-sidecar-windows.ps1")
}

$bundle = Join-Path $Root "dist\integration-bundle"
if (Test-Path $bundle) { Remove-Item -Recurse -Force $bundle }
New-Item -ItemType Directory -Force -Path $bundle | Out-Null

Write-Host "==> Assembling integration bundle" -ForegroundColor Cyan

# Player + bridge dists.
foreach ($pkg in @("hypermix-player", "hypermix-bridge")) {
    $src = Join-Path $Root "packages\$pkg\dist"
    $dst = Join-Path $bundle "packages\$pkg"
    if (Test-Path $src) {
        Copy-Item -Recurse -Force $src $dst
        Write-Host "  [ok] $pkg" -ForegroundColor Green
    } else {
        Write-Warning "  missing dist for $pkg (run build-player.ps1)"
    }
}

# Schemas.
$contracts = Join-Path $Root "contracts"
Copy-Item -Recurse -Force $contracts (Join-Path $bundle "schemas")
Write-Host "  [ok] schemas" -ForegroundColor Green

# Sidecar.
$sidecar = Join-Path $Root "dist\sidecar"
if (Test-Path $sidecar) {
    Copy-Item -Recurse -Force $sidecar (Join-Path $bundle "sidecar")
    Write-Host "  [ok] sidecar" -ForegroundColor Green
} else {
    Write-Warning "  no sidecar build found"
}

# Docs.
$docsOut = Join-Path $bundle "docs"
New-Item -ItemType Directory -Force -Path $docsOut | Out-Null
Get-ChildItem (Join-Path $Root "docs\HYPERMIX_*.md") -ErrorAction SilentlyContinue |
    Copy-Item -Destination $docsOut
Write-Host "  [ok] docs" -ForegroundColor Green

# Manifest.
$manifest = [ordered]@{
    name      = "hypermix-integration-bundle"
    version   = "0.1.0"
    builtAt   = (Get-Date).ToUniversalTime().ToString("o")
    protocol  = "hypermix.webview.v1"
    packages  = @("hypermix-player", "hypermix-bridge")
    sidecar   = "sidecar/win32-x64"
    schemas   = (Get-ChildItem $contracts -Filter *.json | ForEach-Object { $_.Name })
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $bundle "manifest.json") -Encoding UTF8

Write-Host "Integration bundle -> $bundle" -ForegroundColor Green
