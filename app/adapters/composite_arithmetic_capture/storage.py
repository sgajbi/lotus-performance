"""Optional precision evidence in the existing candidate transaction."""

from datetime import UTC, datetime

from app.adapters.composite_arithmetic_capture.codec import MAX_CAPTURE_BYTES, comparison_digest, digest, wire
from app.models.composite_arithmetic_capture import PROFILE
from app.models.composite_authority import authority_digest
from app.services.composite_arithmetic_capture.capture import build_capture, read_capture, validate_capture
from app.services.composite_arithmetic_capture.collector import refuse


def profile_request_digest(legacy_digest, profile):
    if profile is None:
        return legacy_digest
    if profile != PROFILE:
        raise ValueError("Unsupported precision capture profile")
    return authority_digest({"legacy_semantic_request_digest": legacy_digest, "precision_capture_profile": profile})


def prepare_capture(*, candidate_id, request, response, principal, observer, profile):
    if profile is None:
        if observer is not None:
            raise ValueError("A source collector requires the registered capture profile")
        return None
    from app.adapters.composite_result_candidate_storage import _admit, _wire, _wire_digest

    request, response, build, legacy_digest = _admit(request, response, principal)
    if observer is None:
        refuse("SOURCE_COVERAGE_INCOMPLETE", "Source-time precision collector is required.")
    return build_capture(
        collector=observer,
        candidate_id=candidate_id,
        request=request,
        response=response,
        principal=principal,
        build=build,
        request_digest=profile_request_digest(legacy_digest, profile),
        original_digest=_wire_digest(_wire(response.model_dump(mode="json"))),
        now=datetime.now(UTC),
    )


def capture_columns(payload, *, response, principal, candidate_id, request_digest, original_digest, build, now):
    if payload is None:
        return {"arithmetic_capture_json": None, "arithmetic_capture_digest": None}
    provenance = {
        "captured_by": principal.subject,
        "captured_at_utc": now.isoformat(),
        "credential_id": principal.credential_id,
        "principal_kind": principal.principal_kind,
        "delegated_actor": principal.delegated_actor,
    }
    parsed = validate_capture(
        payload,
        response,
        tenant=principal.tenant_id,
        candidate_id=candidate_id,
        request_digest=request_digest,
        original_digest=original_digest,
        build=build,
        provenance=provenance,
    )
    return {"arithmetic_capture_json": wire(parsed), "arithmetic_capture_digest": digest(parsed)}


def require_same_arithmetic(row, response, payload):
    existing = read_capture(row, response)
    if (existing is None) != (payload is None):
        raise ValueError("Precision capture profile conflicts")
    if existing is not None:
        before = existing["payload"]["evidence_binding_digest"]
        if before != comparison_digest(payload, response):
            raise ValueError("Source arithmetic evidence conflicts")


def require_candidate_bounds(row, response, payload):
    if payload is None:
        return
    from app.adapters.composite_result_candidate_storage import _candidate_receipt

    receipt = _candidate_receipt(row, response)
    receipt["arithmetic_capture"] = {"digest": row.arithmetic_capture_digest, "payload": payload}
    if len(wire(receipt).encode("utf-8")) > MAX_CAPTURE_BYTES:
        refuse("RESOURCE_LIMIT", "The complete candidate precision result exceeds eight MiB.")
