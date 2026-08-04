"""Register the independent ``wechat_desktop`` channel type."""

from __future__ import annotations

from openakita.channels.adapters.wechat_desktop import WeChatDesktopAdapter
from openakita.plugins.api import PluginAPI, PluginBase


def _factory(
    creds: dict,
    *,
    channel_name: str,
    bot_id: str,
    agent_profile_id: str,
) -> WeChatDesktopAdapter:
    return WeChatDesktopAdapter(
        node_id=str(creds.get("node_id") or ""),
        wechat_account_id=str(creds.get("wechat_account_id") or ""),
        wechat_account_name=str(creds.get("wechat_account_name") or ""),
        allowed_groups=list(creds.get("allowed_groups") or []),
        allowed_contacts=list(creds.get("allowed_contacts") or []),
        ignore_senders=list(creds.get("ignore_senders") or []),
        mention_only=bool(creds.get("mention_only", False)),
        private_chat_enabled=bool(creds.get("private_chat_enabled", False)),
        auto_reply=bool(creds.get("auto_reply", True)),
        merge_window_seconds=int(creds.get("merge_window_seconds", 2)),
        send_interval_seconds=int(creds.get("send_interval_seconds", 3)),
        duplicate_ttl_seconds=int(creds.get("duplicate_ttl_seconds", 600)),
        agent_timeout_seconds=int(creds.get("agent_timeout_seconds", 180)),
        channel_name=channel_name,
        bot_id=bot_id,
        agent_profile_id=agent_profile_id,
    )


class Plugin(PluginBase):
    def on_load(self, api: PluginAPI) -> None:
        self._api = api
        api.register_channel("wechat_desktop", _factory)
        api.log("微信（桌面版）渠道已注册")

    def on_unload(self) -> None:
        pass
