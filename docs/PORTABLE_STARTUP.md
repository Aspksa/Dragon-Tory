# Portable Windows startup

Dragon Tory starts by double-clicking `Start.bat` in the repository root.

## Russian Windows and Unicode paths

The launcher is split into two layers:

- `Start.bat` — a small Windows entry point;
- `scripts/windows/bootstrap.ps1` — Unicode-safe setup and startup logic.

The batch file switches the console to UTF-8 and does not use delayed variable
expansion. The PowerShell bootstrap uses `-LiteralPath` for project paths.

This is designed for paths containing Cyrillic and spaces, for example:

- `D:\Дракончик Тоору\Dragon-Tory\Start.bat`
- `E:\Мои проекты\Дракончик Тоору\Start.bat`

GitHub Actions additionally copies the repository into a Cyrillic path and
runs `Start.bat --check` after switching CMD to OEM code page 866.

## Portable drive behavior

The launcher uses `%~dp0`, so it always resolves the folder containing
`Start.bat`. No fixed drive letter is stored.

The bootstrap sets:

- `PYTHONPATH=<current project root>\src`
- `TOORU_DATA_DIR=<current project root>\data`

If an old `.venv` stops working after the external SSD changes drive letter
or moves to another computer, it is removed and rebuilt automatically.

## Automatic Python setup

Dragon Tory requires Python 3.11 or newer.

Startup checks in this order:

1. a project-local runtime in `runtime\python\python.exe`;
2. Python Launcher 3.12 / 3.11;
3. `python.exe` from PATH;
4. if none are usable, download the official Python 3.12.10 Windows installer
   directly from `https://www.python.org/ftp/python/`.

The fallback installation is local to the project:

`runtime\python\`

It uses `InstallAllUsers=0`, does not change PATH, does not create shortcuts,
and does not require an administrator installation target.

Before installation, the bootstrap checks:

- installer file size;
- Windows Authenticode signature status;
- signer contains `Python Software Foundation`.

The downloaded installer is cached in:

`runtime\downloads\`

Both `runtime/` and `logs/` are ignored by Git.

Python 3.12.10 is intentionally pinned because it is the last Python 3.12
release that provides the traditional Windows binary installer.

## Automatic libraries

Runtime dependencies are read directly from the `[project].dependencies`
section of `pyproject.toml`.

On first setup, or when `pyproject.toml` changes, the launcher:

1. creates/rebuilds `.venv`;
2. ensures pip exists;
3. installs Dragon Tory in editable mode directly from `pyproject.toml`;
4. installs all required runtime libraries declared by the project;
5. runs `pip check`;
6. imports the critical runtime modules as a final validation;
7. saves the SHA-256 hash of `pyproject.toml`.

If dependencies are already healthy and the hash has not changed, startup skips
the install step.

## Startup sequence

1. Validate project structure.
2. Resolve the current removable-drive path.
3. Check whether Dragon Tory is already running.
4. Validate or rebuild `.venv`.
5. Find Python or download/install the local Python runtime.
6. Validate/install Python libraries.
7. Create the local data directory.
8. Start the FastAPI backend.
9. Poll `/health` until the server is ready.
10. Open `http://127.0.0.1:8787/` in the default browser.

Launcher activity and errors are written to:

`logs\launcher.log`

## Launcher options

`Start.bat`

Normal startup and automatic browser opening.

`Start.bat --no-browser`

Start without opening the browser.

`Start.bat --check`

Validate the launcher and Unicode project layout without downloading Python,
installing libraries, or starting the server.

## First-run Internet requirement

If Python or required libraries are missing, the first setup requires Internet
access. Once the local environment is prepared, local Dragon Tory features can
start offline. External DeepSeek or web features still require Internet.
