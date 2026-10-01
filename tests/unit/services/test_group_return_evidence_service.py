from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.models.benchmark_requests import BenchmarkComponentObservation
from app.models.group_return_evidence import (
    GroupReturnEvidenceGrouping,
    GroupReturnEvidenceRequest,
    GroupReturnEvidenceWindow,
)
from app.services import group_return_evidence_service
from app.services.group_return_evidence_service import (
    GroupReturnEvidenceSourceInput,
    build_group_return_evidence_response,
)
from app.services.stateful_performance_input_service import StatefulPortfolioInput


def _request() -> GroupReturnEvidenceRequest:
    return GroupReturnEvidenceRequest(
        calculation_id=UUID("00000000-0000-0000-0000-000000000571"),
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        benchmark_id="BMK_GLOBAL_BALANCED",
        as_of_date=date(2026, 4, 10),
        window=GroupReturnEvidenceWindow(start_date=date(2026, 4, 1), end_date=date(2026, 4, 2)),
        grouping_dimension=GroupReturnEvidenceGrouping.SECTOR,
        reporting_currency="USD",
    )


def _source_input() -> GroupReturnEvidenceSourceInput:
    return GroupReturnEvidenceSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2020, 1, 1),
            portfolio_currency="USD",
            reporting_currency="USD",
            observations=[
                {
                    "valuation_date": "2026-04-01",
                    "beginning_market_value": "1000",
                    "ending_market_value": "1014",
                },
                {
                    "valuation_date": "2026-04-02",
                    "beginning_market_value": "1014",
                    "ending_market_value": "1011.1608",
                },
            ],
        ),
        position_rows=[
            {
                "position_id": "EQ_1",
                "valuation_date": "2026-04-01",
                "beginning_market_value_reporting_currency": "600",
                "ending_market_value_reporting_currency": "612",
                "position_currency": "USD",
                "cash_flow_currency": "USD",
                "cash_flows": [],
                "dimensions": {"sector": "Equity"},
            },
            {
                "position_id": "FI_1",
                "valuation_date": "2026-04-01",
                "beginning_market_value_reporting_currency": "400",
                "ending_market_value_reporting_currency": "402",
                "position_currency": "USD",
                "cash_flow_currency": "USD",
                "cash_flows": [],
                "dimensions": {"sector": "Fixed Income"},
            },
            {
                "position_id": "EQ_1",
                "valuation_date": "2026-04-02",
                "beginning_market_value_reporting_currency": "612",
                "ending_market_value_reporting_currency": "605.88",
                "position_currency": "USD",
                "cash_flow_currency": "USD",
                "cash_flows": [],
                "dimensions": {"sector": "Equity"},
            },
            {
                "position_id": "FI_1",
                "valuation_date": "2026-04-02",
                "beginning_market_value_reporting_currency": "402",
                "ending_market_value_reporting_currency": "405.2808",
                "position_currency": "USD",
                "cash_flow_currency": "USD",
                "cash_flows": [],
                "dimensions": {"sector": "Fixed Income"},
            },
        ],
        position_source_rows_complete=True,
        benchmark_id="BMK_GLOBAL_BALANCED",
        benchmark_currency="USD",
        benchmark_component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_EQUITY",
                perf_date=date(2026, 4, 1),
                weight_bop=0.5,
                component_return=0.01,
                component_currency="USD",
            ),
            BenchmarkComponentObservation(
                component_id="IDX_FIXED_INCOME",
                perf_date=date(2026, 4, 1),
                weight_bop=0.5,
                component_return=0.002,
                component_currency="USD",
            ),
            BenchmarkComponentObservation(
                component_id="IDX_EQUITY",
                perf_date=date(2026, 4, 2),
                weight_bop=0.5,
                component_return=-0.008,
                component_currency="USD",
            ),
            BenchmarkComponentObservation(
                component_id="IDX_FIXED_INCOME",
                perf_date=date(2026, 4, 2),
                weight_bop=0.5,
                component_return=0.006,
                component_currency="USD",
            ),
        ],
        index_records=[
            {"index_id": "IDX_EQUITY", "classification_labels": {"sector": "Equity"}},
            {"index_id": "IDX_FIXED_INCOME", "classification_labels": {"sector": "Fixed Income"}},
        ],
    )


