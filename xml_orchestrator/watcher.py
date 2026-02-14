"""Linux inotify watcher wrapper with graceful fallback."""

from __future__ import annotations

import ctypes
import os
import select
import struct
import time
from pathlib import Path
from typing import Optional

from .constants import (
    IN_ATTRIB,
    IN_CLOSE_WRITE,
    IN_CREATE,
    IN_DELETE_SELF,
    IN_IGNORED,
    IN_MOVE_SELF,
    IN_MOVED_TO,
    IN_Q_OVERFLOW,
)


class LinuxInotifyWatcher:
    """Watch a single file path via inotify events on its parent directory."""

    _HEADER = struct.Struct("iIII")
    _MASK = (
        IN_ATTRIB
        | IN_CLOSE_WRITE
        | IN_CREATE
        | IN_DELETE_SELF
        | IN_IGNORED
        | IN_MOVE_SELF
        | IN_MOVED_TO
        | IN_Q_OVERFLOW
    )

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.fd: Optional[int] = None
        self.wd: Optional[int] = None
        self._libc: Optional[ctypes.CDLL] = None

        if os.name != "posix":
            return

        try:
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            libc.inotify_init1.argtypes = [ctypes.c_int]
            libc.inotify_init1.restype = ctypes.c_int
            libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
            libc.inotify_add_watch.restype = ctypes.c_int
        except OSError:
            return

        self._libc = libc
        self._open()

    @property
    def available(self) -> bool:
        return self.fd is not None and self.wd is not None

    def _open(self) -> None:
        if self._libc is None:
            return
        flags = os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
        fd = self._libc.inotify_init1(flags)
        if fd < 0:
            return
        self.fd = fd
        self._ensure_watch()

    def _ensure_watch(self) -> None:
        if self._libc is None or self.fd is None:
            return
        dir_bytes = os.fsencode(str(self.file_path.parent))
        wd = self._libc.inotify_add_watch(self.fd, ctypes.c_char_p(dir_bytes), self._MASK)
        if wd < 0:
            self.close()
            return
        self.wd = wd

    def wait(self, timeout_seconds: Optional[float]) -> bool:
        if self.fd is None or self.wd is None:
            if timeout_seconds is not None:
                time.sleep(timeout_seconds)
            return False

        try:
            ready, _, _ = select.select([self.fd], [], [], timeout_seconds)
        except OSError:
            return False
        if not ready:
            return False

        changed = False
        while True:
            try:
                raw = os.read(self.fd, 64 * 1024)
            except BlockingIOError:
                break
            except OSError:
                break
            if not raw:
                break

            offset = 0
            while offset + self._HEADER.size <= len(raw):
                wd, mask, _cookie, name_len = self._HEADER.unpack_from(raw, offset)
                offset += self._HEADER.size
                raw_name = raw[offset : offset + name_len]
                offset += name_len
                name = raw_name.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")

                if mask & IN_Q_OVERFLOW:
                    changed = True
                    continue
                if mask & (IN_IGNORED | IN_DELETE_SELF | IN_MOVE_SELF):
                    changed = True
                    self.wd = None
                    self._ensure_watch()
                    continue
                if wd != self.wd:
                    continue
                if name and name != self.file_path.name:
                    continue
                changed = True

        return changed

    def close(self) -> None:
        if self.fd is None:
            return
        try:
            os.close(self.fd)
        except OSError:
            pass
        finally:
            self.fd = None
            self.wd = None
