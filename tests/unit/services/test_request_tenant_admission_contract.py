"""The tenant the caller presented is the tenant Core is asked with.

The previous slice made `CoreIntegrationService` refuse a read without tenant
authority, and proved it by handing authority to a constructor in a test. That
proved the boundary and not the path: the only production constructor,
`build_stateful_input_service`, passed nothing, so outside tests the authority
was always None and every production Core read would have raised.

These tests cover the pieces of that path at unit level -- header resolution,
the factory's wiring, and the refusal when authority is absent.

They are not the request-path proof, and an earlier version of this docstring
claimed more than they deliver. Each builds a stand-in request, manages its own
context tokens, or reads source text; all of that can pass while the real path
is broken. The proof that a request actually carries its tenant to Core lives
in `tests/unit/api/test_tenant_admission_request_path.py`, which drives the
real application over HTTP.
"""

from __future__ import annotations

import pytest

from app.observability import resolve_tenant_id, tenant_id_var
from app.services.core_tenant_authority import TENANT_HEADER, MissingTenantAuthorityError


class _Request:
    """Minimal stand-in exposing only what the resolver reads."""

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


class TestResolvingTheTenantFromTheRequest:
    def test_the_presented_tenant_is_carried_unchanged(self) -> None:
        assert resolve_tenant_id(_Request({"X-Tenant-Id": "tenant-sg"})) == "tenant-sg"

    def test_an_absent_tenant_stays_absent(self) -> None:
        """The neighbouring resolvers synthesise a value when the header is
        missing, because an invented correlation id costs nothing. An invented
        tenant is a cross-tenant read, so absence must survive."""

        assert resolve_tenant_id(_Request({})) == ""

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    def test_a_blank_tenant_is_absent_not_a_value(self, blank: str) -> None:
        assert resolve_tenant_id(_Request({"X-Tenant-Id": blank})) == ""

    def test_no_generated_fallback_appears(self) -> None:
        """Guards the specific mistake of copying resolve_request_id, whose
        fallback shape (`req_<hex>`) would silently become a tenant."""

        resolved = resolve_tenant_id(_Request({}))
        assert not resolved.startswith(("req_", "corr_", "tenant_"))


class TestTheFactoryCarriesTheAdmittedTenant:
    @staticmethod
    def _core_service():
        from app.core.config import get_settings
        from app.services.portfolio_source_service import build_stateful_input_service

        return build_stateful_input_service(settings=get_settings())._core_service

    def test_a_request_with_a_tenant_reaches_core_with_it(self) -> None:
        token = tenant_id_var.set("tenant-sg")
        try:
            headers = self._core_service()._core_headers(operation="GET /test")
            assert headers[TENANT_HEADER] == "tenant-sg"
        finally:
            tenant_id_var.reset(token)

    def test_a_request_without_a_tenant_is_refused_not_defaulted(self) -> None:
        """The production failure mode. Before this slice the factory passed
        nothing and every read raised; the fix must make a genuine request work
        WITHOUT making a tenant-less one silently succeed."""

        token = tenant_id_var.set("")
        try:
            with pytest.raises(MissingTenantAuthorityError):
                self._core_service()._core_headers(operation="GET /portfolios/analytics")
        finally:
            tenant_id_var.reset(token)

    def test_the_middleware_resets_every_context_variable_it_sets(self) -> None:
        """Symmetry check on the middleware's own source: every set has a reset.

        Corrected claim. This previously said an unreset tenant would leak the
        previous caller's authority into the next request. That is not true of
        this middleware, and the request-path tests in
        `tests/unit/api/test_tenant_admission_request_path.py` demonstrate it:
        deleting the reset leaves them all green, because Starlette's
        `BaseHTTPMiddleware` runs the handler in its own task and asyncio copies
        the context per task, so the value never escapes the request that set it.

        The check is still worth keeping, for what it actually is -- a symmetry
        rule on context handling, which would become load-bearing if this ever
        moved to a pure-ASGI middleware that set the variable in the caller's
        own context. It is not evidence of tenant isolation, and it is no longer
        described as such."""

        from pathlib import Path

        source = (Path(__file__).resolve().parents[3] / "app" / "observability.py").read_text(encoding="utf-8")

        for variable in ("correlation_id_var", "request_id_var", "trace_id_var", "tenant_id_var"):
            assert f"{variable}.set(" in source, f"{variable} is never set"
            assert f"{variable}.reset(" in source, (
                f"{variable} is set without a matching reset. This middleware isolates "
                "requests through per-task context copying rather than through this "
                "reset, so the symmetry is hygiene, not the isolation guarantee."
            )

    def test_one_request_tenant_does_not_survive_into_the_next(self) -> None:
        """Set then reset restores the refusal, at the unit level.

        Corrected claim: this does not prove the middleware's reset is
        load-bearing. It exercises ContextVar semantics with tokens this test
        owns, which would hold whatever the middleware did. The request-path
        proof lives in `tests/unit/api/test_tenant_admission_request_path.py`,
        where two tenants are genuinely in flight and each reaches Core under
        its own.

        What it does show is worth keeping: once authority is out of scope, the
        very next read is refused rather than falling back to anything."""

        first = tenant_id_var.set("tenant-a")
        assert self._core_service()._core_headers(operation="GET /x")[TENANT_HEADER] == "tenant-a"
        tenant_id_var.reset(first)

        with pytest.raises(MissingTenantAuthorityError):
            self._core_service()._core_headers(operation="GET /x")