def test_group_return_evidence_reconciles_heterogeneous_and_negative_active_contributions() -> None:
    response = build_group_return_evidence_response(
        request=_request(),
        source_input=_source_input(),
        source_snapshots=[
            {
                "upstream_endpoint": "portfolio_timeseries",
                "source_identifier": "PB_SG_GLOBAL_BAL_001",
                "as_of_date": "2026-04-10",
                "request_fingerprint": "portfolio-request",
                "response_fingerprint": "portfolio-response",
                "retrieval_status": "200",
            },
            {
                "upstream_endpoint": "position_timeseries",
                "source_identifier": "PB_SG_GLOBAL_BAL_001",
                "as_of_date": "2026-04-10",
                "request_fingerprint": "positions-request",
                "response_fingerprint": "positions-response",
                "retrieval_status": "200",
            },
        ],
    )

    assert response.coverage.status == "COMPLETE"
    assert response.reporting_currency == "USD"
    assert response.return_basis == "SOURCE_POSITION_AND_BENCHMARK_COMPONENT_GROSS_TWR"
    assert response.valuation_basis == "SOURCE_REPORTED_BEGINNING_AND_ENDING_MARKET_VALUES"
    assert response.weight_basis == "SIGNED_BEGINNING_CAPITAL_AND_BENCHMARK_BOP_WEIGHT"
    assert response.source_lineage.snapshots[0].as_of_date == date(2026, 4, 10)
    assert [(item.date, item.portfolio_return, item.benchmark_return) for item in response.aggregate_returns] == [
        (date(2026, 4, 1), Decimal("0.014"), Decimal("0.006")),
        (date(2026, 4, 2), Decimal("-0.0028"), Decimal("-0.001")),
    ]
    active_by_date = {
        aggregate.date: sum(row.active_contribution for row in response.rows if row.date == aggregate.date)
        for aggregate in response.aggregate_returns
    }
    assert active_by_date == {
        date(2026, 4, 1): Decimal("0.008"),
        date(2026, 4, 2): Decimal("-0.0018"),
    }
    assert any(row.active_contribution < 0 for row in response.rows)


def test_group_return_evidence_source_cut_is_stable_for_identical_economics() -> None:
    first = build_group_return_evidence_response(
        request=_request(),
        source_input=_source_input(),
        source_snapshots=[],
    )
    second = build_group_return_evidence_response(
        request=_request().model_copy(update={"calculation_id": UUID("00000000-0000-0000-0000-000000000572")}),
        source_input=_source_input(),
        source_snapshots=[],
    )

    assert first.source_lineage.source_cut_id == second.source_lineage.source_cut_id
    assert first.source_lineage.execution_id != second.source_lineage.execution_id


def test_group_return_evidence_source_cut_changes_when_consumed_source_fingerprint_changes() -> None:
    snapshots = [
        {
            "upstream_endpoint": "portfolio_timeseries",
            "source_identifier": "PB_SG_GLOBAL_BAL_001",
            "as_of_date": "2026-04-10",
            "request_fingerprint": "portfolio-request-v1",
            "response_fingerprint": "portfolio-response-v1",
            "retrieval_status": "200",
        }
    ]
    first = build_group_return_evidence_response(
        request=_request(),
        source_input=_source_input(),
        source_snapshots=snapshots,
    )
    restated = build_group_return_evidence_response(
        request=_request(),
        source_input=_source_input(),
        source_snapshots=[{**snapshots[0], "response_fingerprint": "portfolio-response-v2"}],
    )

    assert restated.source_lineage.source_cut_id != first.source_lineage.source_cut_id


