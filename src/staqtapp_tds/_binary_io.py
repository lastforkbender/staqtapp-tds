"""Platform-safe raw file-descriptor helpers.

Windows opens ``os.open`` descriptors in text mode unless ``O_BINARY`` is
requested. Storage code writes byte-exact formats through ``os.write``, so
text-mode newline expansion would invalidate offsets, sizes, and digests.
"""

from __future__ import annotations

import os
from os import PathLike
from typing import Any


def open_binary_fd(path: str | bytes | PathLike[Any], flags: int, mode: int = 0o777) -> int:
    """Open a raw descriptor with Windows text translation disabled."""

    return os.open(path, flags | getattr(os, "O_BINARY", 0), mode)
