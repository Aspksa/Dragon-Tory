from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path


_DPAPI_MAGIC = b"TORYDPAPI1"
_DPAPI_DESCRIPTION = "Dragon Tory local Ed25519 seal key"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob(data: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


def _dpapi_protect(data: bytes) -> bytes:
    source, source_buffer = _blob(data)
    _ = source_buffer  # keep the ctypes buffer alive for the native call
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        ctypes.c_wchar_p(_DPAPI_DESCRIPTION),
        None,
        None,
        None,
        0,
        ctypes.byref(output),
    ):
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
    try:
        encrypted = ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
    return _DPAPI_MAGIC + encrypted


def _dpapi_unprotect(payload: bytes) -> bytes:
    encrypted = payload[len(_DPAPI_MAGIC) :]
    source, source_buffer = _blob(encrypted)
    _ = source_buffer  # keep the ctypes buffer alive for the native call
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(output),
    ):
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def private_key_is_os_protected(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        return path.read_bytes().startswith(_DPAPI_MAGIC)
    except OSError:
        return False


def store_private_key(path: Path, raw_key: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _dpapi_protect(raw_key) if os.name == "nt" else raw_key
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(payload)
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, path)


def load_private_key(path: Path) -> bytes:
    payload = path.read_bytes()
    if payload.startswith(_DPAPI_MAGIC):
        if os.name != "nt":
            raise RuntimeError(
                "This Dragon Tory signing key is protected by Windows DPAPI."
            )
        return _dpapi_unprotect(payload)

    # Migrate legacy raw keys to Windows DPAPI on first use.
    if os.name == "nt":
        store_private_key(path, payload)
    else:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return payload
