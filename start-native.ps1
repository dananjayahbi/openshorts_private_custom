# Native Windows launcher — the no-Docker path.
#
#   .\start-native.ps1            start backend + renderer + dashboard
#   .\start-native.ps1 -Stop      stop whatever is listening on the three ports
#   .\start-native.ps1 -Restart   stop, then start
#
# Everything runs from the repo root: app.py launches main.py with
# cwd=os.getcwd(), so the working directory is part of the contract.

param(
    [switch]$Stop,
    [switch]$Restart,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = if ($env:OPENSHORTS_VENV) { $env:OPENSHORTS_VENV } else { 'F:\openshorts-venv' }
$python = Join-Path $venv 'Scripts\python.exe'

$apiPort = 18480
$uiPort = 18481
$renderPort = 18482

function Get-PortPid([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($conn) { return $conn.OwningProcess }
    return $null
}

function Stop-Stack {
    foreach ($port in @($apiPort, $uiPort, $renderPort)) {
        $procId = Get-PortPid $port
        if ($procId) {
            Write-Host "  stopping :$port (pid $procId)" -ForegroundColor DarkGray
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
    # main.py children (ffmpeg/whisper) of a killed backend would linger.
    Get-Process -Name 'ffmpeg' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -like '*ffmpeg*' } |
        ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
}

if ($Stop -or $Restart) {
    Write-Host "stopping openshorts (native)" -ForegroundColor Cyan
    Stop-Stack
    if ($Stop) { return }
    Start-Sleep -Seconds 1
}

if (-not (Test-Path $python)) {
    throw "Python venv not found at $venv. Run .\setup-native.ps1 first (or set OPENSHORTS_VENV)."
}
foreach ($port in @($apiPort, $uiPort, $renderPort)) {
    if (Get-PortPid $port) { throw "Port $port is already in use. Run .\start-native.ps1 -Restart." }
}

$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# --- environment -----------------------------------------------------------
$env:HF_HOME = Join-Path $root '.cache\huggingface'
$env:HF_HUB_DISABLE_XET = '1'
$env:PYTORCH_CUDA_ALLOC_CONF = 'expandable_segments:True'
$env:TRANSNETV2_DEVICE = 'cuda'
$env:PUBLIC_API_URL = "http://localhost:$apiPort"
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:FONTCONFIG_FILE = Join-Path $root 'fonts\fonts.local.conf'

$env:PORT = "$renderPort"
$env:REMOTION_BUNDLE_PATH = Join-Path $root 'remotion'
$env:OUTPUT_DIR = Join-Path $root 'output'

$env:VITE_PROXY_TARGET = "http://localhost:$apiPort"
$env:VITE_RENDER_TARGET = "http://localhost:$renderPort"

# --- backend ---------------------------------------------------------------
Write-Host "starting api       :$apiPort" -ForegroundColor Cyan
Start-Process -FilePath $python `
    -ArgumentList @('-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', "$apiPort", '--log-level', 'info') `
    -WorkingDirectory $root `
    -RedirectStandardOutput (Join-Path $logDir 'api.log') `
    -RedirectStandardError (Join-Path $logDir 'api.err.log') `
    -WindowStyle Hidden | Out-Null

# --- renderer (Remotion) ---------------------------------------------------
Write-Host "starting renderer  :$renderPort" -ForegroundColor Cyan
Start-Process -FilePath 'cmd.exe' `
    -ArgumentList @('/c', 'npm', 'start') `
    -WorkingDirectory (Join-Path $root 'render-service') `
    -RedirectStandardOutput (Join-Path $logDir 'renderer.log') `
    -RedirectStandardError (Join-Path $logDir 'renderer.err.log') `
    -WindowStyle Hidden | Out-Null

# --- dashboard (Vite) ------------------------------------------------------
Write-Host "starting dashboard :$uiPort" -ForegroundColor Cyan
Start-Process -FilePath 'cmd.exe' `
    -ArgumentList @('/c', 'npm', 'run', 'dev', '--', '--port', "$uiPort", '--strictPort') `
    -WorkingDirectory (Join-Path $root 'dashboard') `
    -RedirectStandardOutput (Join-Path $logDir 'dashboard.log') `
    -RedirectStandardError (Join-Path $logDir 'dashboard.err.log') `
    -WindowStyle Hidden | Out-Null

# --- wait for readiness ----------------------------------------------------
$deadline = (Get-Date).AddSeconds(120)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:$apiPort/health/ready" -TimeoutSec 2
        if ($health.status -eq 'ready') { $ready = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 800
}

if (-not $ready) {
    Write-Host "api did not become ready in 120s - see logs\api.err.log" -ForegroundColor Red
    Get-Content (Join-Path $logDir 'api.err.log') -Tail 25 -ErrorAction SilentlyContinue
    return
}

Write-Host ""
Write-Host "openshorts is up" -ForegroundColor Green
Write-Host "  dashboard  http://localhost:$uiPort"
Write-Host "  api        http://localhost:$apiPort/docs"
Write-Host "  renderer   http://localhost:$renderPort"
Write-Host "  logs       $logDir"
Write-Host ""
if (-not $NoBrowser) { Start-Process "http://localhost:$uiPort" }
