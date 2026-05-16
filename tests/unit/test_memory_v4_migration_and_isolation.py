"""Phase 0 + Phase 2b.1 单测。

覆盖：
1. ``test_v3_to_v4_split_legacy_to_pending``:
   v3 升 v4 时，lifecycle 后台合成（``source IN ('daily_consolidation',
   'experience_synthesis')``）的旧记忆从 ``legacy_quarantine`` 迁到
   ``pending_consolidation``，并写入 ``_memory_scope_audit``。
   真历史 v1/v2 旧数据（其他 source）继续留在 ``legacy_quarantine``。
2. ``test_lifecycle_extracted_item_lands_in_pending_when_tenant_unknown``:
   ``_save_extracted_item`` 拿不到 tenant 时落 ``pending_consolidation``，
   不再污染 ``legacy_quarantine``。
3. ``test_lifecycle_extracted_item_lands_in_user_when_tenant_known``:
   ``_save_extracted_item`` 拿到 tenant 时直接进对应租户的 ``user`` scope。
4. ``test_global_store_source_blocks_cross_user``:
   Phase 2b.1 — ``_GlobalStoreSource`` 必须按 owner_provider 透传的
   (user_id, workspace_id) 过滤，不能跨用户返回结果。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from openakita.memory.lifecycle import LifecycleManager
from openakita.memory.storage import _SCHEMA_VERSION, MemoryStorage
from openakita.memory.types import MemoryPriority, MemoryType, SemanticMemory
from openakita.memory.unified_store import UnifiedStore

# ----------------------------------------------------------------------
# 用 raw sqlite 造一个 v3 库，再让 MemoryStorage 读它触发 v3→v4 迁移
# ----------------------------------------------------------------------


def _build_v3_db_with_legacy_rows(
    db_path: Path,
    *,
    extra_turn_sessions: list[str] | None = None,
) -> dict[str, str]:
    """直接造一个 v3 schema 的 sqlite 数据库，预置两条 legacy_quarantine 记忆：

    - mem-lifecycle：``source='daily_consolidation'``，应被 v4 迁出。
    - mem-true-legacy：``source='manual'``，应继续留在 legacy_quarantine。

    可选 ``extra_turn_sessions`` 用于在 conversation_turns 里插入若干 session_id，
    模拟 v3 库中已有未抽取对话，验证 v4 backfill session_tenants 行为。

    返回 {"lifecycle_id": ..., "true_legacy_id": ...}。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE _schema_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.execute(
            "INSERT INTO _schema_meta(key, value) VALUES ('version', '3')"
        )
        conn.execute(
            """
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                priority TEXT NOT NULL,
                content TEXT NOT NULL,
                subject TEXT DEFAULT '',
                predicate TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                source TEXT DEFAULT '',
                source_episode_id TEXT DEFAULT '',
                importance_score REAL DEFAULT 0.5,
                confidence REAL DEFAULT 0.5,
                access_count INTEGER DEFAULT 0,
                last_accessed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                superseded_by TEXT,
                scope TEXT DEFAULT 'user',
                scope_owner TEXT DEFAULT '',
                user_id TEXT DEFAULT 'default',
                workspace_id TEXT DEFAULT 'default',
                agent_id TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                tool_calls TEXT,
                tool_results TEXT,
                has_tool_calls BOOLEAN DEFAULT FALSE,
                timestamp TEXT NOT NULL,
                token_estimate INTEGER,
                episode_id TEXT,
                extracted BOOLEAN DEFAULT FALSE,
                UNIQUE(session_id, turn_index)
            )
            """
        )
        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO memories
                (id, type, priority, content, source, importance_score, confidence,
                 created_at, updated_at, scope, scope_owner, user_id, workspace_id)
            VALUES (?, 'fact', 'long_term', 'lifecycle synthesized fact',
                    'daily_consolidation', 0.6, 0.7, ?, ?, 'legacy_quarantine', '',
                    'legacy', 'default')
            """,
            ("mem-lifecycle", now, now),
        )
        conn.execute(
            """
            INSERT INTO memories
                (id, type, priority, content, source, importance_score, confidence,
                 created_at, updated_at, scope, scope_owner, user_id, workspace_id)
            VALUES (?, 'fact', 'long_term', 'true legacy fact from v1 export',
                    'manual', 0.7, 0.8, ?, ?, 'legacy_quarantine', '',
                    'legacy', 'default')
            """,
            ("mem-true-legacy", now, now),
        )
        for idx, sess in enumerate(extra_turn_sessions or []):
            conn.execute(
                """
                INSERT INTO conversation_turns
                    (session_id, turn_index, role, content, timestamp, extracted)
                VALUES (?, 0, 'user', 'hello', ?, FALSE)
                """,
                (sess, now),
            )
        conn.commit()
    finally:
        conn.close()
    return {
        "lifecycle_id": "mem-lifecycle",
        "true_legacy_id": "mem-true-legacy",
    }


def test_v3_to_v4_split_legacy_to_pending(tmp_path: Path):
    db_path = tmp_path / "openakita.db"
    ids = _build_v3_db_with_legacy_rows(db_path)

    storage = MemoryStorage(db_path, _register=False)
    assert storage._get_schema_version() == _SCHEMA_VERSION

    lifecycle_row = storage.get_memory(ids["lifecycle_id"])
    legacy_row = storage.get_memory(ids["true_legacy_id"])
    assert lifecycle_row is not None
    assert legacy_row is not None

    # daily_consolidation 产物迁出到 pending_consolidation
    assert lifecycle_row["scope"] == "pending_consolidation"
    # 真历史 legacy 继续留在 legacy_quarantine
    assert legacy_row["scope"] == "legacy_quarantine"

    audit_rows = storage._conn.execute(
        "SELECT memory_id, old_scope, new_scope, migration_version, reason "
        "FROM _memory_scope_audit ORDER BY memory_id"
    ).fetchall()
    audit = {row[0]: row for row in audit_rows}
    # 只有 lifecycle 那条要审计
    assert ids["lifecycle_id"] in audit
    assert ids["true_legacy_id"] not in audit
    moved = audit[ids["lifecycle_id"]]
    assert moved[1] == "legacy_quarantine"
    assert moved[2] == "pending_consolidation"
    assert moved[3] == "v3_to_v4"
    assert moved[4] == "v3_to_v4_source_lifecycle"

    # session_tenants 表存在但为空（本测试没插任何 conversation_turns）
    cnt = storage._conn.execute("SELECT COUNT(*) FROM session_tenants").fetchone()[0]
    assert cnt == 0


def test_v3_to_v4_backfills_session_tenants_from_conversation_turns(tmp_path: Path):
    """v3→v4 升级时，conversation_turns 里出现过的 session_id 都应在
    session_tenants 中得到登记，避免老 unextracted turn 升级后被误落
    pending_consolidation。

    解析规则：
    - IM 通道 conversation_safe_id 形如 ``ns__chat__user[__thread]`` →
      取第 3 段作 user_id；
    - 桌面 / CLI 形如 ``YYYYMMDD_HHMMSS_xxx`` 单段 → default。
    """
    db_path = tmp_path / "openakita.db"
    _build_v3_db_with_legacy_rows(
        db_path,
        extra_turn_sessions=[
            "telegram__chat-100__alice",
            "telegram__chat-200__bob__thread-1",
            "20251115_120000_abc12345",          # desktop CLI 单段
            "feishu__group-7__default",           # IM 但 user 段是 default
            "feishu__group-9__anonymous",         # 占位身份
            "",                                   # 空 session_id（不应入表）
        ],
    )

    storage = MemoryStorage(db_path, _register=False)

    rows = storage._conn.execute(
        "SELECT session_id, user_id, workspace_id FROM session_tenants "
        "ORDER BY session_id"
    ).fetchall()
    mapping = {sid: (u, w) for sid, u, w in rows}

    # IM 通道里 user 段是真实身份的 → 取出来
    assert mapping["telegram__chat-100__alice"] == ("alice", "default")
    assert mapping["telegram__chat-200__bob__thread-1"] == ("bob", "default")
    # IM 但 user 段是 default / anonymous → 降级为 default
    assert mapping["feishu__group-7__default"] == ("default", "default")
    assert mapping["feishu__group-9__anonymous"] == ("default", "default")
    # desktop CLI 单段 → default
    assert mapping["20251115_120000_abc12345"] == ("default", "default")
    # 空 session_id 不入表
    assert "" not in mapping


def test_v3_to_v4_backfill_is_idempotent(tmp_path: Path):
    """重复打开同一个已迁移到 v4 的库不应再次 backfill 或动数据。"""
    db_path = tmp_path / "openakita.db"
    _build_v3_db_with_legacy_rows(
        db_path, extra_turn_sessions=["telegram__a__alice"]
    )

    s1 = MemoryStorage(db_path, _register=False)
    rows_before = s1._conn.execute(
        "SELECT session_id, user_id, last_updated_at FROM session_tenants"
    ).fetchall()
    s1.close()

    # 再次打开（已经是 v4，不会再走 migration）
    s2 = MemoryStorage(db_path, _register=False)
    rows_after = s2._conn.execute(
        "SELECT session_id, user_id, last_updated_at FROM session_tenants"
    ).fetchall()
    assert rows_before == rows_after


# ----------------------------------------------------------------------
# Lifecycle 抽取产物落桶测试（不真正调 LLM，直接走 _save_extracted_item）
# ----------------------------------------------------------------------


def _make_lifecycle(tmp_path: Path) -> tuple[LifecycleManager, UnifiedStore]:
    store = UnifiedStore(db_path=tmp_path / "memory.db", backend_type="fts5")
    lifecycle = LifecycleManager(
        store=store,
        extractor=None,
        identity_dir=tmp_path / "identity",
    )
    return lifecycle, store


def test_lifecycle_extracted_item_lands_in_pending_when_tenant_unknown(tmp_path: Path):
    lifecycle, store = _make_lifecycle(tmp_path)

    item = {
        "type": "FACT",
        "content": "User prefers dark mode for the dashboard",
        "subject": "user",
        "predicate": "theme",
        "importance": 0.55,
    }
    lifecycle._save_extracted_item(item, tenant=None)

    legacy = store.load_all_memories(
        scope="legacy_quarantine",
        scope_owner="",
        user_id="legacy",
        workspace_id=None,
        include_inactive=True,
    )
    pending = store.load_all_memories(
        scope="pending_consolidation",
        scope_owner="",
        user_id=None,
        workspace_id=None,
        include_inactive=True,
    )
    assert legacy == []
    assert len(pending) == 1
    assert pending[0].user_id == "pending"
    assert pending[0].scope == "pending_consolidation"


def test_lifecycle_extracted_item_lands_in_user_when_tenant_known(tmp_path: Path):
    lifecycle, store = _make_lifecycle(tmp_path)

    item = {
        "type": "PREFERENCE",
        "content": "User wants concise commit messages",
        "subject": "user",
        "predicate": "commit_style",
        "importance": 0.62,
    }
    lifecycle._save_extracted_item(item, tenant=("alice", "proj-a"))

    visible = store.load_all_memories(
        scope="user",
        scope_owner="",
        user_id="alice",
        workspace_id="proj-a",
    )
    other_user = store.load_all_memories(
        scope="user",
        scope_owner="",
        user_id="bob",
        workspace_id="proj-a",
    )
    pending = store.load_all_memories(
        scope="pending_consolidation",
        scope_owner="",
        user_id=None,
        workspace_id=None,
        include_inactive=True,
    )
    assert len(visible) == 1
    assert visible[0].user_id == "alice"
    assert visible[0].workspace_id == "proj-a"
    assert other_user == []
    assert pending == []


def test_lifecycle_resolve_tenant_accepts_registered_default(tmp_path: Path):
    """desktop / CLI 单用户场景：session_tenants 登记 default 是合法身份，
    不能被 lifecycle 误判为共享桶而拒绝。"""
    lifecycle, store = _make_lifecycle(tmp_path)
    store.upsert_session_tenant("sess-desktop", "default", "default")

    tenant = lifecycle._resolve_tenant_for_session("sess-desktop")
    assert tenant == ("default", "default")

    item = {
        "type": "FACT",
        "content": "Desktop single-user fact",
        "subject": "user",
        "predicate": "city",
        "importance": 0.55,
    }
    lifecycle._save_extracted_item(item, tenant=tenant)

    visible = store.load_all_memories(
        scope="user", scope_owner="", user_id="default", workspace_id="default"
    )
    pending = store.load_all_memories(
        scope="pending_consolidation", scope_owner="", user_id=None, workspace_id=None,
        include_inactive=True,
    )
    assert len(visible) == 1
    assert visible[0].content == "Desktop single-user fact"
    assert pending == []


def test_lifecycle_resolve_tenant_rejects_placeholder_identities(tmp_path: Path):
    """anonymous / legacy / system / 空 是显式占位身份，不能当成有效归属。"""
    lifecycle, store = _make_lifecycle(tmp_path)
    for placeholder in ("anonymous", "legacy", "system"):
        store.upsert_session_tenant(f"sess-{placeholder}", placeholder, "default")
        assert lifecycle._resolve_tenant_for_session(f"sess-{placeholder}") is None
    # 表里没登记的 session：同样返回 None
    assert lifecycle._resolve_tenant_for_session("sess-unknown") is None


# ----------------------------------------------------------------------
# Phase 2b.1: _GlobalStoreSource 跨用户检索过滤
# ----------------------------------------------------------------------


class _FakeStore:
    """轻量假 store，捕获 search_semantic 调用并按 user_id 隔离返回。"""

    def __init__(self) -> None:
        self.last_kwargs: dict | None = None
        self._data = {
            ("alice", "proj-a"): [
                SemanticMemory(
                    type=MemoryType.FACT,
                    priority=MemoryPriority.LONG_TERM,
                    content="alice secret note",
                )
            ],
            ("bob", "proj-a"): [
                SemanticMemory(
                    type=MemoryType.FACT,
                    priority=MemoryPriority.LONG_TERM,
                    content="bob secret note",
                )
            ],
        }

    def search_semantic(self, query, *, limit=8, scope=None, scope_owner=None,
                        user_id=None, workspace_id=None, **_):
        self.last_kwargs = {
            "query": query,
            "limit": limit,
            "scope": scope,
            "scope_owner": scope_owner,
            "user_id": user_id,
            "workspace_id": workspace_id,
        }
        return list(self._data.get((user_id, workspace_id), []))


@pytest.mark.asyncio
async def test_global_store_source_blocks_cross_user():
    from openakita.agents.factory import _GlobalStoreSource

    store = _FakeStore()

    src_alice = _GlobalStoreSource(store, lambda: ("alice", "proj-a"))
    out_alice = await src_alice.retrieve("anything", limit=5)
    assert len(out_alice) == 1
    assert "alice secret note" in out_alice[0]["content"]
    assert store.last_kwargs["user_id"] == "alice"
    assert store.last_kwargs["workspace_id"] == "proj-a"
    assert store.last_kwargs["scope"] == "user"

    src_bob = _GlobalStoreSource(store, lambda: ("bob", "proj-a"))
    out_bob = await src_bob.retrieve("anything", limit=5)
    assert len(out_bob) == 1
    assert "bob secret note" in out_bob[0]["content"]

    # 共享 / 占位身份必须直接拒绝，不能裸跨用户查
    for owner in [("default", "default"), ("anonymous", "default"),
                  ("", "default"), ("legacy", "default"), ("system", "default")]:
        store.last_kwargs = None
        src = _GlobalStoreSource(store, lambda owner=owner: owner)
        out = await src.retrieve("anything", limit=5)
        assert out == []
        assert store.last_kwargs is None
