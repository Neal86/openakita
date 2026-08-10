"""Hermes Extensions plugin entry point."""

from . import schemas, tools
from .wechat import WeChatDesktop


def register(ctx):
    wechat = [
        ("wechat_status", schemas.WECHAT_STATUS, tools.wechat_status),
        ("wechat_list_chats", schemas.WECHAT_LIST_CHATS, tools.wechat_list_chats),
        ("wechat_get_unread_chats", schemas.WECHAT_GET_UNREAD_CHATS, tools.wechat_get_unread_chats),
        ("wechat_get_messages", schemas.WECHAT_GET_MESSAGES, tools.wechat_get_messages),
        ("wechat_send_message", schemas.WECHAT_SEND_MESSAGE, tools.wechat_send_message),
    ]
    for name, schema, handler in wechat:
        ctx.register_tool(
            name=name,
            toolset="hermes_extensions_wechat",
            schema=schema,
            handler=handler,
            description=schema["description"],
            check_fn=WeChatDesktop.available,
        )

    task_tools = [
        ("task_center_overview", schemas.TASK_CENTER_OVERVIEW, tools.task_center_overview),
        ("task_center_upcoming", schemas.TASK_CENTER_UPCOMING, tools.task_center_upcoming),
        ("task_center_create", schemas.TASK_CENTER_CREATE, tools.task_center_create),
        ("task_center_update", schemas.TASK_CENTER_UPDATE, tools.task_center_update),
        ("task_center_action", schemas.TASK_CENTER_ACTION, tools.task_center_action),
        ("task_center_history", schemas.TASK_CENTER_HISTORY, tools.task_center_history),
    ]
    for name, schema, handler in task_tools:
        ctx.register_tool(
            name=name,
            toolset="hermes_extensions_tasks",
            schema=schema,
            handler=handler,
            description=schema["description"],
        )