def test_group_return_evidence_source_cut_changes_for_restatement_or_portfolio_scope() -> None:
    first = build_group_return_evidence_response(
        request=_request(),
        source_input=_source_input(),
        source_snapshots=[],
    )
    restated_source = _source_input()
    restated_components = [
        component.model_copy(update={"component_return": 0.011})
        if component.component_id == "IDX_EQUITY" and component.perf_date == date(2026, 4, 1)
        else component
        for component in restated_source.benchmark_component_observations
    ]
    restated = build_group_return_evidence_response(
        request=_request(),
        source_input=GroupReturnEvidenceSourceInput(
            **{**restated_source.__dict__, "benchmark_component_observations": restated_components}
        ),
        source_snapshots=[],
    )
    other_portfolio = build_group_return_evidence_response(
        request=_request().model_copy(update={"portfolio_id": "PB_SG_OTHER_TENANT_001"}),
        source_input=_source_input(),
        source_snapshots=[],
    )

    assert restated.source_lineage.source_cut_id != first.source_lineage.source_cut_id
    assert other_portfolio.source_lineage.source_cut_id != first.source_lineage.source_cut_id


def test_group_return_evidence_preserves_zero_exposure_only_from_complete_source_calendar() -> None:
    source_input = _source_input()
    zero_rows = [
        {
            "position_id": "ZERO_EXPOSURE",
            "valuation_date": observation_date,
            "beginning_market_value_reporting_currency": "0",
            "ending_market_value_reporting_currency": "0",
            "position_currency": "USD",
            "cash_flow_currency": "USD",
            "cash_flows": [],
            "dimensions": {"sector": "Alternatives"},
        }
        for observation_date in ("2026-04-01", "2026-04-02")
    ]
    response = build_group_return_evidence_response(
        request=_request(),
        source_input=GroupReturnEvidenceSourceInput(
            **{**source_input.__dict__, "position_rows": [*source_input.position_rows, *zero_rows]}
        ),
        source_snapshots=[],
    )

    zero_rows_response = [row for row in response.rows if row.group_id == "SECTOR:alternatives"]
    assert [
        (row.portfolio_weight, row.portfolio_group_return, row.active_contribution) for row in zero_rows_response
    ] == [
        (Decimal("0"), Decimal("0"), Decimal("0")),
        (Decimal("0"), Decimal("0"), Decimal("0")),
    ]


def test_group_return_evidence_treats_canonical_income_as_source_return_not_external_flow() -> None:
    request = _request().model_copy(
        update={
            "window": GroupReturnEvidenceWindow(start_date=date(2026, 4, 1), end_date=date(2026, 4, 1)),
        }
    )
    source_input = GroupReturnEvidenceSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2020, 1, 1),
            portfolio_currency="USD",
            reporting_currency="USD",
            observations=[
                {
                    "valuation_date": "2026-04-01",
                    "beginning_market_value": "1300000",
                    "ending_market_value": "1300850",
                }
            ],
        ),
        position_rows=[
            {
                "position_id": "INCOME_ASSET",
                "valuation_date": "2026-04-01",
                "beginning_market_value_reporting_currency": "100000",
                "ending_market_value_reporting_currency": "100000",
                "position_currency": "USD",
                "cash_flow_currency": "USD",
                "cash_flows": [{"amount": "-850", "timing": "eod", "cash_flow_type": "income"}],
                "dimensions": {"sector": "Fixed Income"},
            },
            {
                "position_id": "CASH",
                "valuation_date": "2026-04-01",
                "beginning_market_value_reporting_currency": "100000",
                "ending_market_value_reporting_currency": "100850",
                "position_currency": "USD",
                "cash_flow_currency": "USD",
                "cash_flows": [{"amount": "850", "timing": "bod", "cash_flow_type": "internal_trade_flow"}],
                "dimensions": {"sector": "Cash"},
            },
            {
                "position_id": "OTHER",
                "valuation_date": "2026-04-01",
                "beginning_market_value_reporting_currency": "1100000",
                "ending_market_value_reporting_currency": "1100000",
                "position_currency": "USD",
                "cash_flow_currency": "USD",
                "cash_flows": [],
                "dimensions": {"sector": "Other"},
            },
        ],
        position_source_rows_complete=True,
        benchmark_id="BMK_GLOBAL_BALANCED",
        benchmark_currency="USD",
        benchmark_component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_OTHER",
                perf_date=date(2026, 4, 1),
                weight_bop=1,
                component_return=0,
                component_currency="USD",
            )
        ],
        index_records=[{"index_id": "IDX_OTHER", "classification_labels": {"sector": "Other"}}],
    )

    response = build_group_return_evidence_response(
        request=request,
        source_input=source_input,
        source_snapshots=[],
    )

    fixed_income = next(row for row in response.rows if row.group_id == "SECTOR:fixed_income")
    assert fixed_income.portfolio_group_return == Decimal("0.0085")
    assert response.aggregate_returns[0].portfolio_return == Decimal("850") / Decimal("1300000")


