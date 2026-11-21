@echo off
setlocal EnableExtensions
title OpenShorts
cd /d "%~dp0"

rem ---------------------------------------------------------------------------
rem  OpenShorts - native launcher (no Docker)
rem
rem  Opens one CMD window per service so each one keeps streaming its own log:
rem    * API       uvicorn app:app          http://127.0.0.1:18480
rem    * Renderer  Remotion render service  http://127.0.0.1:18482
rem    * Dashboard Vite dev server          http://127.0.0.1:18481
rem
rem  Everything is written under Storage\ (storage.py): videos, thumbnails and
rem  uploads. Set OPENSHORTS_STORAGE before running this file to move the tree.
rem  A one-time install is required first:  setup-native.ps1
rem ---------------------------------------------------------------------------

set "API_PORT=18480"
set "UI_PORT=18481"
set "RENDER_PORT=18482"

if "%OPENSHORTS_VENV%"=="" set "OPENSHORTS_VENV=F:\openshorts-venv"
set "PYTHON=%OPENSHORTS_VENV%\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [ERROR] Python venv not found at %OPENSHORTS_VENV%
    echo         Run setup-native.ps1 once, or set OPENSHORTS_VENV to your venv.
    pause
    exit /b 1
)
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js is not on PATH. Install it, then run setup-native.ps1.
    pause
    exit /b 1
)
if not exist "dashboard\node_modules" (
    echo [ERROR] dashboard\node_modules is missing.
    echo         Run setup-native.ps1 once to install the frontend packages.
    pause
    exit /b 1
)
if not exist "render-service\node_modules" (
    echo [ERROR] render-service\node_modules is missing.
    echo         Run setup-native.ps1 once to install the renderer packages.
    pause
    exit /b 1
)
if not exist "fonts\fonts.local.conf" (
    echo [WARN] fonts\fonts.local.conf is missing; captions may use a fallback font.
    echo        Run setup-native.ps1 to generate it.
)

rem --- storage roots ------------------------------------------------------------
rem  State (settings, profiles, gallery flags, Thumbnail Studio) stays next to
rem  the app. Big media (renders, sources, Collector, archive) goes to the
rem  external drive; if it is unplugged the API still starts and the dashboard
rem  says so, and replugging it needs no restart.
if "%OPENSHORTS_STORAGE%"=="" set "OPENSHORTS_STORAGE=%CD%\Storage"
if "%OPENSHORTS_MEDIA%"==""   set "OPENSHORTS_MEDIA=D:\OpenShorts\Storage"
if not exist "%OPENSHORTS_STORAGE%\thumbnails" mkdir "%OPENSHORTS_STORAGE%\thumbnails"
if not exist "%OPENSHORTS_MEDIA%" mkdir "%OPENSHORTS_MEDIA%" 2>nul
if exist "%OPENSHORTS_MEDIA%" (
    if not exist "%OPENSHORTS_MEDIA%\videos"    mkdir "%OPENSHORTS_MEDIA%\videos"
    if not exist "%OPENSHORTS_MEDIA%\uploads"   mkdir "%OPENSHORTS_MEDIA%\uploads"
    if not exist "%OPENSHORTS_MEDIA%\collector" mkdir "%OPENSHORTS_MEDIA%\collector"
    if not exist "%OPENSHORTS_MEDIA%\archive"   mkdir "%OPENSHORTS_MEDIA%\archive"
) else (
    echo [WARN] Media drive not connected: %OPENSHORTS_MEDIA%
    echo        The dashboard will start; plug the drive in before rendering.
)

rem --- environment inherited by every window ---------------------------------
set "HF_HOME=%CD%\.cache\huggingface"
set "HF_HUB_DISABLE_XET=1"
set "PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True"
set "TRANSNETV2_DEVICE=cuda"
set "PUBLIC_API_URL=http://127.0.0.1:%API_PORT%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "FONTCONFIG_FILE=%CD%\fonts\fonts.local.conf"
set "PORT=%RENDER_PORT%"
set "REMOTION_BUNDLE_PATH=%CD%\remotion"
set "OUTPUT_DIR=%OPENSHORTS_MEDIA%\videos"
set "VITE_PROXY_TARGET=http://127.0.0.1:%API_PORT%"
set "VITE_RENDER_TARGET=http://127.0.0.1:%RENDER_PORT%"

echo.
echo   OpenShorts
echo   ----------
echo   API        http://127.0.0.1:%API_PORT%/docs
echo   Dashboard  http://127.0.0.1:%UI_PORT%
echo   Renderer   http://127.0.0.1:%RENDER_PORT%
echo   Storage    %OPENSHORTS_STORAGE%
echo.
echo   Three windows will open. Close them (or run stop.bat) to stop.
echo.

start "OpenShorts API" cmd /k ""%PYTHON%" -m uvicorn app:app --host 127.0.0.1 --port %API_PORT% --log-level info"
start "OpenShorts Renderer" cmd /k "cd /d "%~dp0render-service" && npm start"
rem Bind Vite to IPv4 explicitly: with host "localhost", Node may bind only
rem ::1, and on Windows hosts where the IPv6 loopback is unavailable the
rem dashboard window starts but the browser cannot reach it at all.
start "OpenShorts Dashboard" cmd /k "cd /d "%~dp0dashboard" && npm run dev -- --host 127.0.0.1 --port %UI_PORT% --strictPort"

rem Give Vite a moment, then open the UI. The API takes longer and the
rem dashboard polls it, so waiting for the API here would only delay the tab.
rem (ping, not timeout: timeout refuses to run when stdin is redirected.)
ping -n 5 127.0.0.1 >nul
start "" "http://127.0.0.1:%UI_PORT%"

endlocal
