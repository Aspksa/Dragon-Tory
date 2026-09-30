# Portable Windows startup

Dragon Tory can be started by double-clicking `Start.bat` in the repository root.

## Portable path behavior

The launcher uses `%~dp0`, which always resolves to the folder containing
`Start.bat`. No fixed drive letter is stored.

Examples:

- `D:\Dragon-Tory\Start.bat`
- `E:\AI\Dragon-Tory\Start.bat`
- external SSD or USB drive mounted under another letter

The launcher sets:

- `PYTHONPATH=<current project root>\src`
- `TOORU_DATA_DIR=<current project root>\data`

This keeps source imports and local memory data bound to the current copy of the
project instead of a previously assigned drive letter.

## Startup sequence

1. Resolve the current project root.
2. Detect whether Dragon Tory is already running.
3. Reuse `.venv` when healthy.
4. Otherwise create `.venv` using:
   - optional `runtime\python\python.exe`;
   - Python Launcher 3.12 / 3.11;
   - `python.exe` from PATH;
   - as a last resort, install Python 3.12 through winget.
5. Read runtime dependencies from `pyproject.toml`.
6. Install dependencies only when needed or when `pyproject.toml` changes.
7. Start the FastAPI backend.
8. Wait until `/health` reports ready.
9. Open `http://127.0.0.1:8787/` in the default browser.

## Launcher options

`Start.bat --no-browser`
starts the project without automatically opening the browser.

`Start.bat --check`
validates the portable launcher structure without creating a virtual
environment or starting the server. GitHub Actions runs this mode on Windows.

## First run

The first run may require Internet access to install Python and Python packages.
After the environment is prepared, normal startup can work offline for local
features that do not call external AI providers.