def test_group_return_evidence_refuses_currency_mismatch_without_inventing_fx() -> None:
    source_input = _source_input()
    mismatch = GroupReturnEvidenceSourceInput(
        **{**source_input.__dict__, "benchmark_currency": "EUR"},
    )

    with pytest.raises(ValueError, match="currency"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=mismatch,
            source_snapshots=[],
        )


def test_group_return_evidence_preserves_signed_hedge_group_economics() -> None:
    request = _request().model_copy(
        update={"window": GroupReturnEvidenceWindow(start_date=date(2026, 4, 1), end_date=date(2026, 4, 1))}
    )
    source_input = GroupReturnEvidenceSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2020, 1, 1),
            portfolio_currency="USD",
            reporting_currency="USD",
            observations=[
                {
                    "valuation_date": "2026-04-01",
                    "beginning_market_value": "1000",
                    "ending_market_value": "1010",
                }
            ],
        ),
        position_rows=[
            {
                "position_id": "EQUITY",
                "valuation_date": "2026-04-01",
                "beginning_market_value_reporting_currency": "1100",
                "ending_market_value_reporting_currency": "1122",
                "position_currency": "USD",
                "cash_flow_currency": "USD",
                "cash_flows": [],
                "dimensions": {"sector": "Equity"},
            },
            {
                "position_id": "FX_HEDGE",
                "valuation_date": "2026-04-01",
                "beginning_market_value_reporting_currency": "-100",
                "ending_market_value_reporting_currency": "-112",
                "position_currency": "USD",
                "cash_flow_currency": "USD",
                "cash_flows": [],
                "dimensions": {"sector": "FX Hedge"},
            },
        ],
        position_source_rows_complete=True,
        benchmark_id="BMK_GLOBAL_BALANCED",
        benchmark_currency="USD",
        benchmark_component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_EQUITY",
                perf_date=date(2026, 4, 1),
                weight_bop=0.9,
                component_return=0.005,
                component_currency="USD",
            ),
            BenchmarkComponentObservation(
                component_id="IDX_FX_HEDGE",
                perf_date=date(2026, 4, 1),
                weight_bop=0.1,
                component_return=0,
                component_currency="USD",
            ),
        ],
        index_records=[
            {"index_id": "IDX_EQUITY", "classification_labels": {"sector": "Equity"}},
            {"index_id": "IDX_FX_HEDGE", "classification_labels": {"sector": "FX Hedge"}},
        ],
    )

    response = build_group_return_evidence_response(
        request=request,
        source_input=source_input,
        source_snapshots=[],
    )

    hedge = next(row for row in response.rows if row.group_id == "SECTOR:fx_hedge")
    assert hedge.portfolio_weight == Decimal("-0.1")
    assert hedge.portfolio_group_return == Decimal("0.12")
    assert hedge.active_contribution == Decimal("-0.012")
    assert response.aggregate_returns[0].active_return == Decimal("0.0055")
    assert response.aggregate_returns[0].group_active_contribution_delta == Decimal("0")


