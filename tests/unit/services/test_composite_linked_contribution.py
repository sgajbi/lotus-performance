from datetime import date
from decimal import ROUND_DOWN, ROUND_UP, Decimal, Inexact, localcontext
from uuid import UUID

import pytest

from app.models.composite_linked_contribution import CompositeLinkedContributionRequest
from app.models.composites import CompositeMemberReturnFact, CompositeTWRWindowEvidence
from app.services.composite_linked_contribution import application
from core.errors import APIUnprocessableEntityError


def _inputs(returns, *, status="READY"):
    facts, windows = [], []
    for month, ret in enumerate(returns, 1):
        identity = UUID(int=month)
        start = date(2026, month, 1)
        end = date(2026, month, 28)
        # Contiguity is the retained reader's responsibility, exercised by real API tests.
        facts.append(
            CompositeMemberReturnFact(
                composite_id="COMPOSITE",
                portfolio_id="A" if month == 1 else "B",
                period_start=start,
                period_end=end,
                return_value=ret,
                beginning_market_value="100",
                ending_market_value="100",
                return_view="GROSS",
                reporting_currency="USD",
                calculation_id=str(identity),
                source_snapshot_id=f"snapshot-{month}",
                source_fingerprint=f"fingerprint-{month}",
                restatement_version="original",
                restatement_sequence=month,
                status=status,
                reason_codes=[] if status == "READY" else ["SOURCE_UNAVAILABLE"],
            )
        )
        windows.append(
            CompositeTWRWindowEvidence(
                materialization_id=identity,
                period_start=start,
                period_end=end,
                restatement_sequence=month,
                definition_content_hash="definition",
                membership_content_hash="membership",
                attestation_content_hash="attestation",
                source_cut_id="cut",
                method_binding={"method": "TWR"},
                retained_receipt_fingerprint=f"receipt-{month}",
            )
        )
    request = CompositeLinkedContributionRequest(
        metric_id="LINKED_MEMBER_CONTRIBUTION",
        composite_id="COMPOSITE",
        period_start=facts[0].period_start,
        period_end=facts[-1].period_end,
        materialization_ids=[window.materialization_id for window in windows],
        return_view="GROSS",
    )
    return facts, windows, request


def _calculate(monkeypatch, returns, *, status="READY"):
    facts, windows, request = _inputs(returns, status=status)
    monkeypatch.setattr(application, "select_composite_materialization_facts", lambda **kwargs: (facts, windows))
    return application.calculate_linked_member_contribution(request, tenant_id="tenant-a")


def test_exact_zero_cancellation_links_opposing_members_without_residual(monkeypatch):
    response = _calculate(monkeypatch, ("1", "-0.5"))
    with localcontext() as context:
        context.prec = 90
        expected = Decimal(2).ln()
        assert abs(response.members[0].linked_contribution - expected) < Decimal("1e-70")
        assert abs(response.members[1].linked_contribution + expected) < Decimal("1e-70")
    assert response.cumulative_return == 0
    assert abs(response.total_linked_contribution) < Decimal("1e-70")
    assert abs(response.reconciliation_difference) < Decimal("1e-70")


def test_decimal_precision_exhaustion_refuses_without_manufactured_total(monkeypatch):
    # Each period is inside the domain; subtracting one from their tiny linked
    # growth loses the domain at the declared 80-digit budget, so refuse explicitly.
    ret = "-0." + "9" * 45
    with pytest.raises(APIUnprocessableEntityError) as error:
        _calculate(monkeypatch, (ret, ret))
    assert error.value.error_code == "COMPOSITE_CARINO_PRECISION_REFUSED"


def test_unavailable_constituents_do_not_become_zero_rows(monkeypatch):
    with pytest.raises(APIUnprocessableEntityError) as error:
        _calculate(monkeypatch, ("0.01",), status="BLOCKED")
    assert error.value.error_code == "COMPOSITE_CONSTITUENT_DECOMPOSITION_UNAVAILABLE"


def test_display_precision_overflow_is_a_typed_refusal(monkeypatch):
    with pytest.raises(APIUnprocessableEntityError) as error:
        _calculate(monkeypatch, ("1e90",))
    assert error.value.error_code == "COMPOSITE_CARINO_PRECISION_REFUSED"


def test_large_growth_cancellation_fails_absolute_reconciliation_budget(monkeypatch):
    with pytest.raises(APIUnprocessableEntityError) as error:
        _calculate(monkeypatch, ("1e20", "2e20", "3e20"))
    assert error.value.error_code == "COMPOSITE_CARINO_PRECISION_REFUSED"


def test_caller_decimal_state_cannot_change_dataset_or_fingerprint(monkeypatch):
    facts, windows, request = _inputs(("0.01", "0.02"))
    monkeypatch.setattr(application, "select_composite_materialization_facts", lambda **kwargs: (facts, windows))
    baseline = application.calculate_linked_member_contribution(request, tenant_id="tenant-a")
    for rounding in (ROUND_DOWN, ROUND_UP):
        with localcontext() as caller:
            caller.prec = 9
            caller.rounding = rounding
            caller.traps[Inexact] = True
            caller.Emin, caller.Emax = -9, 9
            actual = application.calculate_linked_member_contribution(request, tenant_id="tenant-a")
            assert actual == baseline
            assert caller.prec == 9 and caller.rounding == rounding and caller.traps[Inexact]
