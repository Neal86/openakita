#!/usr/bin/env python3
"""Integrate Hermes routes into the real FastAPI composition root."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src/openakita/api/server.py"


def main() -> None:
    text = PATH.read_text("utf-8")

    import_marker = "    diagnostics,\n    feishu_onboard,\n"
    import_replacement = (
        "    diagnostics,\n"
        "    execution_instances,\n"
        "    feishu_onboard,\n"
        "    hermes,\n"
        "    hermes_ui,\n"
        "    llm_gateway,\n"
    )
    if "    execution_instances,\n" not in text:
        if import_marker not in text:
            raise RuntimeError("server route import marker missing")
        text = text.replace(import_marker, import_replacement, 1)

    helper_marker = "\ndef get_api_host_for_health_display(app_state: Any | None = None) -> str:\n"
    helper = '''\ndef mount_hermes_execution_routes(app: FastAPI) -> None:\n    \"\"\"Mount Hermes APIs at their canonical public paths exactly once.\"\"\"\n    mounted = {getattr(route, \"path\", \"\") for route in app.routes}\n    if \"/api/hermes/nodes\" not in mounted:\n        hermes_paths = {getattr(route, \"path\", \"\") for route in hermes.router.routes}\n        if \"/ui\" not in hermes_paths:\n            hermes.router.include_router(hermes_ui.router)\n        app.include_router(hermes.router, prefix=\"/api\", tags=[\"Hermes\"])\n    if \"/api/execution/instances\" not in mounted:\n        app.include_router(execution_instances.router)\n    if \"/v1/chat/completions\" not in mounted:\n        app.include_router(llm_gateway.router)\n\n'''
    if "def mount_hermes_execution_routes" not in text:
        if helper_marker not in text:
            raise RuntimeError("server helper marker missing")
        text = text.replace(helper_marker, helper + helper_marker, 1)

    mount_marker = '    app.include_router(agents.router, tags=["智能体"])\n'
    mount_replacement = mount_marker + "    mount_hermes_execution_routes(app)\n"
    if "    mount_hermes_execution_routes(app)\n" not in text:
        if mount_marker not in text:
            raise RuntimeError("server mount marker missing")
        text = text.replace(mount_marker, mount_replacement, 1)

    PATH.write_text(text, "utf-8")
    print("Hermes routes integrated into server.py")


if __name__ == "__main__":
    main()
