"""Internal method evidence comes from immutable receipts, not a provider label."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.composite_materialization import CompositeMaterializationState
from app.models.composites import CompositeTWRRequest
from app.services.composite_calculation_service import (
    calculate_composite_twr_from_materializations,
    retained_return_method,
    retained_window_evidence,
)
from app.services.composite_materialization.records import MaterializationRecord
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIError
from tests.composite_authority_window_helpers import DatedMemberSource, dated_request
from tests.composite_materialization_helpers import MemberSource, admitted, command_for


def internal_record():
    command = command_for()
    source = admitted(command)
    member_source = MemberSource()
    outcomes = [
        member_source.read_member(
            command,
            reference,
            tenant_id="tenant-a",
            membership_snapshot_id=command.membership_content_hash,
            request_headers={},
        )
        for reference in command.member_calculations
    ]
    return MaterializationRecord(command, "operator", source, outcomes, CompositeMaterializationState.COMPLETE, None, 1)


def changed_member(record, index, *, engine_version=None, **policy):
    """Rebind all receipt identities so a semantic mismatch has valid custody."""
    outcome = record.outcomes[index]
    evidence = outcome.source_evidence
    portfolio = evidence.calculation_request.portfolio.model_copy(update=policy)
    request = evidence.calculation_request.model_copy(update={"portfolio": portfolio})
    version = engine_version or evidence.engine_version
    input_digest, calculation_digest = generate_value_fingerprint(request, version)
    evidence = evidence.model_copy(
        update={
            "calculation_request": request,
            "engine_version": version,
            "precision_mode": portfolio.precision_mode,
            "input_fingerprint": input_digest,
            "calculation_hash": calculation_digest,
        }
    )
    fact = outcome.fact.model_copy(
        update={
            "source_fingerprint": calculation_digest,
            "source_snapshot_id": generate_value_fingerprint(evidence, "composite-member-source.v1")[0],
        }
    )
    outcomes = list(record.outcomes)
    outcomes[index] = outcome.model_copy(update={"fact": fact, "source_evidence": evidence})
    references = list(record.command.member_calculations)
    references[index] = references[index].model_copy(
        update={
            "input_fingerprint": input_digest,
            "calculation_hash": calculation_digest,
        }
    )
    return replace(
        record, outcomes=outcomes, command=record.command.model_copy(update={"member_calculations": references})
    )


def dated_internal_record(day):
    command = command_for(period_start=day, period_end=day)
    references = []
    for reference in command.member_calculations:
        request = dated_request(reference.portfolio_id, reference.calculation_id, day, day)
        digest, calculation = generate_value_fingerprint(request, "controlled-test-v1")
        references.append(reference.model_copy(update={"input_fingerprint": digest, "calculation_hash": calculation}))
    command = command.model_copy(update={"member_calculations": references})
    outcomes = [
        DatedMemberSource().read_member(
            command,
            reference,
            tenant_id="tenant-a",
            membership_snapshot_id=command.membership_content_hash,
            request_headers={},
        )
        for reference in references
    ]
    return MaterializationRecord(
        command, "operator", admitted(command), outcomes, CompositeMaterializationState.COMPLETE, None, 1
    )


@pytest.mark.parametrize("mismatch", [False, True])
def test_internal_vector_links_common_method_and_refuses_cross_window_precision_drift(monkeypatch, mismatch):
    records = [dated_internal_record(date(2026, 1, day)) for day in (5, 6)]
    if mismatch:
        for index in range(3):
            records[1] = changed_member(records[1], index, precision_mode="DECIMAL_STRICT")
    store = SimpleNamespace(get_many=lambda identities, tenant_id: records)
    monkeypatch.setattr("app.services.composite_calculation_service.get_composite_materialization_store", lambda: store)
    request = CompositeTWRRequest(
        composite_id="COMPOSITE",
        period_start=date(2026, 1, 5),
        period_end=date(2026, 1, 6),
        materialization_ids=[record.command.materialization_id for record in records],
    )
    if mismatch:
        with pytest.raises(APIError) as error:
            calculate_composite_twr_from_materializations(tenant_id="tenant-a", request=request)
        assert error.value.error_code == "COMPOSITE_VECTOR_METHOD_MISMATCH"
    else:
        result, windows = calculate_composite_twr_from_materializations(tenant_id="tenant-a", request=request)
        expected = (Decimal(1) + Decimal(14) / Decimal(600)) ** 2 - Decimal(1)
        assert result.cumulative_return == expected.quantize(Decimal("0.000000000001"))
        assert windows[0].method_binding == windows[1].method_binding


def test_internal_method_uses_common_retained_receipts_without_fx_authority():
    record = internal_record()
    method = retained_return_method(record, None)
    assert record.source.currency_normalization_wire is None
    assert method["engine_version"] == "controlled-test-v1"
    assert method["metric_basis"] == "NET"
    assert method["precision_mode"] == "FLOAT64"
    assert method["reporting_currency"] == "USD"
    assert method["methodology"] == "TWR"
    assert method["method_digest"].startswith("sha256:")
    assert retained_window_evidence(record, method).method_binding == method


@pytest.mark.parametrize("missing", ["receipt", "members"])
def test_internal_method_refuses_missing_retained_evidence(missing):
    record = internal_record()
    if missing == "members":
        record = replace(record, outcomes=[])
    else:
        record.outcomes[0] = record.outcomes[0].model_copy(update={"source_evidence": None})
    with pytest.raises(APIError) as error:
        retained_return_method(record, None)
    assert error.value.error_code == "COMPOSITE_VECTOR_METHOD_UNAVAILABLE"


def test_internal_method_revalidates_receipt_digest_before_deriving_method():
    record = internal_record()
    original = record.outcomes[0]
    record.outcomes[0] = original.model_copy(
        update={"source_evidence": original.source_evidence.model_copy(update={"engine_version": "changed"})}
    )
    with pytest.raises(APIError) as error:
        retained_return_method(record, None)
    assert error.value.error_code == "COMPOSITE_MATERIALIZATION_MEMBER_EVIDENCE_REFUSED"


@pytest.mark.parametrize(
    "change",
    [
        {"engine_version": "another-engine"},
        {"precision_mode": "DECIMAL_STRICT"},
        {"rounding_precision": 9},
        {"currency": "EUR"},
    ],
)
def test_internal_method_refuses_valid_but_incompatible_member_methods(change):
    record = changed_member(internal_record(), 1, **change)
    with pytest.raises(APIError) as error:
        retained_return_method(record, None)
    assert error.value.error_code == "COMPOSITE_VECTOR_METHOD_MISMATCH"


def test_internal_method_accepts_common_decimal_policy_and_binds_its_digest():
    record = internal_record()
    floating = retained_return_method(record, None)
    original_receipt = retained_window_evidence(record, floating).retained_receipt_fingerprint
    for index in range(3):
        record = changed_member(record, index, precision_mode="DECIMAL_STRICT")
    strict = retained_return_method(record, None)
    assert strict["precision_mode"] == "DECIMAL_STRICT"
    assert strict["method_digest"] != floating["method_digest"]
    assert retained_window_evidence(record, strict).retained_receipt_fingerprint != original_receipt


@pytest.mark.parametrize("field,change", [("calendar", {"trading_calendar": "LSE"}), ("fee_effect", {"enabled": True})])
def test_internal_method_refuses_calendar_and_fee_policy_drift_with_valid_receipts(field, change):
    record = internal_record()
    original = getattr(record.outcomes[1].source_evidence.calculation_request.portfolio, field)
    record = changed_member(record, 1, **{field: original.model_copy(update=change)})
    with pytest.raises(APIError) as error:
        retained_return_method(record, None)
    assert error.value.error_code == "COMPOSITE_VECTOR_METHOD_MISMATCH"


@pytest.mark.parametrize("state", [CompositeMaterializationState.WAITING, CompositeMaterializationState.BLOCKED])
def test_internal_method_cannot_release_an_incomplete_window(state):
    with pytest.raises(APIError) as error:
        retained_return_method(replace(internal_record(), state=state), None)
    assert error.value.error_code == "REQUIRED_PERIOD_UNAVAILABLE"
