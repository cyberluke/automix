#requires -Version 5.1
<#!
.SYNOPSIS
  Build the TypeScript player/bridge/studio packages (§R).
#>
[CmdletBinding()]
param([string]$Root = "")

$ErrorActionPreference = "Stop"
if (-not $Root) { $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
$packages = @("hypermix-bridge", "hypermix-player", "hypermix-studio")

foreach ($pkg in $packages) {
    $dir = Join-Path $Root "packages\$pkg"
    Write-Host "==> building $pkg" -ForegroundColor Cyan
    Push-Location $dir
    try {
        if (-not (Test-Path "node_modules")) { npm install --silent }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "build failed for $pkg" }
        Write-Host "  [ok] $pkg" -ForegroundColor Green
    } finally {
        Pop-Location
    }
}
Write-Host "All packages built." -ForegroundColor Green
