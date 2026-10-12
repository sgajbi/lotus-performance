"""Financial refusals preserve exact native money and independently admitted daily FX."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.composite_authority import authority_digest
from app.models.twr_requests import TWRResolvedExecutionRequest
from app.services.composite_materialization.currency_normalization import (
    _recalculate_member_daily_returns,
    normalize_member_money,
)
from app.services.composite_materialization.currency_source_admission import (
    admit_composite_fx_source,
    fx_resolution_for_command,
)
from tests.composite_annual_fx_helpers import normalized_month_record
from tests.composite_currency_normalization_helpers import synthetic_fx_verification
from tests.unit.services.test_composite_annual_dispersion_service import month_record


@pytest.mark.parametrize("ending_basis", ["AFTER_FEES", "FEE_EXCLUSIVE"])
@pytest.mark.parametrize("precision", ["FLOAT64", "DECIMAL_STRICT"])
@pytest.mark.parametrize("metric_basis", ["NET", "GROSS"])
@pytest.mark.parametrize("fee", ["-2", "2", "0"])
def test_currency_reprojection_uses_retained_fee_basis(ending_basis, precision, metric_basis, fee):
    day = date(2026, 1, 5)
    retained = TWRResolvedExecutionRequest.model_validate(
        {
            "ending_value_basis": ending_basis,
            "portfolio": {
                "portfolio_id": "SOURCE_FEE_BASIS",
                "performance_start_date": day,
                "report_start_date": day,
                "report_end_date": day,
                "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
                "metric_basis": metric_basis,
                "precision_mode": precision,
                "rounding_precision": 12,
                "currency": "EUR",
                "currency_mode": "BOTH",
                "report_ccy": "USD",
                "fx": {
                    "rates": [
                        {"date": "2026-01-04", "ccy": "EUR", "rate": "1.3"},
                        {"date": day, "ccy": "EUR", "rate": "1.4"},
                    ]
                },
                "valuation_points": [{"perf_date": day, "begin_mv": "100", "end_mv": "102", "mgmt_fees": fee}],
            },
        }
    )
    native = SimpleNamespace(calculation_request=retained, precision_mode=precision)
    command = SimpleNamespace(period_start=day, period_end=day)
    actual = _recalculate_member_daily_returns(command, native, retained.portfolio.valuation_points)
    # Independently convert admitted source money at its economic-date fixing.
    # AFTER_FEES NET leaves observed ending assets intact; GROSS removes the fee.
    # Historical/stateless FEE_EXCLUSIVE keeps its existing separate-fee semantics.
    adjustment = (
        -Decimal(fee)
        if ending_basis == "AFTER_FEES" and metric_basis == "GROSS"
        else Decimal(fee)
        if ending_basis == "FEE_EXCLUSIVE" and metric_basis == "NET"
        else Decimal(0)
    )
    expected = ((Decimal(102) + adjustment) * Decimal("1.4") - Decimal(100) * Decimal("1.3")) / Decimal(130)
    assert len(actual) == 1
    assert abs(actual[0] - expected) <= Decimal("1e-12")


@pytest.fixture
def direct_case(monkeypatch):
    monkeypatch.setattr(
        "app.ports.composite_currency_normalization.composite_fx_receipt_verifier",
        lambda: SimpleNamespace(verify=synthetic_fx_verification),
    )
    record = normalized_month_record(month_record(7, count=1), "member-regime")
    native = record.outcomes[0].source_evidence.native_evidence
    command, admitted = _admit(record.command, record.source.currency_normalization_wire)
    expected = normalize_member_money(
        command, native, admitted, member_id="1", fx_snapshots=record.outcomes[0].source_evidence.fx_snapshots
    )
    assert expected.normalized_assets.observations[0].beginning_market_value == Decimal("100")
    assert expected.normalized_assets.observations[-1].ending_market_value == Decimal("100")
    assert expected == record.outcomes[0].source_evidence
    return command, native, admitted, record


def _admit(command, wire):
    binding = command.currency_normalization_binding.model_copy(update={"digest": authority_digest(wire)})
    command = command.model_copy(update={"currency_normalization_binding": binding})
    return command, admit_composite_fx_source(
        fx_resolution_for_command(command, tenant_id="tenant-a"), retained_wire=wire
    )


@pytest.mark.parametrize(
    "fault, message",
    [
        ("identity", "input identities differ"),
        ("request-currency", "Native currency or hedging"),
        ("window", "complete exact daily native window"),
        ("bod-flow", "Beginning-of-day"),
        ("asset-money", "request money disagree"),
        ("missing-fixing", "exact economic-date fixing"),
        ("engine-rate", "engine fixing differs"),
        ("reporting-mode", "required reporting currency"),
        ("duplicate-engine-rate", "Ambiguous retained member FX fixing"),
    ],
)
def test_normalization_refuses_incompatible_retained_money_or_engine_evidence(direct_case, fault, message):
    command, original, admitted, _ = direct_case
    native = deepcopy(original)
    request = native.calculation_request.portfolio
    if fault == "identity":
        native.input_fingerprint = "sha256:" + "8" * 64
    elif fault == "request-currency":
        request.currency = "GBP"
    elif fault == "window":
        native.source_assets.observations.pop(0)
    elif fault == "bod-flow":
        request.valuation_points[0].bod_cf = Decimal("1")
    elif fault == "asset-money":
        native.source_assets.observations[0].ending_market_value += Decimal("1")
    elif fault == "missing-fixing":
        wire = deepcopy(admitted.source_wire)
        wire["members"][0]["fixings"].pop(0)
        command, admitted = _admit(command, wire)
    elif fault == "engine-rate":
        request.fx.rates[0].rate = Decimal("1.01")
    elif fault == "reporting-mode":
        request.currency_mode = "LOCAL"
    else:
        request.fx.rates.append(deepcopy(request.fx.rates[0]))
    with pytest.raises(ValueError, match=message):
        normalize_member_money(command, native, admitted, member_id="1", fx_snapshots=[])


@pytest.mark.parametrize("fault", ["binding", "membership-receipt", "native-request", "fact-assets"])
def test_retained_normalization_rechecks_source_identity_and_fact_projection(direct_case, fault):
    from app.services.composite_materialization.member_evidence_policy import require_member_source_evidence
    from core.errors import APIConflictError

    command, _, admitted, record = direct_case
    original = record.outcomes[0]
    require_member_source_evidence(
        command, original, tenant_id="tenant-a", currency_normalization_wire=admitted.source_wire
    )
    outcome = deepcopy(original)
    if fault == "binding":
        outcome.source_evidence.normalization_binding.revision = "unrelated-revision"
    elif fault == "membership-receipt":
        outcome.source_evidence.native_evidence.membership_snapshot_id = "sha256:" + "8" * 64
    elif fault == "native-request":
        outcome.source_evidence.native_evidence.calculation_request.portfolio.rounding_precision = 11
    else:
        outcome.fact.beginning_market_value += Decimal("1")
    with pytest.raises(APIConflictError) as refused:
        require_member_source_evidence(
            command, outcome, tenant_id="tenant-a", currency_normalization_wire=admitted.source_wire
        )
    assert refused.value.error_code == "COMPOSITE_MATERIALIZATION_MEMBER_EVIDENCE_REFUSED"


@pytest.mark.parametrize("fault", ["early-release", "ready-before-fx", "source-rewrite"])
def test_fx_recovery_cannot_release_early_or_rewrite_admitted_source(direct_case, fault):
    from app.services.composite_materialization.progress_policy import require_progress_transition
    from core.errors import APIConflictError

    command, _, _, record = direct_case
    pending = record.source.model_copy(update={"currency_normalization_wire": None})
    prior_outcomes, source, state = [], record.source, "WAITING"
    if fault == "early-release":
        source, state = pending, "PUBLISHING"
    elif fault == "ready-before-fx":
        prior_outcomes = record.outcomes
    else:
        source = source.model_copy(
            update={"definition": source.definition.model_copy(update={"created_by": "rewritten-owner"})}
        )
    with pytest.raises(APIConflictError) as refused:
        require_progress_transition(
            command=command,
            tenant_id="tenant-a",
            prior_source=pending,
            prior_outcomes=prior_outcomes,
            prior_state="WAITING",
            source=source,
            outcomes=record.outcomes,
            state=state,
        )
    assert refused.value.error_code == (
        "COMPOSITE_MATERIALIZATION_SOURCE_IMMUTABLE" if fault == "source-rewrite" else "COMPOSITE_FX_SOURCE_UNAVAILABLE"
    )


@pytest.mark.parametrize("fault", ["date", "currency"])
def test_reported_native_assets_cannot_change_date_grain_or_relabel_money(direct_case, fault):
    from app.adapters.composite_member_result_source import _require_reported_asset_projection

    _, native, _, _ = direct_case
    assets = native.source_assets
    dates = [row.valuation_date for row in assets.observations]
    reported = [
        SimpleNamespace(
            portfolio_currency=assets.portfolio_currency,
            begin_mv=row.beginning_market_value,
            end_mv=row.ending_market_value,
        )
        for row in assets.observations
    ]
    _require_reported_asset_projection(assets, reported, dates)
    if fault == "date":
        dates.pop(0)
    else:
        reported[0].portfolio_currency = "USD"
    with pytest.raises(ValueError, match="date grains differ" if fault == "date" else "currency conflicts"):
        _require_reported_asset_projection(assets, reported, dates)
