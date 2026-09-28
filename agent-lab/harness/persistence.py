"""Crash-tolerant writes for harness-owned state and project files."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Replace a binary file only after its complete contents are on disk."""

    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            file_descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if file_descriptor != -1:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Replace a file only after its complete contents are on disk.

    The temporary file lives beside the destination so ``os.replace`` is a
    same-volume operation.  A failed replace leaves the previous destination
    intact and removes the temporary file.
    """

    if not isinstance(content, str):
        raise TypeError("content must be a string")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding=encoding, newline="") as handle:
            file_descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if file_descriptor != -1:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
    )

