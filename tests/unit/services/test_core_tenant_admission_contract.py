"""A Core read carries the caller's tenant, or it does not happen.

lotus-core's ingress is fail-closed: every protected route answers
`401 TENANT_CONTEXT_REQUIRED` without a valid `X-Tenant-Id`. These tests fix
the behaviour this service must have on the near side of that contract, and
the one it must never have -- supplying a tenant of its own.

The failure being guarded is not "the Core call 401s". That is merely visible.
It is that a service able to default a tenant can read one tenant's data on
behalf of another, and the request would succeed.
"""

from __future__ import annotations

import pytest

from app.services.core_integration_service import CoreIntegrationService
from app.services.core_tenant_authority import (
    TENANT_HEADER,
    MissingTenantAuthorityError,
    TenantAuthority,
    require_tenant_authority,
)


class TestTenantAuthority:
    def test_a_blank_tenant_is_an_absent_tenant(self) -> None:
        """An empty header is not a weaker tenant; it is no tenant, and Core
        treats it as such. Representing it as a value would let an absent
        tenant travel as though it were present."""

        for blank in ("", "   ", "\t"):
            with pytest.raises(ValueError, match="non-empty"):
                TenantAuthority(tenant_id=blank)

    def test_a_padded_tenant_is_a_different_tenant(self) -> None:
        """Core compares the header exactly, so ` tenant-sg ` is not
        `tenant-sg` there. Silently stripping it here would make this service
        disagree with the authority it is quoting."""

        with pytest.raises(ValueError, match="whitespace"):
            TenantAuthority(tenant_id=" tenant-sg ")

    def test_the_authority_travels_as_the_header_core_admits_on(self) -> None:
        assert TenantAuthority(tenant_id="tenant-sg").headers() == {TENANT_HEADER: "tenant-sg"}

    def test_authority_cannot_be_rewritten_after_admission(self) -> None:
        """Whose data is being read is decided once. A mutable authority means
        a computation can change tenant midway, which no downstream check would
        see."""

        authority = TenantAuthority(tenant_id="tenant-sg")
        with pytest.raises(Exception):
            authority.tenant_id = "tenant-other"  # type: ignore[misc]


class TestRequireTenantAuthority:
    def test_absent_authority_is_refused_and_names_the_read(self) -> None:
        with pytest.raises(MissingTenantAuthorityError) as raised:
            require_tenant_authority(None, operation="GET /portfolios/analytics")

        assert raised.value.operation == "GET /portfolios/analytics"
        assert "does not mint or default" in str(raised.value)

    def test_present_authority_passes_through_unchanged(self) -> None:
        authority = TenantAuthority(tenant_id="tenant-sg")
        assert require_tenant_authority(authority, operation="GET /x") is authority


class TestCoreIntegrationServiceCarriesTheTenant:
    @staticmethod
    def _service(authority: TenantAuthority | None) -> CoreIntegrationService:
        return CoreIntegrationService(
            base_url="http://core.invalid",
            timeout_seconds=1.0,
            tenant_authority=authority,
        )

    def test_every_core_read_carries_the_admitted_tenant(self) -> None:
        headers = self._service(TenantAuthority(tenant_id="tenant-sg"))._core_headers(operation="GET /test")

        assert headers[TENANT_HEADER] == "tenant-sg"

    def test_the_tenant_travels_alongside_trace_propagation_not_instead_of_it(self) -> None:
        """The tenant was added to a header set that already carried
        correlation and trace ids. Losing those would trade one observability
        gap for another."""

        headers = self._service(TenantAuthority(tenant_id="tenant-sg"))._core_headers(operation="GET /test")

        for expected in ("X-Correlation-Id", "X-Request-Id", "X-Trace-Id", "traceparent"):
            assert expected in headers, f"{expected} was dropped when the tenant was added"

    def test_a_read_without_authority_is_refused_before_the_request_is_built(self) -> None:
        """The refusal happens here rather than at Core, so a computation with
        no tenant never reaches the network - and cannot be mistaken for a
        transport failure."""

        with pytest.raises(MissingTenantAuthorityError):
            self._service(None)._core_headers(operation="GET /portfolios/analytics")

    def test_the_service_never_supplies_a_tenant_of_its_own(self) -> None:
        """The property that matters. Constructing without authority must not
        produce a usable header set under any default, fallback, or
        environment-derived value."""

        service = self._service(None)

        assert service._tenant_authority is None
        with pytest.raises(MissingTenantAuthorityError):
            service._core_headers(operation="GET /anything")
