"""Deterministic authoring through production admission, BF and response assembly.

Only original source evidence is synthetic. Never imported by runtime routes.
Registered worker/custody/replay behavior is independently required by the ledger.
"""

from types import SimpleNamespace
from uuid import UUID

from pydantic import TypeAdapter

from app.adapters.composite_attribution_deployment import UnavailableAttributionAuthority, UnavailableAttributionSource
from app.adapters.composite_result_custody_schema import COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE
from app.models.composite_analytics import CompositeAnalyticsRequest
from app.models.platform_surfaces import ErrorDetailResponse
from app.observability import correlation_id_var, request_id_var
from app.ports.composite_attribution import AttributionAdmissionError
from app.services.async_result_store import AsyncResultStatus
from app.services.calculation_engine_version import CALCULATION_ENGINE_VERSION
from app.services.composite_attribution.admission import admit_attribution
from app.services.composite_attribution.application import (
    _replay_retained_result,
    accepted_attribution,
    build_attribution_response,
    source_error,
)
from app.services.error_details import safe_error_envelope
from core.attribution_precision_policy import require_attribution_precision
from core.errors import APIError
from tests.composite_attribution_helpers import controlled_financial_case, seal


def _ready(request, bundle, approval, original, vector):
    command = TypeAdapter(CompositeAnalyticsRequest).validate_python(request.model_dump(mode="json"))
    observation = admit_attribution(
        command, bundle, approval, tenant_id=bundle.tenant_id, original=original, vector=vector
    )
    return build_attribution_response(command, observation, engine_version=CALCULATION_ENGINE_VERSION)


def _error(operation):
    try:
        operation()
    except AttributionAdmissionError as exc:
        error = source_error(exc)
    except APIError as exc:
        error = exc
    else:
        raise AssertionError("The documented refusal must execute")
    correlation_token = correlation_id_var.set("")
    request_token = request_id_var.set("")
    try:
        envelope = safe_error_envelope(
            status_code=error.status_code,
            detail=error.detail,
            error_code=error.error_code,
            retryable=error.retryable,
        )
    finally:
        correlation_id_var.reset(correlation_token)
        request_id_var.reset(request_token)
    return ErrorDetailResponse.model_validate(envelope).model_dump(mode="json", exclude_unset=True)


def attribution_example_family():
    request, bundle, approval, original, vector = controlled_financial_case(
        calculation_id=UUID("00000000-0000-4000-8000-000000000017"),
        candidate_id=UUID("00000000-0000-4000-8000-000000000016"),
    )
    ready = _ready(request, bundle, approval, original, vector)
    retained = SimpleNamespace(
        analytics_type=COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE,
        result_status=AsyncResultStatus.COMPLETE,
        response_payload=ready.model_dump(mode="json"),
    )
    snapshot = SimpleNamespace(request=request, observation=ready.observation)
    replay = _replay_retained_result(request, snapshot, retained)
    correction = request.model_copy(
        update={
            "calculation_id": UUID("00000000-0000-4000-8000-000000000018"),
            "source_manifest_id": "corrected-2",
            "correction_of_calculation_id": request.calculation_id,
        }
    )
    corrected_bundle, corrected_approval = seal(
        bundle.model_copy(
            update={
                "source_manifest_id": correction.source_manifest_id,
                "benchmark_revision": "benchmark-2",
                "classification_revision": "classification-2",
                "groups": (bundle.groups[0].model_copy(update={"benchmark_return": 0.09}), bundle.groups[1]),
                "source_pins": tuple(
                    pin.model_copy(update={"revision": pin.pin_id + "-2"}) for pin in bundle.source_pins
                ),
            }
        )
    )
    incomplete, incomplete_approval = seal(bundle.model_copy(update={"groups": bundle.groups[1:]}))
    accepted = accepted_attribution(request.calculation_id).model_dump(mode="json")
    return {
        "request": request.model_dump(mode="json"),
        "correction_request": correction.model_dump(mode="json"),
        "accepted": accepted,
        "pending": dict(accepted),
        "original_ready": ready.model_dump(mode="json"),
        "original_replay": replay.model_dump(mode="json"),
        "corrected_ready": _ready(correction, corrected_bundle, corrected_approval, original, vector).model_dump(
            mode="json"
        ),
        "errors": {
            "source_unavailable": _error(
                lambda: UnavailableAttributionSource().read_population_scope(request, tenant_id="tenant-a")
            ),
            "purpose_unavailable": _error(lambda: UnavailableAttributionAuthority().verify(request, bundle)),
            "incomplete_groups": _error(lambda: _ready(request, incomplete, incomplete_approval, original, vector)),
            "strict_precision": _error(lambda: require_attribution_precision("DECIMAL_STRICT")),
        },
    }
