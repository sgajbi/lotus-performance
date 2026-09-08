import pytest

from app.services.applied_currency_evidence_service import (
    build_applied_currency_evidence,
    build_source_preconverted_currency_evidence,
)
from core.envelope import FXRequestBlock
from core.errors import APIError


def test_applied_currency_evidence_proves_complete_multi_currency_restatement():
    evidence = build_applied_currency_evidence(
        portfolio_base_currency="usd",
        requested_report_ccy="sgd",
        currency_mode="BOTH",
        fx=FXRequestBlock.model_validate(
            {
                "rates": [
                    {"date": "2025-01-01", "ccy": "USD", "rate": 1.35},
                    {"date": "2025-01-01", "ccy": "EUR", "rate": 1.45},
                ]
            }
        ),
        source_currencies=["USD", "EUR", "SGD"],
    )

    assert evidence.applied_report_ccy == "SGD"
    assert evidence.restated is True
    assert evidence.fx_coverage == "complete"
    assert evidence.applied_pairs == ["EUR/SGD", "USD/SGD"]


def test_applied_currency_evidence_distinguishes_same_currency_from_request_echo():
    evidence = build_applied_currency_evidence(
        portfolio_base_currency="USD",
        requested_report_ccy="USD",
        currency_mode="BOTH",
        fx=None,
        source_currencies=["USD"],
    )

    assert evidence.applied_report_ccy == "USD"
    assert evidence.requested_report_ccy == "USD"
    assert evidence.restated is False
    assert evidence.fx_source == "none"
    assert evidence.reason == "REPORTING_CURRENCY_ALREADY_APPLIED"


def test_applied_currency_evidence_does_not_publish_requested_currency_without_rates():
    with pytest.raises(APIError, match="EUR/SGD"):
        build_applied_currency_evidence(
            portfolio_base_currency="EUR",
            requested_report_ccy="SGD",
            currency_mode="BOTH",
            fx=FXRequestBlock(rates=[]),
            source_currencies=["EUR"],
        )


def test_applied_currency_evidence_refuses_both_mode_without_report_currency():
    with pytest.raises(APIError) as exc_info:
        build_applied_currency_evidence(
            portfolio_base_currency="EUR",
            requested_report_ccy=None,
            currency_mode="BOTH",
            fx=FXRequestBlock.model_validate({"rates": [{"date": "2025-01-01", "ccy": "EUR", "rate": 1.08}]}),
            source_currencies=["EUR"],
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "FX_REPORT_CURRENCY_REQUIRED"


def test_local_only_evidence_ignores_supplied_fx_rates():
    evidence = build_applied_currency_evidence(
        portfolio_base_currency="USD",
        requested_report_ccy="SGD",
        currency_mode="LOCAL_ONLY",
        fx=FXRequestBlock.model_validate({"rates": [{"date": "2025-01-01", "ccy": "USD", "rate": 1.35}]}),
        source_currencies=["USD"],
    )

    assert evidence.currency_mode_applied == "LOCAL_ONLY"
    assert evidence.applied_report_ccy is None
    assert evidence.restated is False
    assert evidence.fx_source == "none"


def test_by_group_evidence_identifies_source_preconverted_return_components():
    evidence = build_source_preconverted_currency_evidence(
        portfolio_base_currency="USD",
        requested_report_ccy="USD",
        currency_mode="BOTH",
        source_currencies=["EUR", "USD"],
        portfolio_observations=[{"return_base": 0.0302, "return_local": 0.02, "return_fx": 0.01}],
        benchmark_observations=[{"return_base": 0.02515, "return_local": 0.015, "return_fx": 0.01}],
    )

    assert evidence.applied_report_ccy == "USD"
    assert evidence.restated is True
    assert evidence.fx_source == "source_preconverted"
    assert evidence.fixing_policy == "SOURCE_PRECONVERTED_RETURN_COMPONENTS"
    assert evidence.applied_pairs == ["EUR/USD"]


def test_by_group_evidence_refuses_incomplete_preconverted_components():
    with pytest.raises(APIError) as exc_info:
        build_source_preconverted_currency_evidence(
            portfolio_base_currency="USD",
            requested_report_ccy="USD",
            currency_mode="BOTH",
            source_currencies=["EUR"],
            portfolio_observations=[{"return_base": 0.0302, "return_local": 0.02}],
            benchmark_observations=[{"return_base": 0.02515, "return_local": 0.015, "return_fx": 0.01}],
        )

    assert exc_info.value.error_code == "FX_SOURCE_PRECONVERTED_EVIDENCE_REQUIRED"


def test_by_group_evidence_refuses_unapplied_requested_report_currency():
    with pytest.raises(APIError) as exc_info:
        build_source_preconverted_currency_evidence(
            portfolio_base_currency="USD",
            requested_report_ccy="SGD",
            currency_mode="BOTH",
            source_currencies=["EUR"],
            portfolio_observations=[{"return_base": 0.0302, "return_local": 0.02, "return_fx": 0.01}],
            benchmark_observations=[{"return_base": 0.02515, "return_local": 0.015, "return_fx": 0.01}],
        )

    assert exc_info.value.error_code == "FX_SOURCE_PRECONVERTED_REPORT_CURRENCY_MISMATCH"


def test_by_group_evidence_refuses_unreconciled_preconverted_components():
    with pytest.raises(APIError) as exc_info:
        build_source_preconverted_currency_evidence(
            portfolio_base_currency="USD",
            requested_report_ccy="USD",
            currency_mode="BOTH",
            source_currencies=["EUR"],
            portfolio_observations=[{"return_base": 0.50, "return_local": 0.02, "return_fx": 0.01}],
            benchmark_observations=[{"return_base": 0.02515, "return_local": 0.015, "return_fx": 0.01}],
        )

    assert exc_info.value.error_code == "FX_SOURCE_PRECONVERTED_EVIDENCE_INCONSISTENT"
