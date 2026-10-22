"""Windows user-bound DPAPI protection; never fall back to plaintext storage."""
from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise ValueError("Saving API keys requires Windows DPAPI on this Windows build")
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = _Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    # UI forbidden; current-user scope (not CRYPTPROTECT_LOCAL_MACHINE).
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ValueError("Cannot protect/read API key for this Windows user; enter the API key again")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


def protect_key(key: str) -> str:
    return base64.b64encode(_crypt(key.encode("utf-8"))).decode("ascii") if key else ""


def unprotect_key(encoded: str) -> str:
    return _crypt(base64.b64decode(encoded, validate=True), decrypt=True).decode("utf-8") if encoded else ""
