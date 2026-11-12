# One-time native Windows setup (no Docker).
#
#   .\setup-native.ps1
#
# Installs into F:\openshorts-venv by default (override with OPENSHORTS_VENV)
# so the repo drive keeps its free space for rendered clips. Safe to re-run:
# pip/npm skip what is already installed.
#
# Downloads on a cold machine: ~3-4 GB of Python wheels (torch + CUDA), then
# ~500 MB of npm packages for the renderer and the dashboard.

param(
    [string]$Venv = $(if ($env:OPENSHORTS_VENV) { $env:OPENSHORTS_VENV } else { 'F:\openshorts-venv' })
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $Venv 'Scripts\python.exe'
$cache = if ($env:PIP_CACHE_DIR) { $env:PIP_CACHE_DIR } else { 'F:\pip-cache' }

Write-Host "== 1/6 python venv ($Venv)" -ForegroundColor Cyan
if (-not (Test-Path $python)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "Python launcher 'py' not found." }
    py -3.12 -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed. Python 3.12 is required (mediapipe has no 3.13+ wheel)." }
}
& $python -m pip install --quiet --upgrade pip

Write-Host "== 2/6 torch (cu128 wheel - runs on the current driver)" -ForegroundColor Cyan
$env:PIP_CACHE_DIR = $cache
& $python -m pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw "torch install failed." }

Write-Host "== 3/6 pipeline requirements" -ForegroundColor Cyan
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "requirements install failed." }

Write-Host "== 4/6 renderer + dashboard packages" -ForegroundColor Cyan
Push-Location (Join-Path $root 'render-service')
npm ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "render-service npm ci failed." }
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "render-service build failed." }
Pop-Location

Push-Location (Join-Path $root 'remotion')
npm ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "remotion npm ci failed." }
Pop-Location

Push-Location (Join-Path $root 'dashboard')
if (-not (Test-Path 'node_modules')) { npm ci --no-audit --no-fund }
Pop-Location

Write-Host "== 5/6 fonts (per-user + explicit fontconfig map)" -ForegroundColor Cyan
$fontDir = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Fonts'
$fontKey = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts'
New-Item -ItemType Directory -Force -Path $fontDir | Out-Null
foreach ($file in @('Anton-Regular.ttf', 'Montserrat-ExtraBold.ttf', 'NotoSerif-Bold.ttf')) {
    $src = Join-Path $root "fonts\$file"
    if (-not (Test-Path $src)) { continue }
    $dst = Join-Path $fontDir $file
    Copy-Item $src $dst -Force
    $label = [System.IO.Path]::GetFileNameWithoutExtension($file) -replace '-', ' '
    New-ItemProperty -Path $fontKey -Name "$label (TrueType)" -Value $dst -PropertyType String -Force | Out-Null
}

# libass finds fonts through fontconfig, which does not always see per-user
# installs on Windows. Point it at the repo's fonts explicitly, with the same
# name aliases the image uses, so burned captions match the in-browser preview.
$confPath = Join-Path $root 'fonts\fonts.local.conf'
$conf = @"
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>$($root -replace '\\','/')/fonts</dir>
  <dir>C:/Windows/Fonts</dir>
  <alias binding="strong"><family>Verdana</family><prefer><family>Arial</family></prefer></alias>
  <alias binding="strong"><family>Helvetica</family><prefer><family>Arial</family></prefer></alias>
  <alias binding="strong"><family>Georgia</family><prefer><family>Times New Roman</family></prefer></alias>
  <alias binding="strong"><family>Impact</family><prefer><family>Anton</family></prefer></alias>
</fontconfig>
"@
Set-Content -Path $confPath -Value $conf -Encoding UTF8
Write-Host "   installed: Anton, Montserrat ExtraBold, Noto Serif"
Write-Host "   fontconfig: $confPath"

Write-Host "== 6/6 verify" -ForegroundColor Cyan
& $python -c "import torch, sys; print('python', sys.version.split()[0]); print('torch', torch.__version__, 'cuda', torch.version.cuda); print('cuda available', torch.cuda.is_available()); print('device', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'); print('sm', torch.cuda.get_device_capability(0) if torch.cuda.is_available() else '-')"
Write-Host ""
Write-Host "done. start it with .\start-native.ps1" -ForegroundColor Green
