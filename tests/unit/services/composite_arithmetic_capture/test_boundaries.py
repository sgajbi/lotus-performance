"""Independent input binding, finite-number and installed replay refusal contracts."""

import copy
import decimal
from fractions import Fraction
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.adapters.composite_arithmetic_capture import bundle, codec, storage
from app.models.composite_arithmetic_capture import ExactQuantity
from app.services.composite_arithmetic_capture import capture, replay, validation
from app.services.composite_arithmetic_capture.collector import ArithmeticCollector, context_payload
from core.errors import APIError


def binding_case():
    window = dict(
        materialization_id="window-1",
        retained_receipt_fingerprint="receipt-1",
        source_cut_id="cut-1",
        period_start="2026-01-01",
        period_end="2026-01-31",
    )
    scope = dict(
        composite_id="CMP",
        period_start=window["period_start"],
        period_end=window["period_end"],
        return_view="GROSS",
        reporting_currency="USD",
        windows=[window],
        materialization_vector=["window-1"],
    )
    request = {
        key: scope[key] for key in ("composite_id", "period_start", "period_end", "return_view", "reporting_currency")
    }
    request.update(calculation_id="calculation-1", materialization_ids=["window-1"])
    fact = {
        key: scope[key] for key in ("composite_id", "period_start", "period_end", "return_view", "reporting_currency")
    }
    fact["portfolio_id"] = "member-1"
    payload = dict(
        scope=scope,
        calculation_request=request,
        source=dict(tenant_id="tenant-a", calculation_id="calculation-1"),
        algorithm=dict(engine_version="engine-1"),
        input_digest="digest-1",
        projection_replay=dict(input_digest="digest-1"),
        ordered_facts=[dict(ordinal=0, window_ordinal=0, fact=fact)],
        source_refs=validation.retained_refs([window], "tenant-a"),
    )
    response = {key: scope[key] for key in ("composite_id", "period_start", "period_end")}
    response.update(
        selection_manifest=dict(windows=[copy.deepcopy(window)], engine_version="engine-1"),
        periods=[dict(return_view="GROSS", reporting_currency="USD")],
    )
    return payload, response


@pytest.mark.parametrize(
    "fault",
    [
        "window",
        "vector",
        "scope",
        "calculation",
        "currency",
        "engine",
        "digest",
        "period-basis",
        "reference",
        "ordinal",
        "absent-window",
        "duplicate",
    ],
)
def test_cross_field_source_binding_rejects_each_independent_substitution(fault):
    payload, response = binding_case()
    validation.validate_vector(payload, response)
    if fault == "window":
        payload["scope"]["windows"][0]["source_cut_id"] = "another-cut"
    elif fault == "vector":
        payload["scope"]["materialization_vector"] = ["another-window"]
    elif fault == "scope":
        payload["calculation_request"]["composite_id"] = "another-composite"
    elif fault in {"calculation", "currency"}:
        payload["calculation_request"]["calculation_id" if fault == "calculation" else "reporting_currency"] = "other"
    elif fault == "engine":
        payload["algorithm"]["engine_version"] = "other"
    elif fault == "digest":
        payload["projection_replay"]["input_digest"] = "other"
    elif fault == "period-basis":
        response["periods"][0]["reporting_currency"] = "EUR"
    elif fault == "reference":
        payload["source_refs"][0]["tenant_id"] = "tenant-b"
    elif fault == "ordinal":
        payload["ordered_facts"][0]["ordinal"] = 1
    elif fault == "absent-window":
        payload["ordered_facts"][0]["window_ordinal"] = 1
    else:
        second = copy.deepcopy(payload["ordered_facts"][0])
        second["ordinal"] = 1
        payload["ordered_facts"].append(second)
    with pytest.raises(ValueError, match="Arithmetic|arithmetic|Duplicate"):
        validation.validate_vector(payload, response)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "BLOCKED"),
        ("return_value", None),
        ("return_value", decimal.Decimal("NaN")),
        ("ending_market_value", decimal.Decimal("Infinity")),
        ("return_value", decimal.Decimal("1E-161")),
    ],
)
def test_rational_audit_refuses_incomplete_or_unbounded_original_facts(field, value):
    fact = SimpleNamespace(
        status="READY",
        period_start="start",
        period_end="end",
        return_value=decimal.Decimal("0.1"),
        beginning_market_value=decimal.Decimal(1),
        ending_market_value=decimal.Decimal(1),
    )
    setattr(fact, field, value)
    with pytest.raises(APIError) as error:
        replay.mathematical_return([fact])
    assert error.value.error_code == (
        "RESOURCE_LIMIT"
        if field == "return_value" and value == decimal.Decimal("1E-161")
        else "SOURCE_COVERAGE_INCOMPLETE"
    )


def test_rational_audit_requires_positive_assets_and_bounds_exact_growth():
    fact = SimpleNamespace(
        status="READY",
        period_start="start",
        period_end="end",
        return_value=decimal.Decimal("0.1"),
        beginning_market_value=decimal.Decimal(0),
        ending_market_value=decimal.Decimal(1),
    )
    with pytest.raises(APIError) as error:
        replay.mathematical_return([fact])
    assert error.value.error_code == "SOURCE_COVERAGE_INCOMPLETE"
    with pytest.raises(APIError) as error:
        replay.exact(Fraction(1 << 13600))
    assert error.value.error_code == "RESOURCE_LIMIT"
    assert replay.exact(Fraction(1, 6)) == {"numerator": "1", "denominator": "6"}


