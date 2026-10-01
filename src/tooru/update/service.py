import base64
import json
import os
import platform
import re
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar


class UpdateError(RuntimeError):
    pass


class UpdateService:
    """Checks GitHub and starts the detached Windows self-updater."""

    RUNNING_PHASES: ClassVar[set[str]] = {
        "starting",
        "checking",
        "downloading",
        "backing_up",
        "stopping",
        "installing",
        "restarting",
        "verifying",
        "rolling_back",
    }

    def __init__(
        self,
        *,
        project_root: Path,
        local_version: str,
        repository: str,
        branch: str,
    ) -> None:
        self.project_root = project_root.resolve()
        self.local_version = local_version
        self.repository = repository
        self.branch = branch
        self.state_path = self.project_root / "data" / "update" / "state.json"
        self.updater_script = (
            self.project_root / "scripts" / "windows" / "update.ps1"
        )

    def status(self) -> dict[str, Any]:
        state = self._read_state()
        state.setdefault("phase", "idle")
        state.setdefault("message", "Готово к проверке обновлений.")
        state.setdefault("local_version", self.local_version)
        state.setdefault("remote_version", None)
        state.setdefault("remote_sha", None)
        state.setdefault("installed_sha", self._installed_sha())
        state.setdefault("update_available", False)
        state.setdefault("last_checked_at", None)
        state.setdefault("last_updated_at", None)
        state.setdefault("backup_path", None)
        state.setdefault("error", None)
        state["repository"] = self.repository
        state["branch"] = self.branch
        state["running"] = state.get("phase") in self.RUNNING_PHASES
        return state

    def check(self) -> dict[str, Any]:
        current = self.status()
        if current["running"]:
            return current

        self._write_state(
            {
                **current,
                "phase": "checking",
                "message": "Проверка GitHub…",
                "error": None,
            }
        )

        try:
            remote = self._remote_info()
            installed_sha = self._installed_sha()
            if installed_sha:
                available = installed_sha.lower() != remote["sha"].lower()
                tracking = "commit"
            else:
                available = self._version_tuple(remote["version"]) > self._version_tuple(
                    self.local_version
                )
                tracking = "version"

            state = {
                **self.status(),
                "phase": "available" if available else "current",
                "message": (
                    "Доступно обновление."
                    if available
                    else "Установлена актуальная версия."
                ),
                "local_version": self.local_version,
                "remote_version": remote["version"],
                "remote_sha": remote["sha"],
                "installed_sha": installed_sha,
                "update_available": available,
                "tracking": tracking,
                "last_checked_at": self._now(),
                "error": None,
            }
            self._write_state(state)
            return self.status()
        except Exception as exc:
            state = {
                **self.status(),
                "phase": "error",
                "message": "Не удалось проверить обновления.",
                "error": f"{type(exc).__name__}: {exc}",
                "last_checked_at": self._now(),
            }
            self._write_state(state)
            raise UpdateError(state["error"]) from exc

    def start_install(self, *, force: bool = False) -> dict[str, Any]:
        if platform.system() != "Windows":
            raise UpdateError("Автоматическая установка обновлений поддерживается на Windows.")

        current = self.status()
        if current["running"]:
            raise UpdateError("Обновление уже выполняется.")

        checked = self.check()
        if not checked["update_available"] and not force:
            raise UpdateError("Новых обновлений нет.")

        if not self.updater_script.is_file():
            raise UpdateError(f"Не найден updater: {self.updater_script}")

        state = {
            **checked,
            "phase": "starting",
            "message": "Запуск автоматического обновления…",
            "error": None,
        }
        self._write_state(state)

        args = [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.updater_script),
            "-ProjectRoot",
            str(self.project_root),
            "-Repository",
            self.repository,
            "-Branch",
            self.branch,
            "-ServerPid",
            str(os.getpid()),
        ]
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(
                args,
                cwd=self.project_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
        except OSError as exc:
            self._write_state(
                {
                    **state,
                    "phase": "error",
                    "message": "Не удалось запустить updater.",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            raise UpdateError(str(exc)) from exc

        self._write_state(
            {
                **state,
                "updater_pid": process.pid,
                "message": "Updater запущен. Идёт подготовка обновления…",
            }
        )
        return self.status()

    def _remote_info(self) -> dict[str, str]:
        repo_api = f"https://api.github.com/repos/{self.repository}"
        commit = self._get_json(f"{repo_api}/commits/{self.branch}")
        contents = self._get_json(
            f"{repo_api}/contents/pyproject.toml?ref={self.branch}"
        )
        encoded = contents.get("content")
        if not encoded:
            raise UpdateError("GitHub не вернул pyproject.toml.")

        pyproject = base64.b64decode(encoded).decode("utf-8")
        match = re.search(
            r'(?ms)^\[project\].*?^version\s*=\s*"([^"]+)"',
            pyproject,
        )
        if not match:
            raise UpdateError("Не удалось определить удалённую версию.")

        sha = str(commit.get("sha") or "")
        if not sha:
            raise UpdateError("GitHub не вернул SHA последнего коммита.")

        return {
            "sha": sha,
            "version": self._display_version(match.group(1)),
        }

    @staticmethod
    def _get_json(url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Dragon-Tory-Updater",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise UpdateError(f"GitHub HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise UpdateError(f"GitHub недоступен: {exc.reason}") from exc

    def _installed_sha(self) -> str | None:
        git_sha = self._git_head()
        if git_sha:
            return git_sha
        state = self._read_state()
        value = state.get("installed_sha")
        return str(value) if value else None

    def _git_head(self) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_root), "rev-parse", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
                timeout=4,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        sha = result.stdout.strip()
        return sha if re.fullmatch(r"[0-9a-fA-F]{40}", sha) else None

    def _read_state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, self.state_path)

    @staticmethod
    def _display_version(value: str) -> str:
        parts = [int(part) for part in re.findall(r"\d+", value)[:3]]
        while len(parts) < 3:
            parts.append(0)
        return ".".join(f"{part:02d}" for part in parts)

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, int, int]:
        parts = [int(part) for part in re.findall(r"\d+", value)[:3]]
        while len(parts) < 3:
            parts.append(0)
        return parts[0], parts[1], parts[2]

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()
