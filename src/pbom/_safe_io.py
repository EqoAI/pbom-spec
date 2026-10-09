"""Safe file reads for untrusted ``*.pbom.json`` paths under ``.pbom/``."""

from __future__ import annotations

import os
import stat
from pathlib import Path

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


def read_record_text(path: Path) -> str:
    """Read a PBOM record file as UTF-8, refusing non-regular files and symlinks.

    Record paths under ``.pbom/`` are attacker-controlled (spec §12). A named
    pipe or symlink (e.g. to ``/dev/zero``) matching ``*.pbom.json`` would make
    ``Path.read_text()`` hang or exhaust memory. This helper opens with
    ``O_NOFOLLOW`` / ``O_NONBLOCK`` when available, refuses symlinks, and
    requires a regular file via ``fstat`` on the open fd.
    """
    if path.is_symlink():
        raise OSError(f"refusing symlink record path: {path!r}")

    fd = os.open(path, os.O_RDONLY | _NOFOLLOW | _NONBLOCK)
    try:
        mode = os.fstat(fd).st_mode
        if not stat.S_ISREG(mode):
            raise OSError(f"not a regular file: {path!r}")
        with os.fdopen(fd, "r", encoding="utf-8", closefd=True) as handle:
            fd = -1  # ownership transferred to handle
            return handle.read()
    finally:
        if fd >= 0:
            os.close(fd)
