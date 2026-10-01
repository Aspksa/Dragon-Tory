from pathlib import Path

import pytest

from tooru.cloud.store import CloudStore
from tooru.cloud.vault import ToryVault


def test_vault_encrypts_and_unlocks_protected_document(
    tmp_path: Path,
) -> None:
    passphrase = "Dragon-Tory-Test-Passphrase-2026"
    root = tmp_path / "cloud"
    vault = ToryVault(root / "vault.json")
    status = vault.setup(passphrase)
    assert status["configured"] is True
    assert status["unlocked"] is True
    metadata = (root / "vault.json").read_text(encoding="utf-8")
    assert passphrase not in metadata

    store = CloudStore(
        root,
        root / "tooru_cloud.sqlite3",
        vault=vault,
    )
    store.initialize()

    incoming = root / ".incoming" / "secret.upload"
    incoming.write_bytes(b"top secret Tory document")
    document = store.register_upload(
        incoming,
        name="secret.txt",
        content_type="text/plain",
        size_bytes=24,
        sha256=(
            "af18fab6e151ea62ca52ba5dd56fe3d77de7fc29"
            "c5d77ee10bd49571a9952609"
        ),
    )
    document_id = document["id"]

    protected = store.update_passport(
        document_id,
        confidentiality="highly_protected",
        ai_access="denied",
    )
    assert protected["encrypted"] is True
    physical = store.content_path(document_id)
    payload = physical.read_bytes()
    assert payload.startswith(b"TORYVAULT1")
    assert b"top secret Tory document" not in payload

    vault.lock()
    with pytest.raises(PermissionError):
        store.materialize_plaintext(document_id)

    with pytest.raises(ValueError):
        vault.unlock("wrong-passphrase-000")

    vault.unlock(passphrase)
    plaintext, cleanup = store.materialize_plaintext(document_id)
    try:
        assert plaintext.read_bytes() == b"top secret Tory document"
    finally:
        if cleanup is not None:
            cleanup.unlink(missing_ok=True)

    downgraded = store.update_passport(
        document_id,
        confidentiality="personal",
        ai_access="denied",
    )
    assert downgraded["encrypted"] is False
    assert store.content_path(document_id).read_bytes() == (
        b"top secret Tory document"
    )