def test_group_return_evidence_refuses_conflicting_labels_or_failed_source_snapshot() -> None:
    source_input = _source_input()
    conflicting_rows = [
        {**row, "dimensions": {"sector": "Fixed income"}} if row["position_id"] == "FI_1" else row
        for row in source_input.position_rows
    ]

    with pytest.raises(ValueError, match="conflicting source labels"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(**{**source_input.__dict__, "position_rows": conflicting_rows}),
            source_snapshots=[],
        )

    with pytest.raises(ValueError, match="failed upstream source snapshot"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=source_input,
            source_snapshots=[
                {
                    "upstream_endpoint": "portfolio_timeseries",
                    "source_identifier": "PB_SG_GLOBAL_BAL_001",
                    "as_of_date": "2026-04-10",
                    "request_fingerprint": "portfolio-request",
                    "response_fingerprint": "portfolio-response",
                    "retrieval_status": "503",
                }
            ],
        )


def test_group_return_evidence_refuses_incomplete_rows_or_a_different_requested_benchmark() -> None:
    source_input = _source_input()

    with pytest.raises(ValueError, match="complete retained position source rows"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{**source_input.__dict__, "position_source_rows_complete": False}
            ),
            source_snapshots=[],
        )

    with pytest.raises(ValueError, match="requested benchmark_id"):
        build_group_return_evidence_response(
            request=_request().model_copy(update={"benchmark_id": "BMK_OTHER"}),
            source_input=source_input,
            source_snapshots=[],
        )


def test_group_return_evidence_refuses_duplicate_or_calendar_misaligned_source_facts() -> None:
    source_input = _source_input()

    with pytest.raises(ValueError, match="duplicate position source observation"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{
                    **source_input.__dict__,
                    "position_rows": [*source_input.position_rows, source_input.position_rows[0]],
                }
            ),
            source_snapshots=[],
        )

    with pytest.raises(ValueError, match="duplicate benchmark component observation"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{
                    **source_input.__dict__,
                    "benchmark_component_observations": [
                        *source_input.benchmark_component_observations,
                        source_input.benchmark_component_observations[0],
                    ],
                }
            ),
            source_snapshots=[],
        )

    with pytest.raises(ValueError, match="calendars are not aligned"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{
                    **source_input.__dict__,
                    "benchmark_component_observations": source_input.benchmark_component_observations[:2],
                }
            ),
            source_snapshots=[],
        )


def test_group_return_evidence_requires_source_classification_and_reconciled_benchmark_weights() -> None:
    source_input = _source_input()
    currency_response = build_group_return_evidence_response(
        request=_request().model_copy(update={"grouping_dimension": GroupReturnEvidenceGrouping.CURRENCY}),
        source_input=source_input,
        source_snapshots=[],
    )
    assert {(row.group_id, row.group_label) for row in currency_response.rows} == {("CURRENCY:usd", "USD")}

    with pytest.raises(ValueError, match="benchmark source is missing"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{
                    **source_input.__dict__,
                    "index_records": [{"index_id": "IDX_EQUITY", "classification_labels": {}}],
                }
            ),
            source_snapshots=[],
        )

    incorrect_weights = [
        component.model_copy(update={"weight_bop": Decimal("0.4")})
        if component.component_id == "IDX_EQUITY" and component.perf_date == date(2026, 4, 1)
        else component
        for component in source_input.benchmark_component_observations
    ]
    with pytest.raises(ValueError, match="weights do not reconcile to one"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{**source_input.__dict__, "benchmark_component_observations": incorrect_weights}
            ),
            source_snapshots=[],
        )


def test_group_return_evidence_refuses_unreconciled_position_economics_and_keeps_object_lineage() -> None:
    source_input = _source_input()
    unreconciled_observations = [
        {**observation, "ending_market_value": "1015"} if observation["valuation_date"] == "2026-04-01" else observation
        for observation in source_input.portfolio_input.observations
    ]
    with pytest.raises(ValueError, match="do not reconcile to the portfolio source valuations"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{
                    **source_input.__dict__,
                    "portfolio_input": StatefulPortfolioInput(
                        performance_start_date=source_input.portfolio_input.performance_start_date,
                        portfolio_currency="USD",
                        reporting_currency="USD",
                        observations=unreconciled_observations,
                    ),
                }
            ),
            source_snapshots=[],
        )

    response = build_group_return_evidence_response(
        request=_request(),
        source_input=source_input,
        source_snapshots=[
            SimpleNamespace(
                upstream_endpoint="portfolio_timeseries",
                source_identifier="PB_SG_GLOBAL_BAL_001",
                as_of_date="2026-04-10",
                request_fingerprint="request-fingerprint",
                response_fingerprint="response-fingerprint",
                retrieval_status="200",
            )
        ],
    )
    assert response.source_lineage.snapshots[0].as_of_date == date(2026, 4, 10)


