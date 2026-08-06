#!/usr/bin/env python3
"""Apply deterministic fixes for Hermes integration CI failures."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise RuntimeError(f"marker missing in {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    replace(
        "src/openakita/api/routes/hermes_ui.py",
        '@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)',
        '@router.get("/ui", response_class=HTMLResponse)',
    )
    replace(
        "src/openakita/hermes/hooks.py",
        '    normalized.setdefault("source", "hermes")\n',
        "",
    )
    replace(
        "src/openakita/hermes/hooks.py",
        '        setattr(Agent, "chat_with_session", chat_with_session)\n',
        '        Agent.chat_with_session = chat_with_session  # type: ignore[method-assign]\n',
    )
    replace(
        "src/openakita/hermes/hooks.py",
        '        setattr(Agent, "chat_with_session_stream", chat_with_session_stream)\n',
        '        Agent.chat_with_session_stream = chat_with_session_stream  # type: ignore[method-assign]\n',
    )
    replace(
        "src/openakita/api/routes/llm_gateway.py",
        "from pathlib import Path\nfrom typing import Any, AsyncIterator\n",
        "from collections.abc import AsyncIterator\nfrom pathlib import Path\nfrom typing import Any\n",
    )
    replace(
        "src/openakita/hermes/bindings.py",
        '    def from_dict(cls, data: dict[str, Any]) -> "AgentHermesBinding":\n',
        "    def from_dict(cls, data: dict[str, Any]) -> AgentHermesBinding:\n",
    )
    replace(
        "src/openakita/hermes/models.py",
        '    def from_dict(cls, data: dict[str, Any]) -> "HermesNode":\n',
        "    def from_dict(cls, data: dict[str, Any]) -> HermesNode:\n",
    )
    replace(
        "src/openakita/hermes/client.py",
        "from dataclasses import dataclass, field\nfrom typing import Any, AsyncIterator\n",
        "from collections.abc import AsyncIterator\nfrom dataclasses import dataclass, field\nfrom typing import Any\n",
    )
    replace(
        "src/openakita/hermes/client.py",
        "        async with httpx.AsyncClient(timeout=self.node.timeout_seconds) as client:\n            async with client.stream(\n",
        "        async with (\n            httpx.AsyncClient(timeout=self.node.timeout_seconds) as client,\n            client.stream(\n",
    )
    replace(
        "src/openakita/hermes/client.py",
        "                json=payload,\n            ) as response:\n",
        "                json=payload,\n            ) as response,\n        ):\n",
    )
    replace(
        "src/openakita/hermes/execution.py",
        "import json\nimport re\nimport threading\n",
        "import json\nimport re\nimport threading\nfrom collections.abc import Callable\n",
    )
    replace(
        "src/openakita/hermes/execution.py",
        "from pathlib import Path\nfrom typing import Any, Callable\n",
        "from pathlib import Path\nfrom typing import Any\n",
    )
    replace(
        "src/openakita/api/server.py",
        "    execution_instances,\n    feishu_onboard,\n    hermes,\n    hermes_ui,\n    llm_gateway,\n    files,\n    health,\n",
        "    execution_instances,\n    feishu_onboard,\n    files,\n    health,\n    hermes,\n    hermes_ui,\n",
    )
    replace(
        "src/openakita/api/server.py",
        "    inbox,\n    logs,\n",
        "    inbox,\n    llm_gateway,\n    logs,\n",
    )
    replace(
        "src/openakita/channels/adapters/wechat_desktop.py",
        "            first, last = rows[0], rows[-1]\n",
        "            last = rows[-1]\n",
    )
    replace(
        "src/openakita/wechat_desktop/connector_bundle/pair.py",
        "import json\n",
        "",
    )
    replace(
        "src/openakita/wechat_desktop/manager.py",
        "from datetime import UTC, datetime, timedelta\nfrom pathlib import Path\nfrom typing import Any, Awaitable, Callable\n",
        "from collections.abc import Awaitable, Callable\nfrom datetime import UTC, datetime, timedelta\nfrom pathlib import Path\nfrom typing import Any\n",
    )
    print("Hermes CI failures fixed")


if __name__ == "__main__":
    main()
