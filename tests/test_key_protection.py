import os
from pathlib import Path

from tooru.cloud.key_protection import (
    load_private_key,
    private_key_is_os_protected,
    store_private_key,
)


def test_private_key_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "seal.key"
    raw = bytes(range(32))

    store_private_key(path, raw)

    assert load_private_key(path) == raw
    if os.name == "nt":
        assert private_key_is_os_protected(path) is True
        assert path.read_bytes() != raw
    else:
        assert private_key_is_os_protected(path) is False
        assert path.read_bytes() == raw
        assert path.stat().st_mode & 0o077 == 0
