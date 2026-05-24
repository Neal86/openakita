"""Tests for backup/restore sandbox + overwrite policy (EX-P1-1).

Covers:

* ``dest_dir`` (create) and ``target_db_path`` (restore) path-traversal
  sandbox enforcement.
* 409 ``target_already_exists`` guard with ``overwrite=true``
  confirmation flag.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from finance_auto_backend.db import FinanceAutoDB
from finance_auto_backend.routes import FinanceAutoService
from finance_auto_backend.services import backup_restore as br


PASSPHRASE = "correct-horse-battery-staple"


@pytest.fixture()
def service_and_sandbox(tmp_path: Path):
    """Return a fully-initialised FinanceAutoService whose backup
    sandbox is rooted under tmp_path (no env-var pollution, no
    home-dir writes during the test run)."""
    db_path = tmp_path / "finance_auto.sqlite"
    sandbox = tmp_path / "backup_sandbox"
    db = FinanceAutoDB(db_path)
    asyncio.run(db.init())
    service = FinanceAutoService(db)
    svc = br.BackupRestoreService(service, allowed_root=sandbox)
    yield service, svc, sandbox, db
    asyncio.run(db.close())


# ---------------------------------------------------------------------------
# EX-P1-1 — sandbox + overwrite
# ---------------------------------------------------------------------------


def test_create_backup_inside_sandbox_succeeds(service_and_sandbox) -> None:
    _service, svc, sandbox, _db = service_and_sandbox
    inside = sandbox / "nested"
    out = asyncio.run(
        svc.create_backup(passphrase=PASSPHRASE, dest_dir=inside)
    )
    assert out["status"] == "completed"
    assert Path(out["backup_path"]).exists()
    assert sandbox in Path(out["backup_path"]).resolve().parents


def test_create_backup_path_traversal_rejected(service_and_sandbox) -> None:
    _service, svc, sandbox, _db = service_and_sandbox
    # ``../../etc`` resolves above the sandbox — must 403, no I/O.
    escape = sandbox / ".." / ".." / "etc"
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            svc.create_backup(passphrase=PASSPHRASE, dest_dir=escape)
        )
    assert exc_info.value.status_code == 403
    detail = exc_info.value.detail
    assert detail["error"] == "path_outside_sandbox"
    assert detail["field"] == "dest_dir"


def test_restore_target_existing_without_overwrite_returns_409(
    service_and_sandbox,
) -> None:
    _service, svc, sandbox, _db = service_and_sandbox
    backup = asyncio.run(svc.create_backup(passphrase=PASSPHRASE))
    # Pre-create a victim file inside the sandbox.
    victim = sandbox / "victim.sqlite"
    victim.write_bytes(b"do-not-clobber")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            svc.restore_backup(
                backup_id=backup["id"],
                passphrase=PASSPHRASE,
                target_db_path=victim,
                overwrite=False,
            )
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error"] == "target_already_exists"
    # Victim file UNTOUCHED.
    assert victim.read_bytes() == b"do-not-clobber"


def test_restore_target_existing_with_overwrite_clobbers(
    service_and_sandbox,
) -> None:
    _service, svc, sandbox, _db = service_and_sandbox
    backup = asyncio.run(svc.create_backup(passphrase=PASSPHRASE))
    victim = sandbox / "victim.sqlite"
    victim.write_bytes(b"old-content")
    result = asyncio.run(
        svc.restore_backup(
            backup_id=backup["id"],
            passphrase=PASSPHRASE,
            target_db_path=victim,
            overwrite=True,
        )
    )
    assert result["ok"] is True
    # File was overwritten with the snapshot DB bytes — they start with
    # the standard SQLite magic header.
    assert victim.read_bytes().startswith(b"SQLite format 3")


def test_restore_target_outside_sandbox_rejected(
    service_and_sandbox, tmp_path: Path
) -> None:
    _service, svc, _sandbox, _db = service_and_sandbox
    backup = asyncio.run(svc.create_backup(passphrase=PASSPHRASE))
    # Path outside both sandbox AND the live DB path → 403.
    escape = tmp_path / "elsewhere" / "evil.sqlite"
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            svc.restore_backup(
                backup_id=backup["id"],
                passphrase=PASSPHRASE,
                target_db_path=escape,
                overwrite=False,
            )
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "path_outside_sandbox"
