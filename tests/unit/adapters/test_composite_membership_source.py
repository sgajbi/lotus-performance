"""Pinned source reads preserve admitted authority and typed source verdicts."""

from copy import deepcopy

import pytest

from app.adapters.composite_membership_source import ManageCompositeMembershipSource
from app.core.config import get_settings
from app.services.composite_materialization.source_contract import source_digest
from core.errors import APIError
from tests.composite_materialization_helpers import command_for, source_products


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (503, "COMPOSITE_MEMBERSHIP_SOURCE_UNAVAILABLE", True),
        (429, "COMPOSITE_MEMBERSHIP_SOURCE_UNAVAILABLE", True),
        (403, "COMPOSITE_MEMBERSHIP_SOURCE_REFUSED", False),
        (404, "COMPOSITE_MEMBERSHIP_SOURCE_REFUSED", False),
    ],
)
async def test_failed_source_read_stops_before_later_products(monkeypatch, status, code, retryable):
    reads = []

    async def read(**kwargs):
        reads.append(kwargs)
        return status, {"detail": "not retained or disclosed"}

    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", "http://manage/api/v1/")
    monkeypatch.setattr("app.adapters.composite_membership_source.get_with_retry", read)
    with pytest.raises(APIError) as refused:
        await ManageCompositeMembershipSource().read_pinned(
            command_for(), tenant_id="tenant-a", actor_id="operator", role="DPM_COMPOSITE_CONSUMER"
        )
    assert (refused.value.error_code, refused.value.retryable) == (code, retryable)
    assert len(reads) == 1
    assert reads[0]["headers"]["X-Tenant-Id"] == "tenant-a"
    assert reads[0]["url"].startswith("http://manage/api/v1/rebalance/composites/")


@pytest.mark.asyncio
async def test_unconfigured_source_is_retryable_without_network_io(monkeypatch):
    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", None)
    with pytest.raises(APIError) as refused:
        await ManageCompositeMembershipSource().read_pinned(
            command_for(), tenant_id="tenant-a", actor_id="operator", role="DPM_COMPOSITE_CONSUMER"
        )
    assert refused.value.error_code == "COMPOSITE_MEMBERSHIP_SOURCE_UNAVAILABLE"
    assert refused.value.status_code == 503 and refused.value.retryable is True


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["hash", "owner", "schema"])
async def test_source_semantic_errors_are_not_collapsed_into_schema_errors(monkeypatch, change):
    products = list(deepcopy(source_products()))
    if change == "owner":
        products[0]["source_authority"]["asset_owner"] = "lotus-performance"
    elif change == "schema":
        products[0]["unknown_authority"] = "untrusted"
    products[0]["content_hash"] = source_digest(products[0])
    command = command_for(products)
    if change == "hash":
        products[0]["display_name"] = "unexplained change"
    pending = iter(products)

    async def read(**kwargs):
        return 200, next(pending)

    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", "http://manage/api/v1")
    monkeypatch.setattr("app.adapters.composite_membership_source.get_with_retry", read)
    with pytest.raises(APIError) as refused:
        await ManageCompositeMembershipSource().read_pinned(
            command, tenant_id="tenant-a", actor_id="operator", role="DPM_COMPOSITE_CONSUMER"
        )
    assert (
        refused.value.error_code
        == {
            "hash": "COMPOSITE_SOURCE_HASH_MISMATCH",
            "owner": "COMPOSITE_SOURCE_OWNER_MISMATCH",
            "schema": "COMPOSITE_SOURCE_SCHEMA_INVALID",
        }[change]
    )
    assert refused.value.status_code == 422
