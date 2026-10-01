import base64
import json
import os
import platform
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import psutil


class UpdateError(RuntimeError):
    pass


class UpdateService:
    """Checks GitHub and supervises the detached Windows updater."""

    RUNNING_PHASES: ClassVar[set[str]] = {
        "starting",
        "checking",
        "downloading",
        "extracting",
        "backing_up",
        "stopping",
        "installing",
        "restarting",
        "verifying",
        "rolling_back",
    }
    STALL_SECONDS: ClassVar[int] = 180

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
        self.history_path = (
            self.project_root / "data" / "update" / "history.json"
        )
        self.launch_log_path = (
            self.project_root / "logs" / "update-launcher.log"
        )
        self.updater_script = (
            self.project_root / "scripts" / "windows" / "update.ps1"
        )
        self.launcher_script = (
            self.project_root
            / "scripts"
            / "windows"
            / "update-launcher.ps1"
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
        state.setdefault("progress_percent", 0)
        state.setdefault("heartbeat_at", None)
        state.setdefault("downloaded_files", [])
        state.setdefault("changed_files", [])
        state.setdefault("new_files", [])
        state.setdefault("removed_files", [])

        if state.get("phase") in self.RUNNING_PHASES:
            state = self._supervise_running_state(state)

        state["repository"] = self.repository
        state["branch"] = self.branch
        state["running"] = state.get("phase") in self.RUNNING_PHASES
        state["stalled"] = self._is_stalled(state) if state["running"] else False
        return state

    def history(self, *, limit: int = 30) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        try:
            raw = json.loads(self.history_path.read_text(encoding="utf-8-sig"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        if not isinstance(raw, list):
            return []
        items = [item for item in raw if isinstance(item, dict)]
        return list(reversed(items[-limit:]))

    def check(self) -> dict[str, Any]:
        current = self.status()
        if current["running"]:
            return current

        self._write_state(
            {
                **current,
                "phase": "checking",
                "message": "Проверка GitHub…",
                "progress_percent": 5,
                "heartbeat_at": self._now(),
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
                available = self._version_tuple(
                    remote["version"]
                ) > self._version_tuple(self.local_version)
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
                "progress_percent": 0,
                "heartbeat_at": self._now(),
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
                "progress_percent": 0,
                "heartbeat_at": self._now(),
            }
            self._write_state(state)
            raise UpdateError(state["error"]) from exc

    def _powershell_executable(self) -> str:
        system_root = os.environ.get("SystemRoot")
        if system_root:
            candidate = (
                Path(system_root)
                / "System32"
                / "WindowsPowerShell"
                / "v1.0"
                / "powershell.exe"
            )
            if candidate.is_file():
                return str(candidate)
        return "powershell.exe"

    def start_install(self, *, force: bool = False) -> dict[str, Any]:
        if platform.system() != "Windows":
            raise UpdateError(
                "Автоматическая установка обновлений поддерживается на Windows."
            )

        current = self.status()
        if current["running"]:
            raise UpdateError("Обновление уже выполняется.")

        checked = self.check()
        if not checked["update_available"] and not force:
            raise UpdateError("Новых обновлений нет.")

        if not self.updater_script.is_file():
            raise UpdateError(f"Не найден updater: {self.updater_script}")

        started_at = self._now()
        state = {
            **checked,
            "phase": "starting",
            "message": "Запуск процесса обновления…",
            "progress_percent": 1,
            "heartbeat_at": started_at,
            "update_started_at": started_at,
            "downloaded_files": [],
            "changed_files": [],
            "new_files": [],
            "removed_files": [],
            "error": None,
        }
        self._write_state(state)

        if not self.launcher_script.is_file():
            raise UpdateError(
                f"Не найден launcher updater: {self.launcher_script}"
            )

        args = [
            self._powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.launcher_script),
            "-ProjectRoot",
            str(self.project_root),
            "-Repository",
            self.repository,
            "-Branch",
            self.branch,
            "-ServerPid",
            str(os.getpid()),
            "-UpdaterScript",
            str(self.updater_script),
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self.launch_log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                args,
                cwd=self.project_root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=flags,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._write_launch_failure(state, exc)
            raise UpdateError(str(exc)) from exc

        launch_text = (
            "Dragon Tory: запуск независимого Windows updater.\n"
            f"Код launcher: {result.returncode}\n"
            f"STDOUT: {result.stdout.strip()}\n"
            f"STDERR: {result.stderr.strip()}\n"
        )
        self.launch_log_path.write_text(
            launch_text,
            encoding="utf-8",
        )

        if result.returncode != 0:
            error = (
                "Не удалось запустить независимый updater. "
                + self._launch_log_tail()
            )
            failed = {
                **state,
                "phase": "failed",
                "message": "Не удалось запустить процесс обновления.",
                "error": error[:2000],
                "progress_percent": 0,
                "heartbeat_at": self._now(),
            }
            self._write_state(failed)
            self._append_history_from_state(failed, success=False)
            raise UpdateError(error)

        match = re.search(r"(?m)^\s*(\d+)\s*$", result.stdout)
        if not match:
            error = (
                "Launcher не вернул PID updater. "
                + self._launch_log_tail()
            )
            failed = {
                **state,
                "phase": "failed",
                "message": "Не удалось определить процесс обновления.",
                "error": error[:2000],
                "progress_percent": 0,
                "heartbeat_at": self._now(),
            }
            self._write_state(failed)
            self._append_history_from_state(failed, success=False)
            raise UpdateError(error)

        updater_pid = int(match.group(1))
        time.sleep(0.5)
        current_after_launch = self._read_state()
        if current_after_launch.get("phase") not in self.RUNNING_PHASES:
            current_after_launch = state

        current_after_launch["updater_pid"] = updater_pid
        current_after_launch["message"] = current_after_launch.get(
            "message"
        ) or "Процесс обновления запущен."
        self._write_state(current_after_launch)

        if not psutil.pid_exists(updater_pid):
            latest = self._read_state()
            if latest.get("phase") not in {
                "success",
                "failed",
                "error",
            }:
                latest.update(
                    {
                        "phase": "failed",
                        "message": "Updater завершился сразу после запуска.",
                        "error": self._launch_log_tail(),
                        "progress_percent": 0,
                        "heartbeat_at": self._now(),
                    }
                )
                self._write_state(latest)
                self._append_history_from_state(
                    latest,
                    success=False,
                )
            raise UpdateError(
                latest.get("error")
                or "Updater завершился сразу после запуска."
            )

        return self.status()

            error = (
                "PowerShell updater завершился до начала установки "
                f"(код {exit_code}). {self._launch_log_tail()}"
            )
            failed = {
                **state,
                **current_after_exit,
                "phase": "failed",
                "message": "Не удалось запустить процесс обновления.",
                "error": error[:2000],
                "progress_percent": 0,
                "heartbeat_at": self._now(),
            }
            self._write_state(failed)
            self._append_history_from_state(failed, success=False)
            raise UpdateError(error)

        current_after_launch = self._read_state()
        if current_after_launch.get("phase") not in self.RUNNING_PHASES:
            current_after_launch = state

        current_after_launch["updater_pid"] = process.pid
        current_after_launch.setdefault(
            "message",
            "Процесс обновления запущен. Ожидание первого статуса…",
        )
        self._write_state(current_after_launch)
        return self.status()

    def _supervise_running_state(
        self,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        pid = state.get("updater_pid")
        if isinstance(pid, int) and pid > 0 and not psutil.pid_exists(pid):
            failed = {
                **state,
                "phase": "failed",
                "message": "Процесс обновления неожиданно завершился.",
                "error": (
                    "Updater больше не запущен. "
                    + self._launch_log_tail()
                )[:2000],
                "progress_percent": 0,
                "heartbeat_at": self._now(),
            }
            self._write_state(failed)
            self._append_history_from_state(failed, success=False)
            return failed

        if self._is_stalled(state):
            state = {
                **state,
                "message": (
                    "Обновление не передавало статус более 3 минут. "
                    "Проверьте журнал обновления."
                ),
            }
        return state

    def _is_stalled(self, state: dict[str, Any]) -> bool:
        heartbeat = self._parse_datetime(state.get("heartbeat_at"))
        if heartbeat is None:
            return False
        age = (datetime.now(UTC) - heartbeat).total_seconds()
        return age > self.STALL_SECONDS

    def _remote_info(self) -> dict[str, str]:
        repo_api = f"https://api.github.com/repos/{self.repository}"
        commit = self._get_json(f"{repo_api}/commits/{self.branch}")
        contents = self._get_json(
            f"{repo_api}/contents/src/tooru/version.py?ref={self.branch}"
        )
        encoded = contents.get("content")
        if not encoded:
            raise UpdateError("GitHub не вернул src/tooru/version.py.")

        version_source = base64.b64decode(encoded).decode("utf-8")
        match = re.search(
            r'(?m)^__version__\s*=\s*"([^"]+)"',
            version_source,
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
            raise UpdateError(
                f"GitHub недоступен: {exc.reason}"
            ) from exc

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
            return json.loads(
                self.state_path.read_text(encoding="utf-8-sig")
            )
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

    def _append_history_from_state(
        self,
        state: dict[str, Any],
        *,
        success: bool,
    ) -> None:
        history = list(reversed(self.history(limit=100)))
        signature = (
            state.get("update_started_at"),
            state.get("remote_sha"),
            "success" if success else "failed",
        )
        for item in history:
            existing = (
                item.get("started_at"),
                item.get("sha"),
                item.get("result"),
            )
            if existing == signature:
                return

        entry = {
            "started_at": state.get("update_started_at"),
            "finished_at": self._now(),
            "from_version": state.get("local_version"),
            "to_version": state.get("remote_version"),
            "sha": state.get("remote_sha"),
            "result": "success" if success else "failed",
            "description": (
                "Обновление успешно установлено."
                if success
                else "Обновление завершилось ошибкой."
            ),
            "error": state.get("error"),
            "downloaded_files": state.get("downloaded_files", []),
            "changed_files": state.get("changed_files", []),
            "new_files": state.get("new_files", []),
            "removed_files": state.get("removed_files", []),
        }
        history.append(entry)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.history_path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(history[-100:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, self.history_path)

    def _write_launch_failure(
        self,
        state: dict[str, Any],
        exc: OSError,
    ) -> None:
        failed = {
            **state,
            "phase": "failed",
            "message": "Не удалось запустить updater.",
            "error": f"{type(exc).__name__}: {exc}",
            "progress_percent": 0,
            "heartbeat_at": self._now(),
        }
        self._write_state(failed)
        self._append_history_from_state(failed, success=False)

    def _launch_log_tail(self) -> str:
        try:
            lines = self.launch_log_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            return "Журнал запуска пуст."
        if not lines:
            return "Журнал запуска пуст."
        return "Последние строки: " + " | ".join(lines[-8:])[:1200]

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

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
