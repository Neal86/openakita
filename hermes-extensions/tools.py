from __future__ import annotations

import json
from typing import Any, Callable

from .task_center import TaskCenter
from .wechat import WeChatDesktop


def _result(fn: Callable[[], Any]) -> str:
    try:
        value = fn()
        return json.dumps({"ok": True, "data": value}, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False)


def _resolve_cron_profile(payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("type") or "") != "cron" or str(payload.get("profile") or "").strip():
        return payload
    task_id = str(payload.get("id") or "").strip()
    if not task_id:
        return payload
    center = TaskCenter()
    matches = [
        job for job in center.cron_jobs()
        if str(job.get("id") or "") == task_id or str(job.get("name") or "").lower() == task_id.lower()
    ]
    profiles = sorted({str(job.get("profile") or "default") for job in matches})
    if len(profiles) == 1:
        return {**payload, "profile": profiles[0]}
    if len(profiles) > 1:
        raise ValueError(f"Cron task reference is ambiguous across profiles: {', '.join(profiles)}")
    return payload


def wechat_status(args: dict, **kwargs) -> str:
    del args, kwargs
    return _result(lambda: WeChatDesktop().status())


def wechat_list_chats(args: dict, **kwargs) -> str:
    del kwargs
    limit = int(args.get("limit", 50))
    return _result(lambda: [row.to_dict() for row in WeChatDesktop().list_chats(limit)])


def wechat_get_unread_chats(args: dict, **kwargs) -> str:
    del kwargs
    limit = int(args.get("limit", 50))
    return _result(lambda: [row.to_dict() for row in WeChatDesktop().unread_chats(limit)])


def wechat_get_messages(args: dict, **kwargs) -> str:
    del kwargs
    chat = str(args.get("chat") or "")
    limit = int(args.get("limit", 20))
    return _result(lambda: WeChatDesktop().get_messages(chat, limit))


def wechat_send_message(args: dict, **kwargs) -> str:
    del kwargs
    chat = str(args.get("chat") or "")
    text = str(args.get("text") or "")
    dry_run = bool(args.get("dry_run", False))
    return _result(lambda: WeChatDesktop().send_message(chat, text, dry_run=dry_run))


def task_center_overview(args: dict, **kwargs) -> str:
    del kwargs
    profile = str(args.get("profile") or "").strip() or None
    include_completed = bool(args.get("include_completed", False))
    return _result(lambda: TaskCenter().overview(profile, include_completed))


def task_center_upcoming(args: dict, **kwargs) -> str:
    del kwargs
    hours = int(args.get("hours", 24 * 7))
    profile = str(args.get("profile") or "").strip() or None
    limit = int(args.get("limit", 200))
    return _result(lambda: TaskCenter().upcoming(hours=hours, profile=profile, limit=limit))


def task_center_create(args: dict, **kwargs) -> str:
    del kwargs
    return _result(lambda: TaskCenter().create(args))


def task_center_update(args: dict, **kwargs) -> str:
    del kwargs
    return _result(lambda: TaskCenter().update(_resolve_cron_profile(dict(args))))


def task_center_action(args: dict, **kwargs) -> str:
    del kwargs
    return _result(lambda: TaskCenter().action(_resolve_cron_profile(dict(args))))


def task_center_history(args: dict, **kwargs) -> str:
    del kwargs
    task_type = str(args.get("type") or "")
    task_id = str(args.get("id") or "")
    limit = int(args.get("limit", 20))
    profile = str(args.get("profile") or "").strip() or None
    if task_type == "cron" and profile is None:
        resolved = _resolve_cron_profile({"type": "cron", "id": task_id})
        profile = str(resolved.get("profile") or "").strip() or None
    return _result(lambda: TaskCenter().history(task_type, task_id, limit=limit, profile=profile))
