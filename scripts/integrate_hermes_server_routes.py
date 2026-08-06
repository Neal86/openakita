#!/usr/bin/env python3
"""Integrate Hermes routes into the real FastAPI composition root."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src/openakita/api/server.py"

OLD_HELPER = '''def mount_hermes_execution_routes(app: FastAPI) -> None:
    """Mount Hermes APIs at their canonical public paths exactly once."""
    mounted = {getattr(route, "path", "") for route in app.routes}
    if "/api/hermes/nodes" not in mounted:
        hermes_paths = {getattr(route, "path", "") for route in hermes.router.routes}
        if "/ui" not in hermes_paths:
            hermes.router.include_router(hermes_ui.router)
        app.include_router(hermes.router, prefix="/api", tags=["Hermes"])
    if "/api/execution/instances" not in mounted:
        app.include_router(execution_instances.router)
    if "/v1/chat/completions" not in mounted:
        app.include_router(llm_gateway.router)
'''

NEW_HELPER = '''def mount_hermes_execution_routes(app: FastAPI) -> None:
    """Mount Hermes APIs at their canonical public paths exactly once."""
    if getattr(app.state, "_hermes_execution_routes_mounted", False):
        return
    hermes_paths = {
        getattr(route, "path", "") or getattr(route, "path_format", "")
        for route in hermes.router.routes
    }
    if "/ui" not in hermes_paths:
        hermes.router.include_router(hermes_ui.router)
    app.include_router(hermes.router, prefix="/api", tags=["Hermes"])
    app.include_router(execution_instances.router)
    app.include_router(llm_gateway.router)
    app.state._hermes_execution_routes_mounted = True
'''


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
    if OLD_HELPER in text:
        text = text.replace(OLD_HELPER, NEW_HELPER, 1)
    elif "def mount_hermes_execution_routes" not in text:
        if helper_marker not in text:
            raise RuntimeError("server helper marker missing")
        text = text.replace(helper_marker, "\n" + NEW_HELPER + helper_marker, 1)
    elif NEW_HELPER not in text:
        raise RuntimeError("unknown Hermes server helper layout")

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
