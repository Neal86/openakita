from __future__ import annotations

import asyncio
import logging
import sys

try:
    from . import connector
    from .config_service import CONFIG_PATH, LOG_PATH, ensure_app_dir
except ImportError:
    import connector  # type: ignore
    from config_service import CONFIG_PATH, LOG_PATH, ensure_app_dir  # type: ignore


def main() -> None:
    ensure_app_dir()
    connector.CONFIG_PATH = CONFIG_PATH
    connector.LOG_PATH = LOG_PATH
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
    )
    try:
        asyncio.run(connector.run())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
