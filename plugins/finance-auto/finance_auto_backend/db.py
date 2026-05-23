"""SQLite connection helper for finance-auto (WAL mode on, M1 W1).

Why a tiny module instead of an ORM?
* M1 W1 needs five tables and ~5 endpoints — pulling in SQLAlchemy would
  triple the code we have to read.
* We mirror ``plugins/fin-pulse``'s pattern (single ``aiosqlite.Connection``
  cached on the plugin instance, WAL + ``synchronous=NORMAL`` PRAGMAs at
  connect time) so the operational behaviour is consistent with the rest of
  the host.

The encryption ``_encrypted_payload BLOB`` columns are present in the schema
but always written as ``NULL`` in M1 W1 — M1 W2's KeyManager will populate
them via a follow-up migration that simply re-encrypts the cleartext columns.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from .schema import SCHEMA_SQL, SCHEMA_VERSION

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


class FinanceAutoDB:
    """Thin wrapper around ``aiosqlite.Connection`` with init/close lifecycle.

    Usage::

        db = FinanceAutoDB(Path("data/plugin_data/finance-auto/finance.sqlite"))
        await db.init()
        async with db.conn.execute("SELECT 1") as cur:
            ...
        await db.close()

    All connections enable WAL mode + ``synchronous=NORMAL`` for concurrent
    read while ingest writes (M1 W1 explicit ask from product).
    """

    def __init__(self, db_path: Path | str):
        self._db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None
        self._init_lock = asyncio.Lock()
        self._ready = False

    @property
    def path(self) -> Path:
        return self._db_path

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("FinanceAutoDB.conn accessed before init()")
        return self._conn

    def is_ready(self) -> bool:
        return self._ready and self._conn is not None

    async def init(self) -> None:
        """Open the connection, enable WAL, and apply schema.

        Idempotent: calling it twice is a no-op. Concurrent callers are
        serialised by an ``asyncio.Lock`` so the bootstrap task and a fast
        first request cannot both race the PRAGMA dance.
        """
        async with self._init_lock:
            if self._ready and self._conn is not None:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(self._db_path)
            conn.row_factory = aiosqlite.Row
            # WAL + NORMAL for read-write concurrency (M1 W1 explicit ask).
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.executescript(SCHEMA_SQL)
            now = _utcnow_iso()
            await conn.execute(
                "INSERT INTO schema_version(component, version, applied_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(component) DO UPDATE SET version=excluded.version, "
                "applied_at=excluded.applied_at WHERE schema_version.version < excluded.version",
                ("finance_auto", SCHEMA_VERSION, now),
            )
            await conn.commit()
            self._conn = conn
            self._ready = True
            logger.info(
                "finance-auto: SQLite ready at %s (WAL, schema v%d)",
                self._db_path,
                SCHEMA_VERSION,
            )

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception as exc:
                logger.warning("finance-auto: SQLite close error: %s", exc)
            self._conn = None
        self._ready = False

    async def journal_mode(self) -> str:
        """Read back ``PRAGMA journal_mode`` for diagnostic / verification."""
        if self._conn is None:
            return "closed"
        async with self._conn.execute("PRAGMA journal_mode") as cur:
            row = await cur.fetchone()
            return row[0] if row else "unknown"


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
