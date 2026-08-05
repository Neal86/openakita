from __future__ import annotations

import asyncio
import sys


def main() -> None:
    if "--connector" in sys.argv:
        from connector import run

        asyncio.run(run())
        return

    from gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
