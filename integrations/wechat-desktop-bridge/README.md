# OpenAkita Personal WeChat Desktop Gateway

This component runs on the same Windows computer as the logged-in WeChat desktop client. It listens to configured private chats and group chats, converts every incoming message into a conversation-aware envelope, forwards the message to the selected OpenAkita/Hermes Agent, and sends the final reply back to the original conversation.

## Message routing model

The bridge owns routing. The Agent generates reply content, but it does not choose the destination.

Each incoming message contains at least:

```text
account_id
conversation_id
conversation_type = private | group
chat_id
chat_name
sender_id
sender_name
message_id
content
timestamp
```

`conversation_id` is generated as:

```text
wechat:<account_id>:<conversation_type>:<chat_id>
```

When wxauto4 exposes a native chat identifier, the bridge uses it as `chat_id`. Otherwise it creates a deterministic hash from the configured chat type and display name. This keeps routing stable across bridge restarts; changing a chat display name can change the fallback identifier when no native ID is available.

Messages are merged by `(conversation_id, sender_id)`, not just by group name. This prevents simultaneous speakers in one customer group from sharing the same pending-message bucket.

Replies are represented internally as:

```json
{
  "conversation_id": "wechat:pc01:group:<chat_id>",
  "chat_name": "客户群A",
  "reply_to": "<sender_id>",
  "text": "@张三 您的订单已经出库……"
}
```

The final send operation uses the original conversation resolved by the Connector. The Agent cannot redirect a reply by returning another `conversation_id`.

## Supported conversations

- configured WeChat private chats;
- configured WeChat group chats;
- multiple groups and private chats on the same logged-in Windows WeChat account;
- per-sender message merging inside a group;
- optional group reply filtering;
- textual `@sender` prefix on group replies.

The `@sender` prefix makes the intended recipient explicit. Whether it becomes a native WeChat mention/notification depends on the installed WeChat and wxauto4 version; the bridge does not claim native-mention support when wxauto4 only sends text.

## Group policy

`group_policy.mode` supports:

- `all`: process every non-ignored group message;
- `mention`: process messages containing one of `mention_names`;
- `question`: process messages that look like customer questions;
- `mention_or_question`: process either condition.

`question` is intentionally a lightweight local pre-filter. The Agent remains responsible for business interpretation and escalation rules.

## Requirements

- Windows 10 or 11
- Python 3.11
- WeChat desktop already logged in
- OpenAkita CLI installed and working (`openakita run ...`)
- The target Agent already configured with its business rules, knowledge, skills, and MCP servers

The bridge contains no customer-service business rules. Order lookup, reply policy, escalation, working hours, and WMS access remain in the selected OpenAkita/Hermes Agent.

## Start

1. Double-click `run.bat` once. It creates `.venv` and `config.yaml`.
2. Edit `config.yaml`:
   - set `wechat.account_id` to a unique value for this Windows/WeChat instance;
   - put exact group names under `wechat.groups`;
   - put exact private-chat names under `wechat.private_chats`;
   - or use the unified `wechat.chats` entries with `type: group|private`;
   - set `openakita.agent_id` to the Agent that handles customer service;
   - add the account's own displayed sender name to `ignore_senders`;
   - choose a `group_policy.mode`.
3. Keep WeChat desktop open and double-click `run.bat` again.

Manual start:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.example.yaml config.yaml
python main.py --config config.yaml
```

## Implemented safeguards

- explicit private/group chat allowlists;
- Connector-owned `conversation_id` routing;
- sender identity attached to every message;
- ignored-sender list to prevent reply loops;
- persistent duplicate detection across restarts;
- short message merge window per conversation and sender;
- minimum send interval per conversation;
- OpenAkita timeout and non-zero exit handling;
- outgoing/incoming event JSONL archive for route auditing;
- failed-message JSONL archive;
- UTF-8 file and subprocess handling.

## Runtime files

- `logs/wechat-bridge.log`: runtime log;
- `data/wechat-bridge-state.json`: duplicate state;
- `data/wechat-bridge-events.jsonl`: incoming/outgoing routing audit trail;
- `data/wechat-bridge-failed.jsonl`: failed messages for investigation/retry.

## Important limitation

This is Windows desktop automation, not an official WeChat API. It must run on the Windows machine where WeChat is logged in. A Linux VPS cannot directly read or operate that desktop WeChat window. WeChat or wxauto4 upgrades may require compatibility updates.

The bridge can route replies back to the exact configured chat and retain the sender identity in group conversations. Native WeChat member IDs, native @ mentions, and other rich message features are only available when the installed wxauto4/WeChat version exposes them; the code falls back to deterministic local identifiers and textual `@name` replies instead of inventing unavailable native IDs.