def test_group_return_evidence_refuses_incomplete_or_malformed_position_source_shape() -> None:
    source_input = _source_input()
    request_with_later_end = _request().model_copy(
        update={"window": GroupReturnEvidenceWindow(start_date=date(2026, 4, 1), end_date=date(2026, 4, 3))}
    )
    position_outside_portfolio_calendar = [
        {**row, "valuation_date": "2026-04-03"} if row["position_id"] == "EQ_1" else row
        for row in source_input.position_rows
    ]
    with pytest.raises(ValueError, match="not present in the portfolio source calendar"):
        build_group_return_evidence_response(
            request=request_with_later_end,
            source_input=GroupReturnEvidenceSourceInput(
                **{**source_input.__dict__, "position_rows": position_outside_portfolio_calendar}
            ),
            source_snapshots=[],
        )

    with pytest.raises(ValueError, match="at least one complete position"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(**{**source_input.__dict__, "position_rows": []}),
            source_snapshots=[],
        )

    duplicate_portfolio_calendar = [
        *source_input.portfolio_input.observations,
        source_input.portfolio_input.observations[0],
    ]
    with pytest.raises(ValueError, match="duplicate portfolio source observation"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{
                    **source_input.__dict__,
                    "portfolio_input": replace(
                        source_input.portfolio_input,
                        observations=duplicate_portfolio_calendar,
                    ),
                }
            ),
            source_snapshots=[],
        )

    with pytest.raises(ValueError, match="requires portfolio source observations"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{
                    **source_input.__dict__,
                    "portfolio_input": replace(source_input.portfolio_input, observations=[]),
                }
            ),
            source_snapshots=[],
        )

    without_stable_position_identity = [
        {key: value for key, value in source_input.position_rows[0].items() if key != "position_id"}
    ]
    with pytest.raises(ValueError, match="missing a stable position identity"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{**source_input.__dict__, "position_rows": without_stable_position_identity}
            ),
            source_snapshots=[],
        )

    incomplete_cashflow_economics = [{**source_input.position_rows[0], "cash_flows": None}]
    with pytest.raises(ValueError, match="cash-flow economics are incomplete"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{**source_input.__dict__, "position_rows": incomplete_cashflow_economics}
            ),
            source_snapshots=[],
        )

    with pytest.raises(ValueError, match="portfolio source date has no position evidence"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{**source_input.__dict__, "position_rows": source_input.position_rows[:2]}
            ),
            source_snapshots=[],
        )


