from __future__ import annotations

from typing import Any

from .executor import WindowsCommandExecutor


def preview_focus_resource(
    executor: WindowsCommandExecutor,
    resource_id: str,
) -> dict[str, Any]:
    """Bring one discovered resource to the foreground for user verification.

    This is an operator-side preview action, not an Agent capability. It does
    not require or mutate an Agent grant and intentionally supports only focus
    / tab activation. All destructive or input actions continue to pass through
    the normal grant authorization path.
    """
    resource = executor._resource(resource_id)  # noqa: SLF001 - same package helper
    automation = str(resource.get("automation") or "")
    kind = str(resource.get("kind") or "")

    if kind == "browser_tab" and automation == "cdp":
        tab_id = str(resource.get("tab_id") or "")
        if not tab_id:
            raise RuntimeError("browser tab is no longer available")
        executor._cdp_command(  # noqa: SLF001 - reuse validated CDP target resolution
            resource,
            "Target.activateTarget",
            {"targetId": tab_id},
        )
        return {
            "focused": resource_id,
            "scope": "browser_tab",
            "automation": "cdp",
        }

    executor._select_uia_tab(resource)  # noqa: SLF001 - exact UIA tab if present
    executor._focus(int(resource.get("hwnd") or 0))  # noqa: SLF001 - Windows foreground helper
    return {
        "focused": resource_id,
        "scope": "browser_tab" if kind == "browser_tab" else "window",
        "automation": automation or "uia",
    }
