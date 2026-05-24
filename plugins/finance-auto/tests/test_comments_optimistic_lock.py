"""Unit tests for the comments table optimistic-lock fix (P2-6).

§2.4 of the M3 audit reported that ``ReviewWorkflowService.resolve_comment``
declared a ``version`` column on the ``comments`` table and bumped it
via ``SET version=version+1`` but failed to add ``WHERE id=? AND
version=?`` to the UPDATE — so concurrent resolves silently raced
last-write-wins instead of producing a 409 contention error like every
other Part Infra C3 table.

These tests exercise the service method directly (no HTTP route yet
exposes comment.resolve) using an in-process SQLite database.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from finance_auto_backend.db import FinanceAutoDB
from finance_auto_backend.models import CommentCreateRequest, OrganizationCreate
from finance_auto_backend.routes import FinanceAutoService
from finance_auto_backend.services.collaboration import CollaborationService
from finance_auto_backend.services.review_workflow import ReviewWorkflowService


async def _bootstrap(tmp_path: Path):
    db_path = tmp_path / "comments.sqlite"
    db = FinanceAutoDB(db_path)
    await db.init()
    service = FinanceAutoService(db)
    org = await service.create_org(
        OrganizationCreate(name="评论锁测试", code="COMM-LOCK-001")
    )
    collab = CollaborationService(db.conn)
    review = ReviewWorkflowService(db.conn, collab)
    return db, service, org.id, review


async def _make_comment(
    review: ReviewWorkflowService, *, org_id: str
) -> int:
    payload = CommentCreateRequest(
        body="测试评论 — 用于验证乐观锁",
        kind="general",
        author_id="local",
    )
    comment = await review.add_comment(
        org_id=org_id, cell_id="cell_dummy", report_id=None,
        workflow_id=None, payload=payload,
    )
    return comment.id


@pytest.mark.asyncio
async def test_resolve_comment_legacy_path_still_works(tmp_path: Path):
    """No expected_version → legacy idempotent behaviour preserved so the
    M2 UI which hasn't been updated yet still resolves cleanly."""
    db, _svc, org_id, review = await _bootstrap(tmp_path)
    try:
        cid = await _make_comment(review, org_id=org_id)
        # First resolve flips resolved=1 and bumps version 1 → 2.
        resolved = await review.resolve_comment(
            comment_id=cid, actor_id="local",
        )
        assert resolved.resolved is True
        assert resolved.version == 2
        assert resolved.resolved_by == "local"
        # Idempotent on a second call — already resolved.
        again = await review.resolve_comment(
            comment_id=cid, actor_id="local",
        )
        assert again.version == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_resolve_comment_rejects_stale_expected_version(tmp_path: Path):
    """expected_version mismatch → HTTPException 409 with structured
    detail; the comment must remain unresolved."""
    db, _svc, org_id, review = await _bootstrap(tmp_path)
    try:
        cid = await _make_comment(review, org_id=org_id)
        # Comment was inserted at version=1 (per add_comment INSERT).
        # Pretend caller thinks it's still at version 99 → should 409.
        with pytest.raises(HTTPException) as exc_info:
            await review.resolve_comment(
                comment_id=cid, actor_id="local",
                expected_version=99,
            )
        assert exc_info.value.status_code == 409
        detail = exc_info.value.detail
        assert detail["error"] == "version_conflict"
        assert detail["expected_version"] == 99
        assert detail["current_version"] == 1

        # Comment is still unresolved + still at v1.
        async with db.conn.execute(
            "SELECT resolved, version FROM comments WHERE id=?", (cid,),
        ) as cur:
            row = await cur.fetchone()
        assert row["resolved"] == 0
        assert row["version"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_resolve_comment_accepts_matching_expected_version(tmp_path: Path):
    """Pass expected_version equal to the live version → succeeds + bumps."""
    db, _svc, org_id, review = await _bootstrap(tmp_path)
    try:
        cid = await _make_comment(review, org_id=org_id)
        resolved = await review.resolve_comment(
            comment_id=cid, actor_id="local",
            expected_version=1,
        )
        assert resolved.resolved is True
        assert resolved.version == 2
    finally:
        await db.close()
