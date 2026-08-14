from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

try:
    from wxauto4 import WeChat
except ImportError as exc:  # pragma: no cover - environment validation
    raise SystemExit("wxauto4 is not installed. Run: pip install -r requirements.txt") from exc


ConversationType = Literal["private", "group"]


@dataclass(frozen=True)
class Conversation:
    account_id: str
    conversation_id: str
    conversation_type: ConversationType
    chat_id: str
    chat_name: str


@dataclass(frozen=True)
class IncomingMessage:
    account_id: str
    conversation_id: str
    conversation_type: ConversationType
    chat_id: str
    chat_name: str
    sender_id: str
    sender_name: str
    content: str
    message_id: str
    timestamp: float


@dataclass(frozen=True)
class ReplyEnvelope:
    conversation_id: str
    chat_name: str
    reply_to: str
    text: str


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
            account_id=message.account_id,
            conversation_id=message.conversation_id,
            conversation_type=message.conversation_type,
            chat_id=message.chat_id,
            chat_name=message.chat_name,
            group_name=message.chat_name,  # backward-compatible template variable
            sender_id=message.sender_id,
            sender_name=message.sender_name,
            sender=message.sender_name,  # backward-compatible template variable
            message_id=message.message_id,
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
        policy = config.get("group_policy", {})

        self.account_id = self._slug(str(wechat.get("account_id", "pc01"))) or "pc01"
        self.group_names = {str(item).strip() for item in wechat.get("groups", []) if str(item).strip()}
        self.private_names = {str(item).strip() for item in wechat.get("private_chats", []) if str(item).strip()}

        for item in wechat.get("chats", []) or []:
            if isinstance(item, str):
                name, kind = item.strip(), "group"
            else:
                name = str(item.get("name", "")).strip()
                kind = str(item.get("type", "group")).strip().lower()
            if not name:
                continue
            if kind == "private":
                self.private_names.add(name)
            elif kind == "group":
                self.group_names.add(name)
            else:
                raise ValueError(f"Unsupported WeChat chat type for {name!r}: {kind!r}")

        if not self.group_names and not self.private_names:
            raise ValueError("Configure at least one wechat.groups, wechat.private_chats, or wechat.chats entry")

        self.ignore_senders = {str(item).strip() for item in wechat.get("ignore_senders", []) if str(item).strip()}
        self.reply_prefix = str(wechat.get("reply_prefix", ""))
        self.poll_interval = float(wechat.get("poll_interval_seconds", 1.0))
        self.send_interval = float(wechat.get("min_send_interval_seconds", 3))
        self.merge_window = float(wechat.get("merge_window_seconds", 2))

        self.group_mode = str(policy.get("mode", "all")).strip().lower()
        if self.group_mode not in {"all", "mention", "question", "mention_or_question"}:
            raise ValueError("group_policy.mode must be all, mention, question, or mention_or_question")
        self.mention_names = {
            str(item).strip().lstrip("@").strip()
            for item in policy.get("mention_names", [])
            if str(item).strip()
        }
        self.mention_sender_on_reply = bool(policy.get("mention_sender_on_reply", True))

        self.failed_file = self._resolve(config_path, runtime.get("failed_message_file", "data/wechat-bridge-failed.jsonl"))
        self.event_file = self._resolve(config_path, runtime.get("event_file", "data/wechat-bridge-events.jsonl"))
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

    @staticmethod
    def _slug(value: str) -> str:
        normalized = re.sub(r"[^0-9A-Za-z_.-]+", "-", value.strip())
        return normalized.strip("-")

    @staticmethod
    def _native_id(obj: Any) -> str:
        for attr in ("wxid", "id", "chat_id", "user_id", "username"):
            value = getattr(obj, attr, None)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    def run(self) -> None:
        targets = sorted(self.group_names | self.private_names)
        for chat_name in targets:
            logging.info("Adding WeChat listener: %s", chat_name)
            self.wx.AddListenChat(who=chat_name)
        logging.info(
            "WeChat desktop bridge started | account=%s groups=%d private=%d",
            self.account_id,
            len(self.group_names),
            len(self.private_names),
        )
        while True:
            try:
                raw = self.wx.GetListenMessage() or {}
                for chat, messages in raw.items():
                    conversation = self._conversation(chat)
                    if conversation is None:
                        continue
                    for item in messages or []:
                        parsed = self._parse(conversation, item)
                        if parsed is not None and self.state.claim(parsed.message_id):
                            self._record_event("incoming", parsed)
                            self._queue(parsed)
                self._flush_ready()
            except KeyboardInterrupt:
                logging.info("Bridge stopped")
                return
            except Exception:
                logging.exception("WeChat polling failed")
                time.sleep(max(self.poll_interval, 3.0))
            time.sleep(self.poll_interval)

    def _conversation(self, chat: Any) -> Conversation | None:
        chat_name = self._chat_name(chat)
        if chat_name in self.group_names:
            kind: ConversationType = "group"
        elif chat_name in self.private_names:
            kind = "private"
        else:
            return None
        native = self._native_id(chat)
        chat_id = native or self._stable_token(f"{kind}|{chat_name}")
        conversation_id = f"wechat:{self.account_id}:{kind}:{chat_id}"
        return Conversation(self.account_id, conversation_id, kind, chat_id, chat_name)

    def _queue(self, message: IncomingMessage) -> None:
        key = (message.conversation_id, message.sender_id)
        with self._pending_lock:
            self._pending.setdefault(key, []).append(message)
        logging.info(
            "Queued message | conversation=%s sender=%s",
            message.conversation_id,
            message.sender_name,
        )

    def _flush_ready(self) -> None:
        now = time.time()
        ready: list[list[IncomingMessage]] = []
        with self._pending_lock:
            for key, messages in list(self._pending.items()):
                if now - messages[-1].timestamp >= self.merge_window:
                    ready.append(self._pending.pop(key))
        for messages in ready:
            last = messages[-1]
            merged = IncomingMessage(
                account_id=last.account_id,
                conversation_id=last.conversation_id,
                conversation_type=last.conversation_type,
                chat_id=last.chat_id,
                chat_name=last.chat_name,
                sender_id=last.sender_id,
                sender_name=last.sender_name,
                content="\n".join(item.content for item in messages),
                message_id=last.message_id,
                timestamp=last.timestamp,
            )
            threading.Thread(target=self._process, args=(merged,), daemon=True).start()

    def _process(self, message: IncomingMessage) -> None:
        try:
            reply = self.runner.reply(message)
            envelope = self._reply_envelope(message, reply)
            self._throttle(envelope.conversation_id)
            self.wx.SendMsg(self.reply_prefix + envelope.text, who=envelope.chat_name)
            self._last_send[envelope.conversation_id] = time.time()
            self._record_event("outgoing", envelope)
            logging.info(
                "Reply sent | conversation=%s reply_to=%s",
                envelope.conversation_id,
                envelope.reply_to,
            )
        except Exception as exc:
            logging.exception("Message processing failed")
            self.failed_file.parent.mkdir(parents=True, exist_ok=True)
            record = {"time": time.time(), "message": asdict(message), "error": str(exc)}
            with self.failed_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _reply_envelope(self, message: IncomingMessage, reply: str) -> ReplyEnvelope:
        text = reply.strip()
        if message.conversation_type == "group" and self.mention_sender_on_reply and message.sender_name:
            marker = f"@{message.sender_name}"
            if not text.startswith(marker):
                text = f"{marker} {text}"
        return ReplyEnvelope(
            conversation_id=message.conversation_id,
            chat_name=message.chat_name,
            reply_to=message.sender_id,
            text=text,
        )

    def _throttle(self, conversation_id: str) -> None:
        wait = self.send_interval - (time.time() - self._last_send.get(conversation_id, 0.0))
        if wait > 0:
            time.sleep(wait)

    def _parse(self, conversation: Conversation, raw: Any) -> IncomingMessage | None:
        sender_name = str(getattr(raw, "sender", "") or getattr(raw, "sender_name", "")).strip()
        content = str(getattr(raw, "content", "") or "").strip()
        if not content or sender_name in self.ignore_senders:
            return None
        if conversation.conversation_type == "group" and not self._group_should_handle(content):
            return None

        sender_native = self._native_id(raw)
        sender_id = sender_native or self._stable_token(f"sender|{sender_name}")
        timestamp_value = getattr(raw, "time", None)
        try:
            timestamp = float(timestamp_value) if timestamp_value is not None else time.time()
        except (TypeError, ValueError):
            timestamp = time.time()
        native_message_id = getattr(raw, "id", None) or getattr(raw, "message_id", None)
        seed = str(
            native_message_id
            or f"{conversation.conversation_id}|{sender_id}|{timestamp}|{content}"
        )
        message_id = self._stable_token(seed, length=64)
        return IncomingMessage(
            account_id=conversation.account_id,
            conversation_id=conversation.conversation_id,
            conversation_type=conversation.conversation_type,
            chat_id=conversation.chat_id,
            chat_name=conversation.chat_name,
            sender_id=sender_id,
            sender_name=sender_name,
            content=content,
            message_id=message_id,
            timestamp=timestamp,
        )

    def _group_should_handle(self, content: str) -> bool:
        if self.group_mode == "all":
            return True
        mentioned = any(f"@{name}" in content for name in self.mention_names) if self.mention_names else False
        question = self._looks_like_question(content)
        if self.group_mode == "mention":
            return mentioned
        if self.group_mode == "question":
            return question
        return mentioned or question

    @staticmethod
    def _looks_like_question(content: str) -> bool:
        if "?" in content or "？" in content:
            return True
        markers = (
            "怎么", "怎样", "如何", "为什么", "为何", "多少", "多久", "什么时候",
            "哪里", "哪儿", "能不能", "可以吗", "是不是", "有没有", "查一下", "查询",
            "订单", "物流", "发货", "库存", "退货", "退款", "tracking", "where", "when", "why", "how",
        )
        lowered = content.lower()
        return any(marker in lowered for marker in markers)

    def _record_event(self, direction: str, payload: IncomingMessage | ReplyEnvelope) -> None:
        self.event_file.parent.mkdir(parents=True, exist_ok=True)
        record = {"time": time.time(), "direction": direction, "payload": asdict(payload)}
        with self.event_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _stable_token(seed: str, length: int = 24) -> str:
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:length]

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
    parser = argparse.ArgumentParser(description="OpenAkita personal WeChat desktop gateway")
    parser.add_argument("--config", default="config.yaml", help="YAML configuration path")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    configure_logging(config, config_path)
    WeChatDesktopBridge(config, config_path).run()


if __name__ == "__main__":
    main()
