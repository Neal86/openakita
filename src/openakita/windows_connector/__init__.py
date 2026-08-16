"""Generic Windows Connector support for remote desktop/browser control."""

from .browser_adapter import install_browser_adapter
from .manager import windows_connector_manager
from .tools import WINDOWS_CONNECTOR_TOOLS, register_windows_connector_tools

register_windows_connector_tools()
install_browser_adapter()

__all__ = [
    "WINDOWS_CONNECTOR_TOOLS",
    "install_browser_adapter",
    "register_windows_connector_tools",
    "windows_connector_manager",
]
