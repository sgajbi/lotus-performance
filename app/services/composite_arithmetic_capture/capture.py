"""Bind one observed source calculation to immutable candidate custody."""

from app.adapters.composite_arithmetic_capture.bundle import installed_source_digest, runtime_identity
from app.adapters.composite_arithmetic_capture.codec import (
    MAX_CAPTURE_BYTES,
    comparison_digest,
    decode,
    digest,
    input_digest,
    wire,
)
from app.models.composite_arithmetic_capture import PROFILE, CompositeArithmeticCapture
from app.services.composite_arithmetic_capture.collector import refuse
from app.services.composite_arithmetic_capture.replay import qualify
from app.services.composite_arithmetic_capture.validation import retained_refs, validate_vector


def _ordered_facts(collector):
    positions = {(item.period_start, item.period_end): index for index, item in enumerate(collector.windows)}
    return [
        {
            "ordinal": index,
            "window_ordinal": positions[(fact.period_start, fact.period_end)],
            "fact": fact.model_dump(mode="json"),
        }
        for index, fact in enumerate(collector.facts)
    ]


def _require_collected_source(collector):
    if collector.context is None or collector.exit_flags is None or not collector.checkpoints:
        refuse("SOURCE_COVERAGE_INCOMPLETE", "Source-time precision evidence was not collected.")
    if any(len(value) > 160 for checkpoint in collector.checkpoints for value in checkpoint.values()):
        refuse("RESOURCE_LIMIT", "Source precision checkpoints exceed the numeric envelope.")


def build_capture(
    *, collector, candidate_id, request, response, principal, build, request_digest, original_digest, now
):
    _require_collected_source(collector)
    try:
        kernel_digest = installed_source_digest()
    except ValueError:
        refuse("PROJECTION_ADAPTER_UNAVAILABLE", "The installed projection source closure is unavailable.")
    windows = [window.model_dump(mode="json") for window in collector.windows]
    scope = {
        "composite_id": request.composite_id,
        "period_start": request.period_start.isoformat(),
        "period_end": request.period_end.isoformat(),
        "return_view": str(request.return_view),
        "reporting_currency": response.periods[0].reporting_currency,
        "materialization_vector": [str(value) for value in request.materialization_ids],
        "windows": windows,
    }
    payload = {
        "schema_version": "CompositeArithmeticCapture.v1",
        "adapter": PROFILE,
        "source": {
            "owner": "lotus-performance",
            "tenant_id": principal.tenant_id,
            "candidate_id": str(candidate_id),
            "calculation_id": str(request.calculation_id),
            "original_response_digest": original_digest,
            "request_binding_digest": request_digest,
        },
        "algorithm": {
            "engine_version": response.selection_manifest.engine_version,
            "release_commit": build,
            "kernel_source_digest": kernel_digest,
            "projection_policy": "composite-quantize-inherited.v1",
            "runtime": runtime_identity(),
        },
        "scope": scope,
        "calculation_request": request.model_dump(mode="json"),
        "source_refs": retained_refs(windows, principal.tenant_id),
        "ordered_facts": _ordered_facts(collector),
        "context_route": collector.route,
        "effective_context": collector.context,
        "exit_flags": collector.exit_flags,
        "checkpoints": collector.checkpoints,
        "response_binding": {"wire_codec": "candidate-wire.v1", "original_response_digest": original_digest},
        "capture_binding": {
            "captured_by": principal.subject,
            "captured_at_utc": now.isoformat(),
            "credential_id": principal.credential_id,
            "principal_kind": principal.principal_kind,
            "delegated_actor": principal.delegated_actor,
        },
    }
    payload["input_digest"] = input_digest(payload)
    payload["projection_replay"] = qualify(payload, response.model_dump(mode="json"))
    payload["evidence_binding_digest"] = ""
    payload["evidence_binding_digest"] = comparison_digest(payload, response.model_dump(mode="json"))
    result = CompositeArithmeticCapture.model_validate(payload).model_dump(mode="json")
    _require_bounds(result)
    return result


def _require_bounds(payload):
    if len(wire(payload).encode("utf-8")) > MAX_CAPTURE_BYTES:
        refuse("RESOURCE_LIMIT", "The complete arithmetic capture exceeds eight MiB.")


def validate_capture(payload, response, *, tenant, candidate_id, request_digest, original_digest, build, provenance):
    parsed = CompositeArithmeticCapture.model_validate(payload).model_dump(mode="json")
    _require_bounds(parsed)
    source = parsed["source"]
    actual = (
        source["tenant_id"],
        source["candidate_id"],
        source["calculation_id"],
        source["request_binding_digest"],
        source["original_response_digest"],
        parsed["response_binding"]["original_response_digest"],
        parsed["algorithm"]["release_commit"],
        parsed["capture_binding"],
        parsed["input_digest"],
        parsed["evidence_binding_digest"],
    )
    expected = (
        tenant,
        str(candidate_id),
        response["calculation_id"],
        request_digest,
        original_digest,
        original_digest,
        build,
        provenance,
        input_digest(parsed),
        comparison_digest(parsed, response),
    )
    if actual != expected:
        raise ValueError("Arithmetic capture custody binding differs")
    validate_vector(parsed, response)
    return parsed


def read_capture(row, response):
    raw, expected = row.arithmetic_capture_json, row.arithmetic_capture_digest
    if raw is None and expected is None:
        return None
    if raw is None or expected is None:
        raise ValueError("Half arithmetic capture")
    payload = decode(raw)
    if digest(payload) != expected or wire(payload) != raw:
        raise ValueError("Arithmetic capture byte custody differs")
    provenance = {
        key: getattr(row, key)
        for key in ("captured_by", "captured_at_utc", "credential_id", "principal_kind", "delegated_actor")
    }
    parsed = validate_capture(
        payload,
        response,
        tenant=row.tenant_id,
        candidate_id=row.candidate_id,
        request_digest=row.semantic_request_digest,
        original_digest=row.original_response_digest,
        build=row.build_commit,
        provenance=provenance,
    )
    return {"digest": expected, "payload": parsed}
