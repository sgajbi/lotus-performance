"""The tenant the caller presented is the tenant Core is asked with.

The previous slice made `CoreIntegrationService` refuse a read without tenant
authority, and proved it by handing authority to a constructor in a test. That
proved the boundary and not the path: the only production constructor,
`build_stateful_input_service`, passed nothing, so outside tests the authority
was always None and every production Core read would have raised.

These tests exercise the production path instead -- request header, through the
middleware's request-scoped variable, into the factory, out as the header Core
admits on.

The leak test is the one that matters. A stale correlation id mislabels a log
line; a stale tenant lets the next request read under the previous caller's
authority, and no downstream check would see it.
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
        """The guard for the bug I actually made.

        The test below proves that set/reset clears the value -- which is
        contextvar semantics, not evidence the middleware calls reset. I set
        the tenant token and omitted the reset, and no behavioural test could
        have caught it, because each test manages its own token.

        So this reads the middleware itself: every `<var>.set(` must have a
        matching `<var>.reset(`. An unreset tenant leaks the previous caller's
        authority into the next request."""

        from pathlib import Path

        source = (Path(__file__).resolve().parents[3] / "app" / "observability.py").read_text(encoding="utf-8")

        for variable in ("correlation_id_var", "request_id_var", "trace_id_var", "tenant_id_var"):
            assert f"{variable}.set(" in source, f"{variable} is never set"
            assert f"{variable}.reset(" in source, (
                f"{variable} is set but never reset; its value survives into the next request "
                "handled on the same context"
            )

    def test_one_request_tenant_does_not_survive_into_the_next(self) -> None:
        """Proves the middleware's reset is load-bearing.

        Setting and resetting mirrors what the request middleware does around
        `call_next`. If the reset were omitted, this would read `tenant-a`
        after that request finished -- the next caller reading under the
        previous caller's authority, invisibly."""

        first = tenant_id_var.set("tenant-a")
        assert self._core_service()._core_headers(operation="GET /x")[TENANT_HEADER] == "tenant-a"
        tenant_id_var.reset(first)

        with pytest.raises(MissingTenantAuthorityError):
            self._core_service()._core_headers(operation="GET /x")
