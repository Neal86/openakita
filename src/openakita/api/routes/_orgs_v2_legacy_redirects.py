"""308 Permanent Redirect shim for the P-RC-3 Group A routes.

Group A (9 endpoints under ``/api/v2/orgs[/...]`` shipped in
P-RC-3, backed by ``runtime.orgs.JsonOrgStore``) relocated to
``/api/v2/orgs-spec[/...]`` in P-RC-9 P9.7a-2 so the bulk
P9.7 mint can claim the original namespace. See
``docs/revamp/P-RC-9-P9.7-DECISIONS.md`` D-1 (R3 LOCKED) for
the reconciliation decision; PLAN ADR-0012 (no-shim under v1)
is relaxed only for this explicit one-window redirect.

For the v2.0.x line, every original Group A path keeps
responding with a **308 Permanent Redirect** to the
corresponding ``/api/v2/orgs-spec/...`` target. 308 preserves
both HTTP method and request body (unlike 301/302), so a
``POST /api/v2/orgs/templates/{id}/instantiate`` continues to
work end-to-end through the shim. Query strings are preserved
verbatim. This shim is **removed in v2.1.0** -- frontend
rewiring lands in P-RC-9 P9.8 caller migration.

ADR refs: ADR-0011 (no new Protocol; shim is a thin router);
ADR-0012 (one-window relaxation for redirect window only).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

__all__ = ["router"]


_SPEC_PREFIX = "/api/v2/orgs-spec"


def _redirect(target_path: str, request: Request) -> Response:
    """Issue a 308 to ``target_path`` while preserving query string.

    We build the ``Response`` manually (rather than using
    :class:`fastapi.responses.RedirectResponse`) so the method
    + body of the original request are preserved -- 308 is the
    only redirect status code that mandates this on the client
    side, and most HTTP clients (including FastAPI's
    :class:`~fastapi.testclient.TestClient`) follow it by default.
    """
    qs = request.url.query
    location = f"{target_path}?{qs}" if qs else target_path
    return Response(status_code=308, headers={"Location": location})


router = APIRouter(prefix="/api/v2/orgs", tags=["v2:Group A 308 shim"])


# ---------------------------------------------------------------------------
# 8 CRUD endpoints + 1 SSE -- mirrors the inventory rows A1..A9.
# Methods listed explicitly so each shim row preserves the method
# of the original Group A route (308 keeps the method client-side).
# ---------------------------------------------------------------------------


@router.get("/templates", include_in_schema=False)
def _r_list_templates(request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/templates", request)


@router.get("/templates/{template_id}", include_in_schema=False)
def _r_get_template(template_id: str, request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/templates/{template_id}", request)


@router.post("/templates/{template_id}/instantiate", include_in_schema=False)
def _r_instantiate(template_id: str, request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/templates/{template_id}/instantiate", request)


@router.get("", include_in_schema=False)
def _r_list_orgs(request: Request) -> Response:
    return _redirect(_SPEC_PREFIX, request)


@router.post("", include_in_schema=False)
def _r_create_org(request: Request) -> Response:
    return _redirect(_SPEC_PREFIX, request)


@router.get("/{org_id}", include_in_schema=False)
def _r_get_org(org_id: str, request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/{org_id}", request)


@router.patch("/{org_id}", include_in_schema=False)
def _r_patch_org(org_id: str, request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/{org_id}", request)


@router.delete("/{org_id}", include_in_schema=False)
def _r_delete_org(org_id: str, request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/{org_id}", request)


@router.get("/{org_id}/stream", include_in_schema=False)
def _r_stream_org(org_id: str, request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/{org_id}/stream", request)
