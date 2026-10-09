"""Read Manage's exact, read-only published eligibility resolver.

The producer getter performs the transactional publication join. The consumer also
checks separately fetched canonical product wires against that returned graph.
No issuer qualification or financial authority follows from an HTTP response.
"""

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from app.core.config import get_settings
from app.models.composite_authority import ManageCompositeDefinitionV2, decode_authority_json
from app.models.composite_eligibility_evidence import decode_eligibility_receipt
from app.models.composite_materialization import CompositeMaterializationCommand
from app.models.composite_monthly_eligibility_evidence import monthly_publication_binding
from app.observability import propagation_headers
from app.ports.composite_external_evidence import PublishedEligibilityEvidence
from app.services.composite_materialization.source_contract import (
    ManageUniverseAttestation,
    published_eligibility_from_wire,
    source_refusal,
    verify_source_wire_hashes,
)
from app.services.core_tenant_authority import admitted_tenant_authority, require_composite_tenant_authority
from app.services.http_resilience import post_with_retry, response_payload
from core.errors import APIError


def eligibility_response_payload(response: httpx.Response) -> dict[str, Any]:
    if response.status_code != 200:
        return response_payload(response)
    try:
        return decode_authority_json(response.text)
    except ValueError as exc:
        raise source_refusal("COMPOSITE_ELIGIBILITY_SOURCE_SCHEMA_INVALID") from exc


class ManageCompositeEligibilityEvidence:
    def __init__(self, *, request_headers: Mapping[str, str] | None = None):
        self.request_headers = dict(request_headers or {})

    async def read_published(
        self,
        command: CompositeMaterializationCommand,
        *,
        tenant_id: str,
        actor_id: str,
        role: str,
        definition: dict[str, Any],
        membership: dict[str, Any],
        attestation: dict[str, Any],
    ) -> PublishedEligibilityEvidence:
        authority = require_composite_tenant_authority(admitted_tenant_authority(tenant_id))
        settings = get_settings()
        if not settings.MANAGE_BASE_URL:
            raise APIError(
                status_code=503,
                detail="Composite eligibility source is not configured.",
                error_code="COMPOSITE_ELIGIBILITY_SOURCE_UNAVAILABLE",
                retryable=True,
            )
        try:
            verify_source_wire_hashes(command, definition, membership, attestation)
            typed = ManageCompositeDefinitionV2.model_validate(definition)
            universe = ManageUniverseAttestation.model_validate(attestation)
            binding = monthly_publication_binding(
                [item.model_dump() for item in universe.source_products], universe.source_cut_id
            )
            binding = binding or typed.source_authority.payload.eligibility_evaluation_binding
            if binding.product_name not in {"CompositeSubjectEvaluationApproval", "CompositeMonthlyEvaluationApproval"}:
                raise source_refusal("COMPOSITE_ELIGIBILITY_RESOLUTION_BINDING_MISMATCH")
            if (typed.tenant_id, typed.composite_id, typed.definition_version) != (
                tenant_id,
                command.composite_id,
                command.definition_version,
            ):
                raise source_refusal("COMPOSITE_SOURCE_SCOPE_MISMATCH")
            status, payload = await post_with_retry(
                url=settings.MANAGE_BASE_URL.rstrip("/")
                + "/rebalance/composites/"
                + quote(command.composite_id, safe="")
                + "/definitions/"
                + quote(command.definition_version, safe="")
                + "/eligibility-evidence/resolve",
                timeout_seconds=settings.MANAGE_TIMEOUT_SECONDS,
                json_body=binding.model_dump(),
                headers=manage_read_headers(
                    self.request_headers, tenant_id=authority.tenant_id, actor_id=actor_id, role=role
                ),
                max_retries=settings.CORE_MAX_RETRIES,
                backoff_seconds=settings.CORE_RETRY_BACKOFF_SECONDS,
                response_decoder=eligibility_response_payload,
            )
            _require_resolved_status(status)
            # Reuse exact duplicate/number-safe decoder and product discriminator.
            receipt = decode_eligibility_receipt(json.dumps(payload))
            return published_eligibility_from_wire(
                command=command,
                tenant_id=tenant_id,
                definition=definition,
                membership=membership,
                attestation=attestation,
                receipt=receipt,
            )
        except APIError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise source_refusal("COMPOSITE_ELIGIBILITY_SOURCE_SCHEMA_INVALID") from exc


def manage_read_headers(
    request_headers: Mapping[str, str], *, tenant_id: str, actor_id: str, role: str
) -> dict[str, str]:
    """Carry existing admitted authority; selected identities cannot be overwritten."""
    protected = {"x-tenant-id": tenant_id, "x-actor-id": actor_id, "x-role": role}
    normalized = _normalized_manage_authority(request_headers)
    for name, selected in protected.items():
        if name in normalized and normalized[name] != selected:
            raise _upstream_authority_conflict()
    headers = {
        **propagation_headers(normalized.get("x-correlation-id")),
        "X-Tenant-Id": tenant_id,
        "X-Actor-Id": actor_id,
        "X-Role": role,
    }
    for incoming, outgoing in (("x-service-identity", "X-Service-Identity"), ("x-capabilities", "X-Capabilities")):
        if incoming in normalized:
            headers[outgoing] = normalized[incoming]
    return headers


def _normalized_manage_authority(request_headers: Mapping[str, str]) -> dict[str, str]:
    allowed = {"x-tenant-id", "x-actor-id", "x-role", "x-service-identity", "x-capabilities", "x-correlation-id"}
    normalized = {}
    for name, value in request_headers.items():
        if not isinstance(name, str):
            raise _upstream_authority_conflict()
        key = name.lower()
        if key in allowed:
            if key in normalized or not isinstance(value, str):
                raise _upstream_authority_conflict()
            normalized[key] = value
    return normalized


def _upstream_authority_conflict() -> APIError:
    return APIError(
        status_code=422,
        detail="Retained upstream authority conflicts with selected composite identity.",
        error_code="COMPOSITE_UPSTREAM_AUTHORITY_CONFLICT",
    )


def _require_resolved_status(status: int) -> None:
    if status == 200:
        return
    transient = status >= 500 or status == 429
    raise APIError(
        status_code=503 if transient else 422,
        detail="Pinned composite eligibility publication could not be admitted.",
        error_code="COMPOSITE_ELIGIBILITY_SOURCE_UNAVAILABLE" if transient else "COMPOSITE_ELIGIBILITY_SOURCE_REFUSED",
        retryable=transient,
    )
