# Remove the container stack and give the disk space back.
#
#   .\remove-docker-stack.ps1                 # drop images/volumes/cache, then compact
#   .\remove-docker-stack.ps1 -KeepImages     # only compact (keep the images)
#   .\remove-docker-stack.ps1 -WhatIf         # show what would be removed, change nothing
#
# Docker Desktop keeps everything inside one virtual disk
# (%LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx). `docker system prune`
# frees space INSIDE that file; Windows does not shrink it, so the VHDX keeps
# its high-water mark (42 GB on this machine) until it is compacted. That is
# the step this script exists for, and it needs an elevated shell.
#
# Run it only after the native stack works: `.\start-native.ps1` must be able
# to process a video before the fallback goes away.

param(
    [switch]$KeepImages,
    [switch]$WhatIf,
    [switch]$CompactOnly
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$vhdx = Join-Path $env:LOCALAPPDATA 'Docker\wsl\disk\docker_data.vhdx'
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
# The elevated window closes when this finishes; the transcript is the only
# record of what it did.
try { Start-Transcript -Path (Join-Path $logDir 'docker-compact.log') -Force | Out-Null } catch { }

function Get-SizeGB($path) {
    if (Test-Path $path) { return [math]::Round((Get-Item $path).Length / 1GB, 2) }
    return 0
}

$before = Get-SizeGB $vhdx
Write-Host "docker data disk: $before GB ($vhdx)" -ForegroundColor Cyan

if ($WhatIf) {
    Write-Host "would: docker compose down"
    if (-not $KeepImages) { Write-Host "would: docker system prune -a --volumes -f" }
    Write-Host "would: wsl --shutdown"
    Write-Host "would: compact $vhdx"
    return
}

# 1. stop this project's containers. Skipped when the engine is down: `docker
#    compose down` then tries to start the VM and blocks for minutes.
$dockerUp = $false
try {
    $null = docker version --format '{{.Server.Version}}' 2>$null
    $dockerUp = ($LASTEXITCODE -eq 0)
} catch { }
if ($dockerUp -and -not $CompactOnly) {
    Push-Location $root
    try {
        docker compose down --remove-orphans 2>$null | Out-Null
    } catch { }
    Pop-Location

    # 2. free the space inside the virtual disk
    if (-not $KeepImages) {
        Write-Host "pruning images, volumes and build cache (this can take a minute)" -ForegroundColor Cyan
        docker system prune -a --volumes -f | Out-Null
    }
    docker system df
} else {
    Write-Host "docker engine not running - skipping container cleanup" -ForegroundColor DarkGray
}

# 3. the disk must be detached before it can be compacted
Write-Host "stopping the WSL/Docker VM" -ForegroundColor Cyan
wsl --shutdown 2>$null | Out-Null
Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 4

if (-not (Test-Path $vhdx)) {
    Write-Host "no docker_data.vhdx - nothing to compact" -ForegroundColor Yellow
    return
}

# 4. compact. Optimize-VHD (Hyper-V module) is the clean way; diskpart is the
#    fallback when Hyper-V is not installed. Both need elevation.
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host ""
    Write-Host "Compaction needs an elevated shell." -ForegroundColor Yellow
    Write-Host "Re-run this script from 'PowerShell (Admin)':" -ForegroundColor Yellow
    Write-Host "  .\remove-docker-stack.ps1 -KeepImages   # images already pruned" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Space freed inside the VHDX so far is not visible to Windows yet; the file is still $before GB." -ForegroundColor Yellow
    return
}

$compacted = $false
if (Get-Command Optimize-VHD -ErrorAction SilentlyContinue) {
    try {
        Write-Host "Optimize-VHD -Mode Full" -ForegroundColor Cyan
        Optimize-VHD -Path $vhdx -Mode Full
        $compacted = $true
    } catch {
        Write-Host "Optimize-VHD failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

if (-not $compacted) {
    Write-Host "diskpart compact vdisk" -ForegroundColor Cyan
    $script = @"
select vdisk file="$vhdx"
attach vdisk readonly
compact vdisk
detach vdisk
exit
"@
    $tmp = Join-Path $env:TEMP 'openshorts-compact.txt'
    Set-Content -Path $tmp -Value $script -Encoding ASCII
    diskpart /s $tmp | Out-String | Write-Host
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}

$after = Get-SizeGB $vhdx
Write-Host ""
Write-Host "docker data disk: $before GB -> $after GB (reclaimed $([math]::Round($before - $after, 2)) GB)" -ForegroundColor Green
Write-Host "If Docker is no longer needed, uninstall Docker Desktop from Settings > Apps to reclaim the rest." -ForegroundColor DarkGray
try { Stop-Transcript | Out-Null } catch { }
