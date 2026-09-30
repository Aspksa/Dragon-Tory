@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul 2>&1
title Dragon Tory Launcher

set "ROOT=%~dp0"
set "BOOTSTRAP=%ROOT%scripts\windows\bootstrap.ps1"

if not exist "%BOOTSTRAP%" (
    echo [ERROR] Missing bootstrap script:
    echo %BOOTSTRAP%
    pause
    exit /b 10
)

if /I "%~1"=="--check" goto :CHECK
if /I "%~1"=="--no-browser" goto :NO_BROWSER
goto :NORMAL

:CHECK
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP%" -ProjectRoot "%ROOT%" -Check
goto :DONE

:NO_BROWSER
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP%" -ProjectRoot "%ROOT%" -NoBrowser
goto :DONE

:NORMAL
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP%" -ProjectRoot "%ROOT%"

:DONE
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
    echo.
    echo [ERROR] Dragon Tory startup failed with code %EXITCODE%.
    pause
)
endlocal & exit /b %EXITCODE%
