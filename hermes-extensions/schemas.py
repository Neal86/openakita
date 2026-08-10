"""Schemas exposed to Hermes for the extensions plugin."""

WECHAT_STATUS = {
    "name": "wechat_status",
    "description": "Check whether Windows WeChat is running and whether the desktop connector can inspect it.",
    "parameters": {"type": "object", "properties": {}},
}

WECHAT_LIST_CHATS = {
    "name": "wechat_list_chats",
    "description": "List visible WeChat conversations with best-effort unread state. Use before opening or replying to a chat.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
        },
    },
}

WECHAT_GET_UNREAD_CHATS = {
    "name": "wechat_get_unread_chats",
    "description": "List WeChat conversations that appear unread. Results include the exact conversation names for safe follow-up calls.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
        },
    },
}

WECHAT_GET_MESSAGES = {
    "name": "wechat_get_messages",
    "description": "Open an exact WeChat conversation and read the newest visible message rows. Does not send anything.",
    "parameters": {
        "type": "object",
        "properties": {
            "chat": {"type": "string", "description": "Exact conversation name returned by wechat_list_chats."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
        },
        "required": ["chat"],
    },
}

WECHAT_SEND_MESSAGE = {
    "name": "wechat_send_message",
    "description": (
        "Send text to an exact WeChat conversation. The connector re-opens and re-verifies the target immediately before sending "
        "and fails closed if it cannot verify the target. Use only after identifying the exact chat."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "chat": {"type": "string", "description": "Exact conversation name."},
            "text": {"type": "string", "minLength": 1, "maxLength": 4000},
            "dry_run": {"type": "boolean", "default": False, "description": "When true, verify target and payload but do not press Send."},
        },
        "required": ["chat", "text"],
    },
}

TASK_CENTER_OVERVIEW = {
    "name": "task_center_overview",
    "description": "Return a fleet-wide view of Hermes profiles, recurring/one-shot cron jobs, Kanban tasks, and current execution summaries.",
    "parameters": {
        "type": "object",
        "properties": {
            "profile": {"type": "string", "description": "Optional profile filter."},
            "include_completed": {"type": "boolean", "default": False},
        },
    },
}

TASK_CENTER_UPCOMING = {
    "name": "task_center_upcoming",
    "description": "List the next scheduled Hermes tasks across profiles, including expanded future occurrences for recurring cron jobs.",
    "parameters": {
        "type": "object",
        "properties": {
            "hours": {"type": "integer", "minimum": 1, "maximum": 24 * 90, "default": 24 * 7},
            "profile": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
        },
    },
}

TASK_CENTER_CREATE = {
    "name": "task_center_create",
    "description": "Create a Hermes cron task (one-shot or recurring) or a Hermes Kanban task without creating a second scheduler.",
    "parameters": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["cron", "kanban"]},
            "name": {"type": "string", "minLength": 1},
            "prompt": {"type": "string", "description": "Cron prompt or Kanban body."},
            "schedule": {"type": "string", "description": "Cron schedule such as 'every 10m', '0 9 * * *', or ISO8601. Required for cron."},
            "profile": {"type": "string", "description": "Hermes profile that owns/runs the cron job or assignee for Kanban."},
            "priority": {"type": "integer", "minimum": 0, "maximum": 100},
            "deliver": {"type": "string", "description": "Cron delivery target, e.g. local, origin, telegram, or wechat_desktop."},
        },
        "required": ["type", "name"],
    },
}

TASK_CENTER_UPDATE = {
    "name": "task_center_update",
    "description": "Update an existing Hermes cron or Kanban task using Hermes' native mutation interfaces.",
    "parameters": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["cron", "kanban"]},
            "id": {"type": "string"},
            "name": {"type": "string"},
            "prompt": {"type": "string"},
            "schedule": {"type": "string", "description": "Cron-only schedule."},
            "profile": {"type": "string", "description": "Owning Cron profile or Kanban assignee."},
            "priority": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Kanban-only priority."},
        },
        "required": ["type", "id"],
    },
}

TASK_CENTER_ACTION = {
    "name": "task_center_action",
    "description": "Pause, resume, run, or remove a Hermes Cron job; assign or archive a native Hermes Kanban task.",
    "parameters": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["cron", "kanban"]},
            "id": {"type": "string"},
            "action": {"type": "string", "enum": ["pause", "resume", "run", "remove", "assign", "archive"]},
            "value": {"type": "string", "description": "Assignee value; required only for the Kanban assign action."},
            "profile": {"type": "string", "description": "Owning Hermes profile for Cron actions. Omit to auto-resolve an unambiguous task ID/name."},
        },
        "required": ["type", "id", "action"],
    },
}

TASK_CENTER_HISTORY = {
    "name": "task_center_history",
    "description": "Read durable execution history for a Hermes Cron job or the lifecycle record for a native Hermes Kanban task.",
    "parameters": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["cron", "kanban"]},
            "id": {"type": "string"},
            "profile": {"type": "string", "description": "Optional owning Cron profile; omitted values are auto-resolved when unique."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
        },
        "required": ["type", "id"],
    },
}
