import hashlib
from pathlib import Path

import pytest

from tooru.cloud.store import CloudStore
from tooru.cloud.vault import ToryVault


def _store(tmp_path: Path) -> CloudStore:
    root = tmp_path / "cloud"
    store = CloudStore(
        root,
        root / "tooru_cloud.sqlite3",
        vault=ToryVault(root / "vault.json"),
    )
    store.initialize()
    return store


def _upload(store: CloudStore, name: str, content: bytes) -> dict:
    temp = store.incoming_dir / (name + ".upload")
    temp.write_bytes(content)
    return store.register_upload(
        temp,
        name=name,
        content_type="text/plain",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def test_trash_rolls_file_back_when_database_transaction_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _store(tmp_path)
    document = _upload(store, "rollback.txt", b"original")
    path = store.content_path(document["id"])

    def fail_log(*args, **kwargs):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(store, "_log", fail_log)

    with pytest.raises(RuntimeError):
        store.trash(document["id"])

    assert path.is_file()
    assert path.read_bytes() == b"original"
    assert store.get(document["id"])["trashed"] is False


def test_new_version_rolls_current_file_back_on_database_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _store(tmp_path)
    document = _upload(store, "version.txt", b"version-one")
    temp = store.incoming_dir / "version-two.upload"
    temp.write_bytes(b"version-two")

    def fail_log(*args, **kwargs):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(store, "_log", fail_log)

    with pytest.raises(RuntimeError):
        store.add_version(
            document["id"],
            temp,
            name="version.txt",
            content_type="text/plain",
            size_bytes=len(b"version-two"),
            sha256=hashlib.sha256(b"version-two").hexdigest(),
        )

    current = store.get(document["id"])
    assert current["version"] == 1
    assert store.content_path(document["id"]).read_bytes() == b"version-one"