def test_group_return_evidence_refuses_unreconciled_capital_or_invalid_source_values() -> None:
    source_input = _source_input()
    one_day_request = _request().model_copy(
        update={"window": GroupReturnEvidenceWindow(start_date=date(2026, 4, 1), end_date=date(2026, 4, 1))}
    )
    negative_capital_positions = [
        {**row, "beginning_market_value_reporting_currency": "-100", "ending_market_value_reporting_currency": "-100"}
        for row in source_input.position_rows[:1]
    ]
    with pytest.raises(ValueError, match="beginning capital must be positive"):
        build_group_return_evidence_response(
            request=one_day_request,
            source_input=GroupReturnEvidenceSourceInput(
                **{
                    **source_input.__dict__,
                    "portfolio_input": replace(
                        source_input.portfolio_input,
                        observations=[
                            {
                                "valuation_date": "2026-04-01",
                                "beginning_market_value": "-100",
                                "ending_market_value": "-100",
                            }
                        ],
                    ),
                    "position_rows": negative_capital_positions,
                    "benchmark_component_observations": source_input.benchmark_component_observations[:2],
                }
            ),
            source_snapshots=[],
        )

    first_position_with_bod_external_flow = {
        **source_input.position_rows[0],
        "cash_flows": [{"amount": "100", "timing": "bod", "cash_flow_type": "external_flow"}],
    }
    with pytest.raises(ValueError, match="weighted portfolio group economics"):
        build_group_return_evidence_response(
            request=one_day_request,
            source_input=GroupReturnEvidenceSourceInput(
                **{
                    **source_input.__dict__,
                    "portfolio_input": replace(
                        source_input.portfolio_input,
                        observations=source_input.portfolio_input.observations[:1],
                    ),
                    "position_rows": [first_position_with_bod_external_flow, source_input.position_rows[1]],
                    "benchmark_component_observations": source_input.benchmark_component_observations[:2],
                }
            ),
            source_snapshots=[],
        )

    malformed_position_date = [{**source_input.position_rows[0], "valuation_date": 20260401}]
    with pytest.raises(ValueError, match="missing an ISO business date"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{**source_input.__dict__, "position_rows": malformed_position_date}
            ),
            source_snapshots=[],
        )

    invalid_position_date = [{**source_input.position_rows[0], "valuation_date": "2026-13-01"}]
    with pytest.raises(ValueError, match="invalid ISO business date"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{**source_input.__dict__, "position_rows": invalid_position_date}
            ),
            source_snapshots=[],
        )

    non_finite_position_value = [{**source_input.position_rows[0], "beginning_market_value_reporting_currency": "NaN"}]
    with pytest.raises(ValueError, match="finite decimal"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{**source_input.__dict__, "position_rows": non_finite_position_value}
            ),
            source_snapshots=[],
        )

    invalid_numeric_position_value = [
        {**source_input.position_rows[0], "beginning_market_value_reporting_currency": "bad-number"}
    ]
    with pytest.raises(ValueError, match="finite decimal"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{**source_input.__dict__, "position_rows": invalid_numeric_position_value}
            ),
            source_snapshots=[],
        )

    position_outside_requested_window = [{**source_input.position_rows[0], "valuation_date": "2026-04-03"}]
    with pytest.raises(ValueError, match="falls outside the requested window"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{**source_input.__dict__, "position_rows": position_outside_requested_window}
            ),
            source_snapshots=[],
        )


def test_group_return_evidence_refuses_zero_capital_or_missing_benchmark_source_facts() -> None:
    source_input = _source_input()
    one_day_request = _request().model_copy(
        update={"window": GroupReturnEvidenceWindow(start_date=date(2026, 4, 1), end_date=date(2026, 4, 1))}
    )
    zero_capital_position = {
        **source_input.position_rows[0],
        "beginning_market_value_reporting_currency": "0",
        "ending_market_value_reporting_currency": "0",
    }
    with pytest.raises(ValueError, match="zero capital"):
        build_group_return_evidence_response(
            request=one_day_request,
            source_input=GroupReturnEvidenceSourceInput(
                **{
                    **source_input.__dict__,
                    "portfolio_input": replace(
                        source_input.portfolio_input,
                        observations=[
                            {
                                "valuation_date": "2026-04-01",
                                "beginning_market_value": "0",
                                "ending_market_value": "0",
                            }
                        ],
                    ),
                    "position_rows": [zero_capital_position],
                    "benchmark_component_observations": source_input.benchmark_component_observations[:2],
                }
            ),
            source_snapshots=[],
        )

    with pytest.raises(ValueError, match="requires benchmark component return observations"):
        build_group_return_evidence_response(
            request=_request(),
            source_input=GroupReturnEvidenceSourceInput(
                **{**source_input.__dict__, "benchmark_component_observations": []}
            ),
            source_snapshots=[],
        )


