"""Original numerical controls invoke the existing MWR kernel through its service."""

from datetime import date
from decimal import Decimal, localcontext

import pytest

from app.ports.composite_pooled_mwr import PooledSourceAdmissionError
from app.services.composite_pooled_mwr.solver_adapter import calculate_pooled_xirr
from tests.unit.services.test_composite_pooled_mwr_admission import (
    _admit,
    _flow,
    _with_flows,
    controlled_request,
    controlled_source_payload,
)


def test_original_or15_invokes_existing_solver_and_converts_percent_once():
    request = controlled_request()
    result = calculate_pooled_xirr(request, _admit(controlled_source_payload(), request))
    assert result.availability == "AVAILABLE" and result.actual_method == "XIRR"
    assert abs(result.return_value - Decimal("0.10")) < Decimal("1e-9")
    assert abs(Decimal(str(result.original_solver_result["mwr"])) - Decimal(10)) < Decimal("1e-7")
    assert result.units == "DECIMAL_FRACTION" and result.root_precision == "FLOAT64"
    assert result.diagnostics["actual_algorithm"] == "log_rate_bracket_scan_bisection"
    assert result.diagnostics["solver_control_method"] == "brent"
    convergence = result.diagnostics["convergence"]
    assert convergence["converged"] and convergence["root_count_detected"] == 1
    assert convergence["uniqueness_supported"] and not convergence["non_simple_root_detected"]
    assert abs(convergence["residual_npv"]) < 1e-7
    assert result.diagnostics["resolved_year_divisor"] == 365
    assert [row["year_fraction"] for row in result.diagnostics["time_axis"]] == [0, 1]
    assert result.diagnostics["actual_interval_start"] == date(2025, 1, 1)
    assert result.diagnostics["actual_interval_end"] == date(2026, 1, 1)


def test_unequal_member_money_is_pooled_without_averaging_member_irrs():
    payload = controlled_source_payload()
    for row in payload["valuations"]:
        row["amount"] = {
            ("member-a", "OPENING"): "90",
            ("member-a", "TERMINAL"): "108",
            ("member-b", "OPENING"): "10",
            ("member-b", "TERMINAL"): "9",
        }[(row["portfolio_id"], row["role"])]
    result = calculate_pooled_xirr(controlled_request(), _admit(payload))
    assert abs(result.return_value - Decimal("0.17")) < Decimal("1e-9")
    assert abs(result.return_value - Decimal("0.05")) > Decimal("0.1")


def two_year_fixture(*, flow="100", terminal_a="121", terminal_b="220", fallback="REQUIRE_XIRR"):
    request = controlled_request().model_copy(update={"period_end": date(2027, 1, 1), "fallback_policy": fallback})
    payload = controlled_source_payload()
    payload["period_end"] = "2027-01-01"
    payload["policy"]["fallback_policy"] = fallback
    for pin in payload["source_pins"]:
        pin["coverage_to"] = "2027-01-01"
    for member in payload["membership"]:
        member["effective_to"] = "2027-01-01"
    for coverage in payload["flow_coverage"]:
        coverage["coverage_to"] = "2027-01-01"
    for row in payload["valuations"]:
        if row["role"] == "OPENING":
            row["amount"] = "100"
        else:
            row["economic_date"] = "2027-01-01"
            row["amount"] = terminal_a if row["portfolio_id"] == "member-a" else terminal_b
    _with_flows(payload, [_flow(member="member-b", amount=flow, economic_date="2026-01-01", source_date="2026-01-01")])
    return request, payload


def test_dated_flow_pool_differs_from_even_beginning_weighted_member_irrs():
    request, payload = two_year_fixture()
    observation = _admit(payload, request)
    assert [row.amount for row in observation.investor_cash_flows] == [Decimal(-200), Decimal(-100), Decimal(341)]
    result = calculate_pooled_xirr(request, observation)
    assert result.availability == "AVAILABLE"
    reference = Decimal("0.0794735800308331061377877548969028459657461134194723829049719890641170933150104")
    wrong_mean = Decimal("0.0826237921249263937432107840559466824042164258640340034948140358936823239732317")
    assert abs(result.return_value - reference) < Decimal("1e-9")
    assert abs(result.return_value - wrong_mean) > Decimal("0.003")
    assert [row["year_fraction"] for row in result.diagnostics["time_axis"]] == [0, 1, 2]


