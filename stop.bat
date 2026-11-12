@echo off
setlocal EnableExtensions
title OpenShorts - stop

rem ---------------------------------------------------------------------------
rem  Stops the three native services started by start.bat.
rem
rem  It kills whatever is listening on the three ports (plus its child
rem  processes, so a running job's ffmpeg dies with the API). Anything you
rem  started by hand on those same ports is stopped too - they are reserved for
rem  this app.
rem ---------------------------------------------------------------------------

set "PORTS=18480 18481 18482"

echo.
echo   stopping OpenShorts ports %PORTS%
echo.

for %%P in (%PORTS%) do (
    for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %%P -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"`) do (
        if not "%%I"=="" (
            echo   port %%P   pid %%I
            taskkill /F /T /PID %%I >nul 2>&1
        )
    )
)

rem A job's encoder can outlive a killed API for a second; give the handles time
rem to close so the next start does not see WinError 32 on its own files.
rem (ping, not timeout: timeout refuses to run when stdin is redirected.)
ping -n 3 127.0.0.1 >nul
echo   done.
endlocal
