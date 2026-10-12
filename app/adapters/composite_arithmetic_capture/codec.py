"""Exact custody and narrowly enumerated semantic comparison projections."""

import copy
import hashlib
import json

MAX_CAPTURE_BYTES = 8 * 1024 * 1024
COMPARISON_EXCLUSIONS = (
    "/source/candidate_id",
    "/source/calculation_id",
    "/source/original_response_digest",
    "/calculation_request/calculation_id",
    "/response_binding/original_response_digest",
    "/capture_binding/captured_by",
    "/capture_binding/captured_at_utc",
    "/capture_binding/credential_id",
    "/capture_binding/principal_kind",
    "/capture_binding/delegated_actor",
    "/effective_context/entry_flags",
    "/exit_flags",
    "/evidence_binding_digest",
)


def wire(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(payload):
    return "sha256:" + hashlib.sha256(wire(payload).encode("utf-8")).hexdigest()


def wire_digest(value):
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def decode(value):
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate capture key")
            result[key] = item
        return result

    def invalid(value):
        raise ValueError("Capture requires exact finite JSON tokens")

    return json.loads(value, object_pairs_hook=unique, parse_float=invalid, parse_constant=invalid)


def semantic_output(payload):
    from app.adapters.composite_result_candidate_storage import _semantic_response

    return _semantic_response(payload)


def input_digest(payload):
    return digest({key: payload[key] for key in ("scope", "source_refs", "ordered_facts")})


def comparison_payload(payload, response):
    result = copy.deepcopy(payload)
    for pointer in COMPARISON_EXCLUSIONS:
        keys = pointer.lstrip("/").split("/")
        target = result
        for key in keys[:-1]:
            target = target[key]
        del target[keys[-1]]
    return {
        "comparison_version": "CandidateArithmeticComparison.v1",
        "semantic_request_digest": payload["source"]["request_binding_digest"],
        "semantic_output_digest": semantic_output(response),
        "arithmetic_payload": result,
    }


def comparison_digest(payload, response):
    return digest(comparison_payload(payload, response))
