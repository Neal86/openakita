"""DEPRECATED: 308 Permanent Redirect shim for legacy ``/api/v2/orgs[/...]`` paths.

This shim is scheduled for removal in OpenAkita 2.1.0. Only one route
(``POST /api/v2/orgs/templates/{id}/instantiate``) is still effective;
all other shim paths are now shadowed by the v2 runtime router. See
``_skip_items_rca_v11.md`` §3 for the full audit.

Frontend already calls the runtime endpoints directly. No external
consumers known. Removal is blocked only by the lack of a deprecation
window announcement.

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

# RFC 8594 / IETF draft-ietf-httpapi-deprecation-header headers added to
# every redirect response so HTTP clients and proxies can detect the
# upcoming removal of this shim. See RCA v11 §3 (Fix-G5).
_SUNSET_DATE = "2026-12-01"
_DEPRECATION_HEADERS: dict[str, str] = {
    "Deprecation": "true",
    "Sunset": _SUNSET_DATE,
    "Link": '</api/v2/orgs-spec>; rel="successor-version"',
}


def _redirect(target_path: str, request: Request) -> Response:
    """Issue a 308 to ``target_path`` while preserving query string.

    We build the ``Response`` manually (rather than using
    :class:`fastapi.responses.RedirectResponse`) so the method
    + body of the original request are preserved -- 308 is the
    only redirect status code that mandates this on the client
    side, and most HTTP clients (including FastAPI's
    :class:`~fastapi.testclient.TestClient`) follow it by default.

    Deprecation/Sunset/Link headers are added so callers can detect
    the upcoming removal in OpenAkita 2.1.0 (RCA v11 §3).
    """
    qs = request.url.query
    location = f"{target_path}?{qs}" if qs else target_path
    headers = {"Location": location, **_DEPRECATION_HEADERS}
    return Response(status_code=308, headers=headers)


router = APIRouter(prefix="/api/v2/orgs", tags=["v2:Group A 308 shim"])


# ---------------------------------------------------------------------------
# 8 CRUD endpoints + 1 SSE -- mirrors the inventory rows A1..A9.
# Methods listed explicitly so each shim row preserves the method
# of the original Group A route (308 keeps the method client-side).
# Every handler is annotated with ``deprecated=True`` so it shows up
# as deprecated in the OpenAPI schema (when ``include_in_schema`` is
# flipped on for audits) and so tooling that inspects the route table
# can surface the marker.
# ---------------------------------------------------------------------------


@router.get("/templates", include_in_schema=False, deprecated=True)
def _r_list_templates(request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/templates", request)


@router.get("/templates/{template_id}", include_in_schema=False, deprecated=True)
def _r_get_template(template_id: str, request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/templates/{template_id}", request)


@router.post(
    "/templates/{template_id}/instantiate",
    include_in_schema=False,
    deprecated=True,
)
def _r_instantiate(template_id: str, request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/templates/{template_id}/instantiate", request)


@router.get("", include_in_schema=False, deprecated=True)
def _r_list_orgs(request: Request) -> Response:
    return _redirect(_SPEC_PREFIX, request)


@router.post("", include_in_schema=False, deprecated=True)
def _r_create_org(request: Request) -> Response:
    return _redirect(_SPEC_PREFIX, request)


@router.get("/{org_id}", include_in_schema=False, deprecated=True)
def _r_get_org(org_id: str, request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/{org_id}", request)


@router.patch("/{org_id}", include_in_schema=False, deprecated=True)
def _r_patch_org(org_id: str, request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/{org_id}", request)


@router.delete("/{org_id}", include_in_schema=False, deprecated=True)
def _r_delete_org(org_id: str, request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/{org_id}", request)


@router.get("/{org_id}/stream", include_in_schema=False, deprecated=True)
def _r_stream_org(org_id: str, request: Request) -> Response:
    return _redirect(f"{_SPEC_PREFIX}/{org_id}/stream", request)