def test_group_return_evidence_refuses_a_zero_capital_group_with_nonzero_economics() -> None:
    source_input = _source_input()
    one_day_request = _request().model_copy(
        update={"window": GroupReturnEvidenceWindow(start_date=date(2026, 4, 1), end_date=date(2026, 4, 1))}
    )
    zero_capital_gain = {
        **source_input.position_rows[0],
        "position_id": "ZERO_CAPITAL_GAIN",
        "beginning_market_value_reporting_currency": "0",
        "ending_market_value_reporting_currency": "1",
        "dimensions": {"sector": "Alternatives"},
    }
    with pytest.raises(ValueError, match="zero-capital portfolio group"):
        build_group_return_evidence_response(
            request=one_day_request,
            source_input=GroupReturnEvidenceSourceInput(
                **{
                    **source_input.__dict__,
                    "portfolio_input": replace(
                        source_input.portfolio_input,
                        observations=[
                            {
                                "valuation_date": "2026-04-01",
                                "beginning_market_value": "1000",
                                "ending_market_value": "1015",
                            }
                        ],
                    ),
                    "position_rows": [*source_input.position_rows[:2], zero_capital_gain],
                    "benchmark_component_observations": source_input.benchmark_component_observations[:2],
                }
            ),
            source_snapshots=[],
        )


def test_group_return_evidence_keeps_a_benchmark_only_group_at_zero_portfolio_weight() -> None:
    source_input = _source_input()
    benchmark_observations = [
        component.model_copy(update={"weight_bop": Decimal("0.45")})
        for component in source_input.benchmark_component_observations
    ]
    benchmark_observations.extend(
        [
            BenchmarkComponentObservation(
                component_id="IDX_ALTERNATIVES",
                perf_date=date(2026, 4, 1),
                weight_bop=Decimal("0.1"),
                component_return=Decimal("0.004"),
                component_currency="USD",
            ),
            BenchmarkComponentObservation(
                component_id="IDX_ALTERNATIVES",
                perf_date=date(2026, 4, 2),
                weight_bop=Decimal("0.1"),
                component_return=Decimal("-0.001"),
                component_currency="USD",
            ),
        ]
    )
    response = build_group_return_evidence_response(
        request=_request(),
        source_input=GroupReturnEvidenceSourceInput(
            **{
                **source_input.__dict__,
                "benchmark_component_observations": benchmark_observations,
                "index_records": [
                    *source_input.index_records,
                    {"index_id": "IDX_ALTERNATIVES", "classification_labels": {"sector": "Alternatives"}},
                ],
            }
        ),
        source_snapshots=[],
    )
    assert {row.portfolio_weight for row in response.rows if row.group_id == "SECTOR:alternatives"} == {Decimal("0")}


def test_group_return_evidence_refuses_a_return_calendar_or_group_active_rollup_mutation(monkeypatch) -> None:
    source_input = _source_input()
    with pytest.raises(ValueError, match="return observations do not match"):
        group_return_evidence_service._portfolio_source_returns(
            portfolio_input=source_input.portfolio_input,
            portfolio_dates={date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 3)},
        )

    observation_date = date(2026, 4, 1)
    portfolio_groups = {
        observation_date: {
            "SECTOR:equity": group_return_evidence_service._DailyPortfolioGroup(
                beginning_capital=Decimal("100"),
                ending_value=Decimal("101"),
                bod_cash_flow=Decimal("0"),
                eod_cash_flow=Decimal("0"),
            )
        }
    }
    benchmark_groups = {
        observation_date: {
            "SECTOR:equity": group_return_evidence_service._DailyBenchmarkGroup(
                weight=Decimal("1"),
                contribution=Decimal("0"),
            )
        }
    }
    monkeypatch.setattr(
        group_return_evidence_service,
        "_aligned_rows_for_date",
        lambda **_: [SimpleNamespace(active_contribution=Decimal("0.5"))],
    )
    with pytest.raises(ValueError, match="group active contributions"):
        group_return_evidence_service._aligned_rows_and_aggregates(
            portfolio_groups=portfolio_groups,
            benchmark_groups=benchmark_groups,
            portfolio_dates={observation_date},
            group_labels={"SECTOR:equity": "Equity"},
            source_portfolio_returns={observation_date: Decimal("0.01")},
        )
