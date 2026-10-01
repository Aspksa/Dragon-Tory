from pathlib import Path

from tooru.api.settings import _write_env_values


def test_env_writer_updates_secret_without_exposing_it(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TOORU_APP_NAME=Dragon Tory\nTOORU_DEEPSEEK_API_KEY=old\n",
        encoding="utf-8",
    )

    _write_env_values(
        env_file,
        {
            "TOORU_DEEPSEEK_API_KEY": "new-secret-value",
            "TOORU_DEEPSEEK_MODEL": "deepseek-ai/DeepSeek-V4-Flash",
        },
    )

    content = env_file.read_text(encoding="utf-8")
    assert 'TOORU_DEEPSEEK_API_KEY="new-secret-value"' in content
    assert 'TOORU_DEEPSEEK_MODEL="deepseek-ai/DeepSeek-V4-Flash"' in content
    assert "old" not in content
