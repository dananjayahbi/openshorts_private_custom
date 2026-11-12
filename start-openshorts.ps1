# OpenShorts local launcher (Windows + Docker Desktop + NVIDIA GPU).
#
#   .\start-openshorts.ps1          start the stack and open the dashboard
#   .\start-openshorts.ps1 -Stop    stop the stack
#
# Ports (see docker-compose.override.yml):
#   Dashboard  http://localhost:18481
#   API        http://localhost:18480
#   Renderer   http://localhost:18482
param([switch]$Stop)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$dashboard = "http://localhost:18481"

if ($Stop) {
    docker compose stop
    Write-Host "Stopped. Start again with: .\start-openshorts.ps1" -ForegroundColor Yellow
    return
}

# 1. Docker Desktop must be running (the engine, not just the window).
$engineUp = $false
try { docker version --format "{{.Server.Version}}" 2>$null | Out-Null; $engineUp = ($LASTEXITCODE -eq 0) } catch { }

if (-not $engineUp) {
    $exe = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"
    if (-not (Test-Path $exe)) { $exe = "C:\Program Files\Docker\Docker\Docker Desktop.exe" }
    if (Test-Path $exe) {
        Write-Host "Starting Docker Desktop..." -ForegroundColor Cyan
        Start-Process $exe
    }
    Write-Host "Waiting for the Docker engine (up to 3 min)..." -ForegroundColor Cyan
    for ($i = 0; $i -lt 36; $i++) {
        Start-Sleep -Seconds 5
        try { docker version --format "{{.Server.Version}}" 2>$null | Out-Null } catch { }
        if ($LASTEXITCODE -eq 0) { $engineUp = $true; break }
    }
}
if (-not $engineUp) { throw "Docker engine did not start. Open Docker Desktop and retry." }

# 2. Bring the stack up (images are already built; this only starts them).
Write-Host "Starting OpenShorts..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed." }

# 3. Wait for the API to answer, then open the dashboard.
Write-Host "Waiting for the API..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    try {
        $r = Invoke-WebRequest "$dashboard/api/config" -TimeoutSec 3 -UseBasicParsing
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 3
}

if ($ready) {
    Write-Host ""
    Write-Host "  OpenShorts is up:" -ForegroundColor Green
    Write-Host "    Dashboard  $dashboard"
    Write-Host "    API        http://localhost:18480"
    Write-Host ""
    Start-Process $dashboard
} else {
    Write-Host "Stack started but the API is not answering yet. Check: docker compose logs -f backend" -ForegroundColor Yellow
}
