from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from .config_service import LOG_PATH, ensure_app_dir

StatusCallback = Callable[[str], None]


class ConnectorService:
    def __init__(self, status_callback: StatusCallback | None = None) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._watcher: threading.Thread | None = None
        self._status_callback = status_callback or (lambda _value: None)
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.running:
            return
        ensure_app_dir()
        self._stopping = False
        self._status_callback("正在连接")
        target = Path(__file__).with_name("connector.py")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            [sys.executable, str(target)],
            cwd=str(target.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=creationflags,
        )
        self._watcher = threading.Thread(target=self._watch, daemon=True)
        self._watcher.start()

    def _watch(self) -> None:
        time.sleep(1)
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            self._status_callback("运行正常")
            return
        if not self._stopping:
            self._status_callback("连接异常")

    def stop(self) -> None:
        self._stopping = True
        process = self._process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        self._process = None
        self._status_callback("已停止")

    def restart(self) -> None:
        self.stop()
        self.start()

    def open_log(self) -> None:
        ensure_app_dir()
        LOG_PATH.touch(exist_ok=True)
        subprocess.Popen(["notepad.exe", str(LOG_PATH)])
