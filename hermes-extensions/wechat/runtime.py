from __future__ import annotations

import contextlib
import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Iterator

from .adapter import WeChatDesktop as _BaseWeChatDesktop, WeChatUnavailable


_UI_THREAD_LOCK = threading.RLock()
_LOCK_LOCAL = threading.local()


class _CrossProcessFileLock:
    """Small cross-process lock used to serialize WeChat UI side effects.

    WeChat is one shared desktop window. Different Hermes processes (gateway,
    tools, dashboard workers) must never search/select/type concurrently.
    """

    def __init__(self, path: Path, timeout: float = 15.0) -> None:
        self.path = path
        self.timeout = max(0.1, float(timeout))
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._handle = handle
                return
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    handle.close()
                    raise WeChatUnavailable(
                        "Timed out waiting for exclusive WeChat desktop access; refusing concurrent UI automation"
                    )
                time.sleep(0.05)

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class WeChatDesktop(_BaseWeChatDesktop):
    """Hardened runtime facade with cross-instance/process UI transactions."""

    def __init__(self, data_dir: Path | None = None, *, lock_timeout: float = 15.0) -> None:
        super().__init__(data_dir=data_dir)
        self._ui_lock_path = self.data_dir / "desktop-ui.lock"
        self._ui_lock_timeout = max(0.1, float(lock_timeout))

    @contextlib.contextmanager
    def _ui_transaction(self) -> Iterator[None]:
        # Re-entrant for nested calls such as get_messages -> open_chat. The
        # process file lock is acquired only by the outermost call.
        with _UI_THREAD_LOCK:
            depth = int(getattr(_LOCK_LOCAL, "depth", 0))
            if depth:
                _LOCK_LOCAL.depth = depth + 1
                try:
                    yield
                finally:
                    _LOCK_LOCAL.depth -= 1
                return

            lock = _CrossProcessFileLock(self._ui_lock_path, self._ui_lock_timeout)
            lock.acquire()
            _LOCK_LOCAL.depth = 1
            try:
                yield
            finally:
                _LOCK_LOCAL.depth = 0
                lock.release()

    def open_chat(self, chat: str) -> None:
        with self._ui_transaction():
            return super().open_chat(chat)

    def list_chats(self, limit: int = 50):
        with self._ui_transaction():
            return super().list_chats(limit)

    def unread_chats(self, limit: int = 50):
        with self._ui_transaction():
            return super().unread_chats(limit)

    def get_messages(self, chat: str, limit: int = 20) -> list[dict]:
        with self._ui_transaction():
            super().open_chat(chat)
            win = self._main_window()
            rows = self._message_rows(win, chat)
            compact: list[dict] = []
            previous_key = None
            for row in rows:
                sender = row.get("sender")
                shown_time = row.get("time")
                direction = row.get("direction") or ""
                key = (row["text"], sender, shown_time, direction, row.get("top"), row.get("left"))
                if key == previous_key:
                    continue
                previous_key = key
                identity_source = "\0".join(
                    [
                        chat,
                        str(sender or ""),
                        str(row["text"]),
                        str(shown_time or ""),
                        str(row.get("top") or ""),
                        str(row.get("left") or ""),
                        direction,
                    ]
                )
                compact.append(
                    {
                        "text": row["text"],
                        "sender": sender,
                        "time": shown_time,
                        "direction": direction,
                        "message_id": hashlib.sha256(identity_source.encode("utf-8")).hexdigest()[:24],
                    }
                )
            return compact[-max(1, min(int(limit), 100)) :]

    def send_message(
        self,
        chat: str,
        text: str,
        *,
        dry_run: bool = False,
        duplicate_ttl: int = 600,
    ) -> dict:
        # Includes state read/write and the entire select -> verify -> type ->
        # verify -> Enter critical section, so another process cannot switch
        # the shared desktop between final verification and send.
        with self._ui_transaction():
            return super().send_message(
                chat,
                text,
                dry_run=dry_run,
                duplicate_ttl=duplicate_ttl,
            )