def ambiguous_fixture(*, fallback="REQUIRE_XIRR", terminal="-132"):
    request, payload = two_year_fixture(flow="-230", terminal_a=terminal, terminal_b="0", fallback=fallback)
    for row in payload["valuations"]:
        if row["role"] == "OPENING":
            row["amount"] = "100" if row["portfolio_id"] == "member-a" else "0"
    return request, payload


def test_ambiguous_xirr_preserves_failure_and_never_inherits_dietz_success():
    request, payload = ambiguous_fixture()
    result = calculate_pooled_xirr(request, _admit(payload, request))
    assert result.availability == "NOT_CALCULABLE"
    assert result.return_value is result.annualized_return is result.holding_period_return is None
    assert result.diagnostics["convergence"]["root_count_detected"] >= 2
    assert not result.diagnostics["convergence"]["converged"]
    assert result.original_solver_result["method"] == "MODIFIED_DIETZ"
    assert result.original_solver_result["status"] == "FALLBACK_USED"


def test_explicit_elected_fallback_names_actual_method_and_retains_xirr_reason():
    request, payload = ambiguous_fixture(fallback="ALLOW_MODIFIED_DIETZ")
    result = calculate_pooled_xirr(request, _admit(payload, request))
    assert result.availability == "FALLBACK_ANALYSIS" and result.actual_method == "MODIFIED_DIETZ"
    assert result.return_value is not None
    assert result.diagnostics["fallback_from"] == "XIRR"
    assert result.diagnostics["fallback_reason"]
    assert not result.diagnostics["convergence"]["converged"]


def test_zero_content_and_one_sided_vector_have_no_published_xirr():
    for zero in (False, True):
        payload = controlled_source_payload()
        for row in payload["valuations"]:
            if zero or row["role"] == "TERMINAL":
                row["amount"] = "0"
        result = calculate_pooled_xirr(controlled_request(), _admit(payload))
        assert result.availability == "NOT_CALCULABLE" and result.return_value is None
        assert result.reason_codes


def test_percentage_conversion_preserves_service_output_under_low_caller_precision():
    request = controlled_request()
    observation = _admit(controlled_source_payload())
    with localcontext() as context:
        context.prec = 4
        result = calculate_pooled_xirr(request, observation)
    percentage = Decimal(str(result.original_solver_result["mwr"]))
    with localcontext() as context:
        context.prec = 80
        assert result.return_value == percentage / 100


def test_work_limit_failure_remains_noncalculable_with_actual_controls():
    request = controlled_request().model_copy(
        update={"solver": controlled_request().solver.model_copy(update={"max_iter": 1, "tolerance": 1e-30})}
    )
    result = calculate_pooled_xirr(request, _admit(controlled_source_payload(), request))
    assert result.availability == "NOT_CALCULABLE" and result.return_value is None
    assert result.diagnostics["convergence"]["max_iterations"] == 1
    assert result.diagnostics["convergence"]["tolerance"] == 1e-30


@pytest.mark.parametrize("basis", ["ACT/ACT", "BUS/252"])
def test_unsupported_pooled_date_basis_refuses_before_existing_solver(basis):
    request = controlled_request().model_copy(
        update={"annualization": controlled_request().annualization.model_copy(update={"basis": basis})}
    )
    payload = controlled_source_payload()
    payload["policy"]["day_count_basis"] = basis
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(payload, request)
    assert error.value.code == "METHOD_DATE_BASIS_UNSUPPORTED"
    with pytest.raises(PooledSourceAdmissionError) as error:
        calculate_pooled_xirr(request, _admit(controlled_source_payload()))
    assert error.value.code == "METHOD_DATE_BASIS_UNSUPPORTED"


def test_decimal_source_outside_finite_float64_root_domain_is_explicit_not_calculable():
    payload = controlled_source_payload()
    payload["valuations"][0]["amount"] = "1E400"
    observation = _admit(payload)
    result = calculate_pooled_xirr(controlled_request(), observation)
    assert result.availability == "NOT_CALCULABLE" and result.return_value is None
    assert result.reason_codes == ("NUMERICAL_DOMAIN_UNSUPPORTED",)
    assert result.original_solver_result["error_type"] == "NumericalDomainError"
    assert observation.source_bundle.valuations[0].amount == Decimal("1E400")


def test_non_simple_root_is_not_published_as_converged_xirr():
    request, payload = ambiguous_fixture(terminal="-121")
    payload["flows"][0]["amount"] = "-220"
    result = calculate_pooled_xirr(request, _admit(payload, request))
    assert result.availability == "NOT_CALCULABLE" and result.return_value is None
    assert result.diagnostics["convergence"]["non_simple_root_detected"]
