from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from wxauto4 import WeChat
except ImportError as exc:  # pragma: no cover - environment validation
    raise SystemExit("wxauto4 is not installed. Run: pip install -r requirements.txt") from exc


@dataclass(frozen=True)
class IncomingMessage:
    group_name: str
    sender: str
    content: str
    message_id: str


class StateStore:
    def __init__(self, path: Path, ttl_seconds: int) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            now = time.time()
            self._seen = {
                str(key): float(value)
                for key, value in data.get("seen", {}).items()
                if now - float(value) <= self.ttl_seconds
            }
        except (OSError, ValueError, TypeError):
            logging.exception("Unable to load bridge state; starting with an empty state")
            self._seen = {}

    def claim(self, message_id: str) -> bool:
        with self._lock:
            now = time.time()
            cutoff = now - self.ttl_seconds
            self._seen = {key: value for key, value in self._seen.items() if value >= cutoff}
            if message_id in self._seen:
                return False
            self._seen[message_id] = now
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps({"seen": self._seen}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            return True


class OpenAkitaRunner:
    def __init__(self, config: dict[str, Any]) -> None:
        self.command = str(config.get("command", "openakita"))
        self.timeout = int(config.get("timeout_seconds", 180))
        self.cwd = str(config.get("working_directory", "")).strip() or None
        self.agent_id = str(config.get("agent_id", "")).strip()
        self.prompt_template = str(config["prompt_template"])

    def reply(self, message: IncomingMessage) -> str:
        prompt = self.prompt_template.format(
            group_name=message.group_name,
            sender=message.sender,
            message=message.content,
            agent_id=self.agent_id,
        )
        args = [self.command, "run"]
        if self.agent_id:
            args.extend(["--agent", self.agent_id])
        args.append(prompt)
        result = subprocess.run(
            args,
            cwd=self.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            raise RuntimeError(f"OpenAkita failed: {error}")
        reply = result.stdout.strip()
        if not reply:
            raise RuntimeError("OpenAkita returned an empty reply")
        return self._clean_reply(reply)

    @staticmethod
    def _clean_reply(text: str) -> str:
        value = text.strip()
        if value.startswith("```") and value.endswith("```"):
            lines = value.splitlines()
            value = "\n".join(lines[1:-1]).strip()
        return value


class WeChatDesktopBridge:
    def __init__(self, config: dict[str, Any], config_path: Path) -> None:
        wechat = config["wechat"]
        runtime = config.get("runtime", {})
        self.groups = {str(item).strip() for item in wechat.get("groups", []) if str(item).strip()}
        if not self.groups:
            raise ValueError("wechat.groups must contain at least one group")
        self.ignore_senders = {str(item).strip() for item in wechat.get("ignore_senders", [])}
        self.reply_prefix = str(wechat.get("reply_prefix", ""))
        self.poll_interval = float(wechat.get("poll_interval_seconds", 1.0))
        self.send_interval = float(wechat.get("min_send_interval_seconds", 3))
        self.merge_window = float(wechat.get("merge_window_seconds", 2))
        self.failed_file = self._resolve(config_path, runtime.get("failed_message_file", "data/wechat-bridge-failed.jsonl"))
        state_file = self._resolve(config_path, runtime.get("state_file", "data/wechat-bridge-state.json"))
        self.state = StateStore(state_file, int(wechat.get("duplicate_ttl_seconds", 600)))
        self.runner = OpenAkitaRunner(config["openakita"])
        self.wx = WeChat()
        self._last_send: dict[str, float] = {}
        self._pending: dict[tuple[str, str], list[IncomingMessage]] = {}
        self._pending_lock = threading.Lock()

    @staticmethod
    def _resolve(config_path: Path, value: Any) -> Path:
        path = Path(str(value))
        return path if path.is_absolute() else config_path.parent / path

    def run(self) -> None:
        for group in sorted(self.groups):
            logging.info("Adding WeChat listener: %s", group)
            self.wx.AddListenChat(who=group)
        logging.info("WeChat desktop bridge started for %d group(s)", len(self.groups))
        while True:
            try:
                raw = self.wx.GetListenMessage() or {}
                for chat, messages in raw.items():
                    group_name = self._chat_name(chat)
                    if group_name not in self.groups:
                        continue
                    for item in messages or []:
                        parsed = self._parse(group_name, item)
                        if parsed is not None and self.state.claim(parsed.message_id):
                            self._queue(parsed)
                self._flush_ready()
            except KeyboardInterrupt:
                logging.info("Bridge stopped")
                return
            except Exception:
                logging.exception("WeChat polling failed")
                time.sleep(max(self.poll_interval, 3.0))
            time.sleep(self.poll_interval)

    def _queue(self, message: IncomingMessage) -> None:
        key = (message.group_name, message.sender)
        with self._pending_lock:
            self._pending.setdefault(key, []).append(message)
        logging.info("Queued message | group=%s sender=%s", message.group_name, message.sender)

    def _flush_ready(self) -> None:
        now = time.time()
        ready: list[list[IncomingMessage]] = []
        with self._pending_lock:
            for key, messages in list(self._pending.items()):
                timestamp = self._message_timestamp(messages[-1].message_id)
                if now - timestamp >= self.merge_window:
                    ready.append(self._pending.pop(key))
        for messages in ready:
            merged = IncomingMessage(
                group_name=messages[-1].group_name,
                sender=messages[-1].sender,
                content="\n".join(item.content for item in messages),
                message_id=messages[-1].message_id,
            )
            threading.Thread(target=self._process, args=(merged,), daemon=True).start()

    def _process(self, message: IncomingMessage) -> None:
        try:
            reply = self.runner.reply(message)
            self._throttle(message.group_name)
            self.wx.SendMsg(self.reply_prefix + reply, who=message.group_name)
            self._last_send[message.group_name] = time.time()
            logging.info("Reply sent | group=%s sender=%s", message.group_name, message.sender)
        except Exception as exc:
            logging.exception("Message processing failed")
            self.failed_file.parent.mkdir(parents=True, exist_ok=True)
            record = {"time": time.time(), "message": message.__dict__, "error": str(exc)}
            with self.failed_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _throttle(self, group_name: str) -> None:
        wait = self.send_interval - (time.time() - self._last_send.get(group_name, 0.0))
        if wait > 0:
            time.sleep(wait)

    def _parse(self, group_name: str, raw: Any) -> IncomingMessage | None:
        sender = str(getattr(raw, "sender", "") or getattr(raw, "sender_name", "")).strip()
        content = str(getattr(raw, "content", "") or "").strip()
        if not content or sender in self.ignore_senders:
            return None
        native_id = getattr(raw, "id", None)
        timestamp = getattr(raw, "time", None) or time.time()
        seed = str(native_id or f"{group_name}|{sender}|{timestamp}|{content}")
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return IncomingMessage(group_name, sender, content, f"{time.time()}:{digest}")

    @staticmethod
    def _message_timestamp(message_id: str) -> float:
        try:
            return float(message_id.split(":", 1)[0])
        except (TypeError, ValueError):
            return time.time()

    @staticmethod
    def _chat_name(chat: Any) -> str:
        return str(getattr(chat, "who", "") or getattr(chat, "name", "") or chat).strip()


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if "wechat" not in data or "openakita" not in data:
        raise ValueError("Config must contain wechat and openakita sections")
    return data


def configure_logging(config: dict[str, Any], config_path: Path) -> None:
    runtime = config.get("runtime", {})
    level = getattr(logging, str(runtime.get("log_level", "INFO")).upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_file = runtime.get("log_file")
    if log_file:
        path = Path(str(log_file))
        if not path.is_absolute():
            path = config_path.parent / path
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAkita personal WeChat desktop bridge")
    parser.add_argument("--config", default="config.yaml", help="YAML configuration path")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    configure_logging(config, config_path)
    WeChatDesktopBridge(config, config_path).run()


if __name__ == "__main__":
    main()
