@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Dragon Tory Launcher

rem ============================================================
rem Dragon Tory portable launcher
rem Uses the folder containing Start.bat as the project root.
rem No fixed drive letter is used.
rem ============================================================

set "ROOT=%~dp0"
cd /d "%ROOT%"
if errorlevel 1 goto :PATH_ERROR

set "HOST=127.0.0.1"
set "PORT=8787"
set "URL=http://%HOST%:%PORT%/"
set "DRAGON_HEALTH=http://%HOST%:%PORT%/health"
set "VENV=%ROOT%.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "DRAGON_PYPROJECT=%ROOT%pyproject.toml"
set "DRAGON_REQ=%VENV%\.dragon_tory_requirements.txt"
set "HASHFILE=%VENV%\.dragon_tory_pyproject.sha256"

rem Keep runtime data and imports bound to the current removable drive path.
set "PYTHONPATH=%ROOT%src"
set "TOORU_DATA_DIR=%ROOT%data"

echo.
echo ===============================================
echo   Dragon Tory - portable startup
echo ===============================================
echo [INFO] Project: %ROOT%

if /I "%~1"=="--check" goto :CHECK_ONLY

rem If Dragon Tory is already running, do not start a second server.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { $h=Invoke-RestMethod -Uri $env:DRAGON_HEALTH -TimeoutSec 1; if ($h.status -eq 'ok') { exit 0 } } catch {}; exit 1" >nul 2>&1
if not errorlevel 1 (
    echo [OK] Dragon Tory is already running.
    goto :OPEN_BROWSER
)

rem Reuse a healthy virtual environment if it already exists.
if exist "%VPY%" (
    "%VPY%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
    if not errorlevel 1 goto :DEPENDENCIES
    echo [WARN] Existing .venv is invalid. Rebuilding it.
    rmdir /s /q "%VENV%" >nul 2>&1
)

:CREATE_VENV
echo [INFO] Preparing Python environment...

rem Optional fully local Python runtime placed beside the project.
if exist "%ROOT%runtime\python\python.exe" (
    "%ROOT%runtime\python\python.exe" -m venv "%VENV%" >nul 2>&1
    if exist "%VPY%" goto :DEPENDENCIES
)

rem Prefer Python Launcher when available.
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
    if not errorlevel 1 (
        py -3.12 -m venv "%VENV%"
        if exist "%VPY%" goto :DEPENDENCIES
    )

    py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
    if not errorlevel 1 (
        py -3.11 -m venv "%VENV%"
        if exist "%VPY%" goto :DEPENDENCIES
    )
)

rem Fall back to python.exe from PATH.
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
    if not errorlevel 1 (
        python -m venv "%VENV%"
        if exist "%VPY%" goto :DEPENDENCIES
    )
)

rem Last resort: automatically install Python 3.12 with winget.
where winget >nul 2>&1
if errorlevel 1 goto :PYTHON_ERROR

echo [INFO] Python 3.11+ was not found. Installing Python 3.12...
winget install --id Python.Python.3.12 -e --silent ^
  --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :PYTHON_ERROR

if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv "%VENV%"
    if exist "%VPY%" goto :DEPENDENCIES
)
if exist "%ProgramFiles%\Python312\python.exe" (
    "%ProgramFiles%\Python312\python.exe" -m venv "%VENV%"
    if exist "%VPY%" goto :DEPENDENCIES
)

rem The Python launcher may become available after installation.
py -3.12 -m venv "%VENV%" >nul 2>&1
if not exist "%VPY%" goto :PYTHON_ERROR

:DEPENDENCIES
echo [OK] Python: %VPY%

set "CURHASH="
for /f "usebackq delims=" %%H in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath $env:DRAGON_PYPROJECT).Hash"`) do set "CURHASH=%%H"

set "OLDHASH="
if exist "%HASHFILE%" set /p OLDHASH=<"%HASHFILE%"

set "NEED_INSTALL=0"
"%VPY%" -c "import fastapi, uvicorn, pydantic_settings" >nul 2>&1
if errorlevel 1 set "NEED_INSTALL=1"
if /I not "!CURHASH!"=="!OLDHASH!" set "NEED_INSTALL=1"

if "!NEED_INSTALL!"=="1" (
    echo [INFO] Installing or updating runtime dependencies...

    "%VPY%" -m pip --version >nul 2>&1
    if errorlevel 1 "%VPY%" -m ensurepip --upgrade
    if errorlevel 1 goto :DEPENDENCY_ERROR

    "%VPY%" -c "import os,tomllib,pathlib; p=pathlib.Path(os.environ['DRAGON_PYPROJECT']); d=tomllib.loads(p.read_text(encoding='utf-8')); pathlib.Path(os.environ['DRAGON_REQ']).write_text('\n'.join(d['project'].get('dependencies', [])), encoding='utf-8')"
    if errorlevel 1 goto :DEPENDENCY_ERROR

    "%VPY%" -m pip install --disable-pip-version-check -r "%DRAGON_REQ%"
    if errorlevel 1 goto :DEPENDENCY_ERROR

    >"%HASHFILE%" echo !CURHASH!
) else (
    echo [OK] Runtime dependencies are ready.
)

echo [INFO] Starting Dragon Tory on %URL%
start "Dragon Tory Server" /D "%ROOT%" "%VPY%" -m tooru.main

echo [INFO] Waiting for the local server...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$u=$env:DRAGON_HEALTH; for($i=0;$i -lt 80;$i++){ try { $h=Invoke-RestMethod -Uri $u -TimeoutSec 1; if($h.status -eq 'ok'){ exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1" >nul 2>&1
if errorlevel 1 goto :SERVER_ERROR

echo [OK] Dragon Tory is ready.

:OPEN_BROWSER
if /I "%~1"=="--no-browser" goto :DONE
echo [INFO] Opening browser: %URL%
start "" "%URL%"
goto :DONE

:CHECK_ONLY
if not exist "%ROOT%pyproject.toml" goto :PATH_ERROR
if not exist "%ROOT%src\tooru\main.py" goto :PATH_ERROR
echo [OK] Portable launcher structure is valid.
echo [OK] Root resolves from %%~dp0: %ROOT%
exit /b 0

:PATH_ERROR
echo.
echo [ERROR] Dragon Tory project files were not found next to Start.bat.
pause
exit /b 10

:PYTHON_ERROR
echo.
echo [ERROR] Python 3.11+ could not be prepared automatically.
echo Install Python 3.12 or place a portable runtime in:
echo   %ROOT%runtime\python\python.exe
pause
exit /b 11

:DEPENDENCY_ERROR
echo.
echo [ERROR] Runtime dependencies could not be installed.
echo The first setup may require an Internet connection.
pause
exit /b 12

:SERVER_ERROR
echo.
echo [ERROR] Dragon Tory did not become ready on %DRAGON_HEALTH%.
echo Check the "Dragon Tory Server" window for the error.
pause
exit /b 13

:DONE
echo [OK] Startup complete.
endlocal
exit /b 0
