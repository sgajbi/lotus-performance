"""Immutable attribution inputs subordinate to the existing Composite owner."""

import json
from dataclasses import dataclass

from sqlalchemy import insert, select

from app.adapters.composite_attribution_dependencies import retained_dependencies
from app.adapters.composite_attribution_schema import attribution_guard_statements, attribution_inputs
from app.adapters.durable_schema.guards import require_managed_guards
from app.models.composite_attribution import AttributionObservation, CompositeAttributionRequest
from app.models.composite_authority import authority_digest
from app.services.composite_attribution.admission import admit_attribution
from app.services.composite_attribution.source_binding import refuse


@dataclass(frozen=True)
class AttributionInputSnapshot:
    request: CompositeAttributionRequest
    observation: AttributionObservation


def read_attribution_input(connection, calculation_id, *, principal):
    require_managed_guards(connection, attribution_guard_statements(connection.dialect))
    row = (
        connection.execute(
            select(attribution_inputs).where(
                attribution_inputs.c.tenant_id == principal.tenant_id,
                attribution_inputs.c.calculation_id == str(calculation_id),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    payload = json.loads(row["payload_json"])
    if authority_digest(payload) != row["payload_digest"]:
        refuse("INPUT_CUSTODY_CORRUPT", "Retained original attribution wire digest differs.")
    request = CompositeAttributionRequest.model_validate(payload["request"])
    observation = AttributionObservation.model_validate(payload["observation"])
    if (
        str(request.calculation_id) != row["calculation_id"]
        or observation.input_manifest_digest != row["input_manifest_digest"]
    ):
        refuse("INPUT_CUSTODY_CORRUPT", "Retained tenant/calculation/input identity differs.")
    original, vector = retained_dependencies(connection, request, principal, require_current=False)
    expected = admit_attribution(
        request,
        observation.source_bundle,
        observation.approval,
        tenant_id=principal.tenant_id,
        original=original,
        vector=vector,
    )
    if expected != observation:
        refuse("INPUT_CUSTODY_CORRUPT", "Retained attribution projection differs from its original evidence.")
    return AttributionInputSnapshot(request, observation)


def bind_attribution_input(connection, request, observation, *, principal):
    existing = read_attribution_input(connection, request.calculation_id, principal=principal)
    original, vector = retained_dependencies(connection, request, principal)
    admitted = admit_attribution(
        request,
        observation.source_bundle,
        observation.approval,
        tenant_id=principal.tenant_id,
        original=original,
        vector=vector,
    )
    if admitted != observation:
        refuse("INPUT_CUSTODY_CONFLICT", "Proposed attribution projection differs from its complete original.")
    snapshot = AttributionInputSnapshot(request, observation)
    if existing is not None:
        if existing != snapshot:
            refuse("INPUT_CUSTODY_CONFLICT", "Calculation already binds different attribution originals.")
        return existing
    payload = {"request": request.model_dump(mode="json"), "observation": observation.model_dump(mode="json")}
    connection.execute(
        insert(attribution_inputs).values(
            tenant_id=principal.tenant_id,
            calculation_id=str(request.calculation_id),
            input_manifest_digest=observation.input_manifest_digest,
            payload_digest=authority_digest(payload),
            payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False),
        )
    )
    return snapshot
