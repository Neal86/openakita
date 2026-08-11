"""Generic Windows Connector support for remote desktop/browser control."""

from .manager import windows_connector_manager
from .tools import WINDOWS_CONNECTOR_TOOLS, register_windows_connector_tools

register_windows_connector_tools()

__all__ = [
    "WINDOWS_CONNECTOR_TOOLS",
    "register_windows_connector_tools",
    "windows_connector_manager",
]
