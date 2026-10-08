from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from app.adapters.manage_composite_eligibility_evidence import ManageCompositeEligibilityEvidence, manage_read_headers
from app.core.config import get_settings
from app.models.composite_authority import ManageCompositeDefinitionV2, decode_authority_json
from app.models.composite_materialization import CompositeMaterializationCommand
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


def strict_composite_response_payload(response):
    if response.status_code != 200:
        return response_payload(response)
    try:
        return decode_authority_json(response.text)
    except ValueError as exc:
        raise source_refusal("COMPOSITE_SOURCE_SCHEMA_INVALID") from exc


class ManageCompositeMembershipSource:
    def __init__(self, *, request_headers: Mapping[str, str] | None = None):
        self.request_headers = dict(request_headers or {})

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
        headers = manage_read_headers(self.request_headers, tenant_id=authority.tenant_id, actor_id=actor_id, role=role)
        prefix = (
            "/rebalance/composites/"
            + quote(command.composite_id, safe="")
            + "/definitions/"
            + quote(command.definition_version, safe="")
        )

        async def read(path: str, *, strict_wire: bool = False) -> dict[str, Any]:
            status_code, payload = await get_with_retry(
                url=settings.MANAGE_BASE_URL.rstrip("/") + path,
                timeout_seconds=settings.MANAGE_TIMEOUT_SECONDS,
                query_params={},
                headers=headers,
                max_retries=settings.CORE_MAX_RETRIES,
                backoff_seconds=settings.CORE_RETRY_BACKOFF_SECONDS,
                response_decoder=strict_composite_response_payload if strict_wire else composite_response_payload,
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
        strict_wire = definition.get("product_version") == "v2"
        membership = await read(
            prefix + "/membership/" + quote(command.membership_revision, safe=""), strict_wire=strict_wire
        )
        attestation = await read(
            prefix
            + "/membership/"
            + quote(command.membership_revision, safe="")
            + "/universe-attestations/"
            + quote(command.attestation_version, safe=""),
            strict_wire=strict_wire,
        )
        try:
            published_eligibility = None
            if definition.get("product_version") == "v2":
                typed = ManageCompositeDefinitionV2.model_validate(definition)
                if (
                    typed.source_authority.payload.eligibility_evaluation_binding.product_name
                    == "CompositeSubjectEvaluationApproval"
                ):
                    published_eligibility = await ManageCompositeEligibilityEvidence(
                        request_headers=self.request_headers
                    ).read_published(
                        command,
                        tenant_id=tenant_id,
                        actor_id=actor_id,
                        role=role,
                        definition=definition,
                        membership=membership,
                        attestation=attestation,
                    )
            return admit_pinned_source(
                command=command,
                tenant_id=tenant_id,
                definition=definition,
                membership=membership,
                attestation=attestation,
                published_eligibility=published_eligibility,
            )
        except APIError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise source_refusal("COMPOSITE_SOURCE_SCHEMA_INVALID") from exc
