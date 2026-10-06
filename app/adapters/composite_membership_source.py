from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from app.core.config import get_settings
from app.models.composite_authority import decode_authority_json
from app.models.composite_materialization import CompositeMaterializationCommand
from app.observability import propagation_headers
from app.services.composite_materialization.source_contract import (
    PinnedCompositeSource,
    admit_pinned_source,
    source_refusal,
)
from app.services.core_tenant_authority import admitted_tenant_authority, require_composite_tenant_authority
from app.services.http_resilience import get_with_retry, response_payload
from core.errors import APIError


def composite_response_payload(response):
    payload = response_payload(response)
    versions = []

    def observe_versions(items):
        versions.extend(value for key, value in items if key == "product_version")
        return dict(items)

    try:
        json.loads(response.text, object_pairs_hook=observe_versions)
    except ValueError:
        return payload
    if payload.get("product_name") == "CompositeDefinition" and "v2" in versions:
        try:
            return decode_authority_json(response.text)
        except ValueError as exc:
            raise source_refusal("COMPOSITE_SOURCE_SCHEMA_INVALID") from exc
    return payload


class ManageCompositeMembershipSource:
    async def read_pinned(
        self,
        command: CompositeMaterializationCommand,
        *,
        tenant_id: str,
        actor_id: str,
        role: str,
    ) -> PinnedCompositeSource:
        authority = require_composite_tenant_authority(admitted_tenant_authority(tenant_id))
        settings = get_settings()
        if not settings.MANAGE_BASE_URL:
            raise APIError(
                status_code=503,
                detail="Composite membership source is not configured.",
                error_code="COMPOSITE_MEMBERSHIP_SOURCE_UNAVAILABLE",
                retryable=True,
            )
        headers = {**propagation_headers(), **authority.headers(), "X-Actor-Id": actor_id, "X-Role": role}
        prefix = (
            "/rebalance/composites/"
            + quote(command.composite_id, safe="")
            + "/definitions/"
            + quote(command.definition_version, safe="")
        )

        async def read(path: str) -> dict[str, Any]:
            status_code, payload = await get_with_retry(
                url=settings.MANAGE_BASE_URL.rstrip("/") + path,
                timeout_seconds=settings.MANAGE_TIMEOUT_SECONDS,
                query_params={},
                headers=headers,
                max_retries=settings.CORE_MAX_RETRIES,
                backoff_seconds=settings.CORE_RETRY_BACKOFF_SECONDS,
                response_decoder=composite_response_payload,
            )
            if status_code != 200:
                raise APIError(
                    status_code=503 if status_code >= 500 or status_code == 429 else 422,
                    detail="Pinned composite membership source could not be admitted.",
                    error_code="COMPOSITE_MEMBERSHIP_SOURCE_UNAVAILABLE"
                    if status_code >= 500 or status_code == 429
                    else "COMPOSITE_MEMBERSHIP_SOURCE_REFUSED",
                    retryable=status_code >= 500 or status_code == 429,
                )
            return payload

        definition = await read(prefix)
        membership = await read(prefix + "/membership/" + quote(command.membership_revision, safe=""))
        attestation = await read(
            prefix
            + "/membership/"
            + quote(command.membership_revision, safe="")
            + "/universe-attestations/"
            + quote(command.attestation_version, safe="")
        )
        try:
            return admit_pinned_source(
                command=command,
                tenant_id=tenant_id,
                definition=definition,
                membership=membership,
                attestation=attestation,
            )
        except APIError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise source_refusal("COMPOSITE_SOURCE_SCHEMA_INVALID") from exc
