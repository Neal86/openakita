"""Tests for :mod:`openakita.runtime.session_bridge`.

P-RC-1 commit 1. The bridge is a single dependency-injection seam:
the v2 runtime asks ``get_org_id_for_session(session_key)``, the
gateway (registered via ``register_session_org_lookup``) answers
with the org bound to that session. These tests cover the four
scenarios the continuation plan calls out:

* bound       -> registered lookup returns ``"org_abc"``
* unbound     -> registered lookup returns ``None``
* unknown     -> registered lookup raises (treated as ``None``)
* cancelled   -> no lookup registered at all (process-wide default)

Plus a few defensive cases (empty session key, non-string return).
"""

from __future__ import annotations

import pytest

from openakita.runtime.session_bridge import (
    SessionOrgLookup,
    get_org_id_for_session,
    register_session_org_lookup,
    reset_session_org_lookup,
)


@pytest.fixture(autouse=True)
def _clean_lookup() -> None:
    """Make sure each test starts and ends with no registered lookup."""
    reset_session_org_lookup()
    yield
    reset_session_org_lookup()


def test_returns_org_id_when_lookup_resolves_session() -> None:
    """Bound case: lookup returns a real org id."""
    def lookup(session_key: str) -> str | None:
        return "org_abc" if session_key == "telegram:chat:user" else None

    register_session_org_lookup(lookup)
    assert get_org_id_for_session("telegram:chat:user") == "org_abc"


def test_returns_none_when_session_is_unbound() -> None:
    """Unbound case: session exists but no org binding."""
    def lookup(session_key: str) -> str | None:
        return None

    register_session_org_lookup(lookup)
    assert get_org_id_for_session("feishu:chat:user") is None


def test_returns_none_when_lookup_raises() -> None:
    """Unknown-session case: lookup raises (e.g. store crashed) -> None."""
    def lookup(session_key: str) -> str | None:
        raise RuntimeError("session store unavailable")

    register_session_org_lookup(lookup)
    assert get_org_id_for_session("wecom:chat:user") is None


def test_returns_none_when_no_lookup_registered() -> None:
    """Cancelled / pre-registration case: never call into nothing."""
    # reset_session_org_lookup already cleared the slot via the fixture.
    assert get_org_id_for_session("dingtalk:chat:user") is None


def test_returns_none_for_empty_session_key() -> None:
    """Defensive: empty key cannot map to an org."""
    def lookup(session_key: str) -> str | None:
        return "org_should_not_be_returned"

    register_session_org_lookup(lookup)
    assert get_org_id_for_session("") is None


def test_returns_none_when_lookup_returns_non_string() -> None:
    """Defensive: lookup must hand back a string; anything else -> None."""
    def lookup(session_key: str) -> object:  # type: ignore[return-value]
        return 12345  # bogus type

    register_session_org_lookup(lookup)  # type: ignore[arg-type]
    assert get_org_id_for_session("qq:chat:user") is None


def test_register_overwrites_previous_lookup() -> None:
    """Last-writer-wins -- the gateway can be re-constructed in tests."""
    register_session_org_lookup(lambda key: "first")
    register_session_org_lookup(lambda key: "second")
    assert get_org_id_for_session("sess") == "second"


def test_protocol_isinstance_check() -> None:
    """The runtime-checkable Protocol accepts a plain callable."""
    def lookup(session_key: str) -> str | None:
        return None

    assert isinstance(lookup, SessionOrgLookup)