@pytest.mark.parametrize("numerator,denominator", [("2", "4"), ("-0", "1"), ("01", "1")])
def test_exact_quantities_reject_equivalent_but_noncanonical_encodings(numerator, denominator):
    with pytest.raises(ValidationError, match="canonical"):
        ExactQuantity(numerator=numerator, denominator=denominator)
    assert ExactQuantity(numerator="-1", denominator="6").numerator == "-1"


@pytest.mark.parametrize("missing", ["context", "exit_flags", "checkpoints"])
def test_capture_never_invents_missing_source_time_observations(missing):
    collector = ArithmeticCollector()
    collector.context, collector.exit_flags, collector.checkpoints = {}, {}, [{"weighted_return": "0"}]
    setattr(collector, missing, [] if missing == "checkpoints" else None)
    with pytest.raises(APIError) as error:
        capture._require_collected_source(collector)
    assert error.value.error_code == "SOURCE_COVERAGE_INCOMPLETE"


def test_capture_refuses_oversized_checkpoint_and_complete_wire(monkeypatch):
    collector = SimpleNamespace(context={}, exit_flags={}, checkpoints=[{"weighted_return": "1" * 161}])
    with pytest.raises(APIError) as error:
        capture._require_collected_source(collector)
    assert error.value.error_code == "RESOURCE_LIMIT"
    monkeypatch.setattr(capture, "MAX_CAPTURE_BYTES", 12)
    capture._require_bounds({})
    with pytest.raises(APIError) as error:
        capture._require_bounds({"value": "a" * 20})
    assert error.value.error_code == "RESOURCE_LIMIT"


@pytest.mark.parametrize("raw", ['{"value":0.1}', '{"value":NaN}', '{"value":Infinity}'])
def test_capture_json_rejects_inexact_numeric_tokens(raw):
    with pytest.raises(ValueError, match="exact finite"):
        codec.decode(raw)
    assert codec.decode('{"value":"0.1"}') == {"value": "0.1"}


def test_installed_source_normalization_rejects_isolated_carriage_return():
    with pytest.raises(ValueError, match="carriage return"):
        bundle.normalized_source(b"line\rnext")
    assert bundle.normalized_source(b"line\r\nnext") == b"line\nnext"


def test_profile_collector_and_sidecar_presence_are_paired():
    with pytest.raises(ValueError, match="Unsupported"):
        storage.profile_request_digest("legacy", "unknown")
    with pytest.raises(ValueError, match="collector"):
        storage.prepare_capture(
            candidate_id=None, request=None, response=None, principal=None, observer=object(), profile=None
        )
    with pytest.raises(ValueError, match="Half"):
        capture.read_capture(SimpleNamespace(arithmetic_capture_json="{}", arithmetic_capture_digest=None), {})


def test_projection_adapter_absence_refuses_instead_of_approximating(monkeypatch):
    def unavailable():
        raise ValueError("missing trusted source")

    monkeypatch.setattr(replay, "installed_source_digest", unavailable)
    with pytest.raises(APIError) as error:
        replay._require_adapter({})
    assert error.value.error_code == "PROJECTION_ADAPTER_UNAVAILABLE"
    monkeypatch.setattr(capture, "installed_source_digest", unavailable)
    collector = SimpleNamespace(context={}, exit_flags={}, checkpoints=[{"return": "0"}])
    with pytest.raises(APIError) as error:
        capture.build_capture(
            collector=collector,
            candidate_id=None,
            request=None,
            response=None,
            principal=None,
            build=None,
            request_digest=None,
            original_digest=None,
            now=None,
        )
    assert error.value.error_code == "PROJECTION_ADAPTER_UNAVAILABLE"


def test_context_restoration_rejects_changed_rounding_without_touching_ambient_flags():
    before = context_payload(decimal.getcontext())
    payload = copy.deepcopy(before)
    payload["rounding"] = decimal.ROUND_DOWN
    with pytest.raises(APIError) as error:
        replay.restored_context(payload)
    assert error.value.error_code == "UNSUPPORTED_PRECISION_CONTEXT"
    assert context_payload(decimal.getcontext()) == before


def test_retained_capture_requires_canonical_bytes_not_just_equivalent_json():
    payload = {"value": "0.1"}
    row = SimpleNamespace(arithmetic_capture_json=' {"value": "0.1"}', arithmetic_capture_digest=codec.digest(payload))
    with pytest.raises(ValueError, match="byte custody"):
        capture.read_capture(row, {})


def test_profile_capture_requires_source_observer_after_native_request_admission(monkeypatch):
    from app.adapters import composite_result_candidate_storage as candidates
    from app.models.composite_arithmetic_capture import PROFILE

    monkeypatch.setattr(candidates, "_admit", lambda *args: (None, None, None, None))
    with pytest.raises(APIError) as error:
        storage.prepare_capture(
            candidate_id=None, request=None, response=None, principal=None, observer=None, profile=PROFILE
        )
    assert error.value.error_code == "SOURCE_COVERAGE_INCOMPLETE"


def test_whole_candidate_size_guard_includes_receipt_envelope(monkeypatch):
    from app.adapters import composite_result_candidate_storage as candidates

    monkeypatch.setattr(candidates, "_candidate_receipt", lambda *args: {"original_response": "x" * 40})
    monkeypatch.setattr(storage, "MAX_CAPTURE_BYTES", 40)
    with pytest.raises(APIError) as error:
        storage.require_candidate_bounds(SimpleNamespace(arithmetic_capture_digest="digest"), {}, {"small": "capsule"})
    assert error.value.error_code == "RESOURCE_LIMIT"


def test_retained_optional_sidecar_presence_cannot_change_on_retry(monkeypatch):
    monkeypatch.setattr(storage, "read_capture", lambda *args: None)
    with pytest.raises(ValueError, match="profile conflicts"):
        storage.require_same_arithmetic(None, {}, {})
