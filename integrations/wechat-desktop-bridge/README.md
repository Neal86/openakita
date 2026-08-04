# OpenAkita Personal WeChat Desktop Bridge

This component runs on the same Windows computer as the logged-in WeChat desktop client. It listens only to configured group chats, forwards merged text messages to a selected OpenAkita Agent, and sends the Agent's final text back to the original group.

## Requirements

- Windows 10 or 11
- Python 3.11
- WeChat desktop already logged in
- OpenAkita CLI installed and working (`openakita run ...`)
- The target Agent already configured with its business rules, knowledge, skills, and MCP servers

The bridge contains no customer-service business rules. Order lookup, reply policy, escalation, working hours, and WMS access remain in the selected OpenAkita Agent.

## Start

1. Double-click `run.bat` once. It creates `.venv` and `config.yaml`.
2. Edit `config.yaml`:
   - replace `wechat.groups` with exact WeChat group names;
   - set `openakita.agent_id` to the Agent that handles customer service;
   - optionally add the account's displayed sender name to `ignore_senders`.
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

- group allowlist;
- ignored-sender list to prevent reply loops;
- persistent duplicate detection across restarts;
- short message merge window per group and sender;
- minimum send interval per group;
- OpenAkita timeout and non-zero exit handling;
- failed-message JSONL archive;
- UTF-8 file and subprocess handling.

## Runtime files

- `logs/wechat-bridge.log`: runtime log;
- `data/wechat-bridge-state.json`: duplicate state;
- `data/wechat-bridge-failed.jsonl`: failed messages for investigation/retry.

## Important limitation

This is Windows UI automation, not an official WeChat API. It must run on the Windows machine where WeChat is logged in. A Linux VPS cannot directly read or operate that desktop WeChat window. WeChat or wxauto4 upgrades may require compatibility updates.
