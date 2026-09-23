from datetime import date

import pandas as pd
import pytest

from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import (
    PositionContribution,
    PositionContributionSeries,
    PositionDailyContribution,
)
from app.services.contribution_series import (
    _adjusted_position_hierarchy_records,
    _apply_hierarchy_unclassified_policy,
    _build_hierarchy_from_adjusted_position_series,
    _daily_hierarchy_metadata,
    _group_return_evidence,
    _has_adjusted_hierarchy_inputs,
    _hierarchy_metadata_columns,
    _normalized_source_position_hierarchy_history,
    _other_hierarchy_row_for_emission,
    _prepared_adjusted_hierarchy_frames,
    _proven_position_inception_dates,
    _residual_adjusted_daily_totals_by_date,
    _residual_adjusted_position_rows,
    _target_total_contribution_by_position,
)
from engine.schema import PortfolioColumns


def test_has_adjusted_hierarchy_inputs_requires_hierarchy_period_rows_and_position_series():
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": "2026-03-30",
            "report_end_date": "2026-03-31",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2026-03-30", "begin_mv": 1000, "end_mv": 1010},
                ],
            },
            "positions_data": [
                {
                    "position_id": "SEC_A",
                    "valuation_points": [
                        {"perf_date": "2026-03-30", "begin_mv": 500, "end_mv": 505},
                    ],
                }
            ],
        }
    )
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["SEC_A"],
            PortfolioColumns.PERF_DATE.value: [date(2026, 3, 30)],
            "daily_weight": [0.5],
            "sector": ["Technology"],
        }
    )
    position_series = [
        PositionContributionSeries(
            position_id="SEC_A",
            series=[PositionDailyContribution(date=date(2026, 3, 30), contribution=1.0)],
        )
    ]

    assert _has_adjusted_hierarchy_inputs(
        period_slice_df=period_slice_df,
        position_series=position_series,
        request=request,
    )
    assert not _has_adjusted_hierarchy_inputs(
        period_slice_df=period_slice_df,
        position_series=position_series,
        request=request.model_copy(update={"hierarchy": []}),
    )
    assert not _has_adjusted_hierarchy_inputs(
        period_slice_df=period_slice_df.iloc[0:0],
        position_series=position_series,
        request=request,
    )
    assert not _has_adjusted_hierarchy_inputs(
        period_slice_df=period_slice_df,
        position_series=[],
        request=request,
    )


def test_build_hierarchy_from_adjusted_position_series_uses_observation_date_alignment():
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": "2026-03-30",
            "report_end_date": "2026-03-31",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "emit": {"threshold_weight": 0.0},
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2026-03-30", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2026-03-31", "begin_mv": 1010, "end_mv": 1020},
                ],
            },
            "positions_data": [
                {
                    "position_id": "SEC_A",
                    "valuation_points": [
                        {"perf_date": "2026-03-30", "begin_mv": 500, "end_mv": 505},
                        {"perf_date": "2026-03-31", "begin_mv": 505, "end_mv": 510},
                    ],
                }
            ],
        }
    )
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["SEC_A", "SEC_A"],
            PortfolioColumns.PERF_DATE.value: ["2026-03-30T12:00:00Z", "2026-03-31T12:00:00Z"],
            PortfolioColumns.DAILY_ROR.value: [1.0, 2.0],
            "capital_inst": [500.0, 505.0],
            "daily_weight": [0.5, 0.5],
            "sector": ["Technology", "Technology"],
        }
    )
    position_series = [
        PositionContributionSeries(
            position_id="SEC_A",
            series=[
                PositionDailyContribution(date=date(2026, 3, 30), contribution=1.0),
                PositionDailyContribution(date=date(2026, 3, 31), contribution=2.0),
            ],
        )
    ]

    hierarchy = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=period_slice_df,
        position_series=position_series,
        request=request,
    )

    assert hierarchy["summary"]["portfolio_contribution"] == 3.0
    row = hierarchy["levels"][0]["rows"][0]
    assert row["key"] == {"sector": "Technology"}
    assert row["contribution"] == 3.0
    assert row["weight_avg"] == 50.0
    assert row["group_return"]["status"] == "READY"
    assert row["group_return"]["currency"] == "USD"
    assert row["group_return"]["period_return_pct"] == pytest.approx(3.02)
    assert row["group_return"]["series"] == [
        {"date": date(2026, 3, 30), "return_pct": 1.0, "portfolio_weight_pct": 50.0},
        {"date": date(2026, 3, 31), "return_pct": 2.0, "portfolio_weight_pct": 50.0},
    ]


def test_normalized_source_position_hierarchy_history_discards_malformed_dates():
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": "2026-03-30",
            "report_end_date": "2026-03-31",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "portfolio_data": {"metric_basis": "NET", "valuation_points": []},
            "positions_data": [],
        }
    )
    source_history = pd.DataFrame(
        {
            "position_id": ["SEC_BAD", "SEC_A"],
            PortfolioColumns.PERF_DATE.value: ["not-a-date", "2026-03-30"],
            "sector": ["Invalid", "Technology"],
        }
    )

    normalized = _normalized_source_position_hierarchy_history(
        source_history,
        observation_dates={date(2026, 3, 30)},
        request=request,
    )

    assert normalized is not None
    assert normalized[["position_id", PortfolioColumns.PERF_DATE.value, "sector"]].to_dict("records") == [
        {
            "position_id": "SEC_A",
            PortfolioColumns.PERF_DATE.value: date(2026, 3, 30),
            "sector": "Technology",
        }
    ]


def test_group_return_uses_effective_dated_membership_for_position_reclassification():
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": "2026-03-30",
            "report_end_date": "2026-03-31",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "emit": {"threshold_weight": 0.0},
            "portfolio_data": {"metric_basis": "NET", "valuation_points": []},
            "positions_data": [{"position_id": "SEC_A", "valuation_points": []}],
        }
    )
    source_position_history = pd.DataFrame(
        {
            "position_id": ["SEC_A", "SEC_A"],
            PortfolioColumns.PERF_DATE.value: [date(2026, 3, 30), date(2026, 3, 31)],
            PortfolioColumns.DAILY_ROR.value: [1.0, 2.0],
            PortfolioColumns.BEGIN_MV.value: [500.0, 505.0],
            PortfolioColumns.BOD_CF.value: [0.0, 0.0],
            "capital_inst": [500.0, 505.0],
            "daily_weight": [0.1, 0.9],
            "currency": ["USD", "USD"],
            "sector": ["Sector A", "Sector B"],
        }
    )
    # The production engine projects the position's latest metadata onto every dated
    # calculation row. Source-effective membership must correct that projection before
    # hierarchy aggregation.
    position_rows = source_position_history.assign(sector="Sector B")
    position_series = [
        PositionContributionSeries(
            position_id="SEC_A",
            series=[
                PositionDailyContribution(date=date(2026, 3, 30), contribution=1.0),
                PositionDailyContribution(date=date(2026, 3, 31), contribution=2.0),
            ],
        )
    ]

    hierarchy = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=position_rows,
        portfolio_period_slice_df=pd.DataFrame(
            {PortfolioColumns.PERF_DATE.value: [date(2026, 3, 30), date(2026, 3, 31)]}
        ),
        source_position_history_df=source_position_history,
        source_position_window_complete=True,
        position_series=position_series,
        position_average_weights=pd.DataFrame({"position_id": ["SEC_A"], "selected_average_weight": [0.5]}),
        request=request,
    )

    rows_by_sector = {row["key"]["sector"]: row for row in hierarchy["levels"][0]["rows"]}
    assert rows_by_sector["Sector A"]["contribution"] == pytest.approx(1.0)
    assert rows_by_sector["Sector B"]["contribution"] == pytest.approx(2.0)
    assert rows_by_sector["Sector A"]["weight_avg"] == pytest.approx(5.0)
    assert rows_by_sector["Sector B"]["weight_avg"] == pytest.approx(45.0)
    assert rows_by_sector["Sector A"]["group_return"]["status"] == "READY"
    assert rows_by_sector["Sector A"]["group_return"]["series"] == [
        {"date": date(2026, 3, 30), "return_pct": 1.0, "portfolio_weight_pct": 10.0},
        {"date": date(2026, 3, 31), "return_pct": 0.0, "portfolio_weight_pct": 0.0},
    ]
    assert rows_by_sector["Sector B"]["group_return"]["status"] == "READY"
    assert rows_by_sector["Sector B"]["group_return"]["series"] == [
        {"date": date(2026, 3, 30), "return_pct": 0.0, "portfolio_weight_pct": 0.0},
        {"date": date(2026, 3, 31), "return_pct": 2.0, "portfolio_weight_pct": 90.0},
    ]

    exclude_unclassified_request = request.model_copy(
        update={"emit": request.emit.model_copy(update={"include_unclassified": False})}
    )
    partly_unclassified_history = source_position_history.copy()
    partly_unclassified_history.loc[1, "sector"] = None
    classified_hierarchy = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=position_rows,
        portfolio_period_slice_df=pd.DataFrame(
            {PortfolioColumns.PERF_DATE.value: [date(2026, 3, 30), date(2026, 3, 31)]}
        ),
        source_position_history_df=partly_unclassified_history,
        source_position_window_complete=True,
        position_series=position_series,
        position_average_weights=pd.DataFrame({"position_id": ["SEC_A"], "selected_average_weight": [0.5]}),
        request=exclude_unclassified_request,
    )
    classified_rows = classified_hierarchy["levels"][0]["rows"]
    assert len(classified_rows) == 1
    assert classified_rows[0]["key"] == {"sector": "Sector A"}
    assert classified_rows[0]["weight_avg"] == pytest.approx(5.0)


def test_group_return_evidence_refuses_complete_calendar_from_incomplete_stateful_source():
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": "2026-03-30",
            "report_end_date": "2026-03-31",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "portfolio_data": {"metric_basis": "NET", "valuation_points": []},
            "positions_data": [],
        }
    )
    complete_retained_rows = pd.DataFrame(
        {
            "position_id": ["SEC_A", "SEC_A"],
            PortfolioColumns.PERF_DATE.value: [date(2026, 3, 30), date(2026, 3, 31)],
            PortfolioColumns.DAILY_ROR.value: [1.0, 2.0],
            "capital_inst": [500.0, 505.0],
            "daily_weight": [0.5, 0.5],
            "currency": ["USD", "USD"],
        }
    )

    evidence = _group_return_evidence(
        group_df=complete_retained_rows,
        request=request,
        observation_dates={date(2026, 3, 30), date(2026, 3, 31)},
        source_position_window_complete=False,
    )

    assert evidence == {
        "status": "UNAVAILABLE",
        "currency": None,
        "series": [],
        "reason": "SOURCE_POSITION_VALUATION_ECONOMICS_INCOMPLETE",
    }


def test_build_hierarchy_from_adjusted_position_series_uses_selected_period_average_weights():
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": "2026-03-30",
            "report_end_date": "2026-03-31",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "emit": {"threshold_weight": 0.0},
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2026-03-30", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2026-03-31", "begin_mv": 1010, "end_mv": 1020},
                ],
            },
            "positions_data": [
                {"position_id": "SEC_A", "valuation_points": []},
                {"position_id": "SEC_B", "valuation_points": []},
            ],
        }
    )
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["SEC_A", "SEC_A", "SEC_B", "SEC_B"],
            PortfolioColumns.PERF_DATE.value: [
                date(2026, 3, 30),
                date(2026, 3, 31),
                date(2026, 3, 30),
                date(2026, 3, 31),
            ],
            PortfolioColumns.DAILY_ROR.value: [1.0, 2.0, 3.0, 4.0],
            "capital_inst": [100.0, 950.0, 900.0, 50.0],
            "daily_weight": [0.10, 0.95, 0.90, 0.05],
            "currency": ["USD", "USD", "USD", "USD"],
            "sector": ["Technology", "Technology", "Health Care", "Health Care"],
        }
    )
    position_series = [
        PositionContributionSeries(
            position_id="SEC_A",
            series=[
                PositionDailyContribution(date=date(2026, 3, 30), contribution=1.0),
                PositionDailyContribution(date=date(2026, 3, 31), contribution=1.0),
            ],
        ),
        PositionContributionSeries(
            position_id="SEC_B",
            series=[
                PositionDailyContribution(date=date(2026, 3, 30), contribution=2.0),
                PositionDailyContribution(date=date(2026, 3, 31), contribution=2.0),
            ],
        ),
    ]
    selected_average_weights = pd.DataFrame(
        {
            "position_id": ["SEC_A", "SEC_B"],
            "selected_average_weight": [0.95, 0.05],
        }
    )

    hierarchy = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=period_slice_df,
        position_series=position_series,
        position_average_weights=selected_average_weights,
        request=request,
    )

    rows_by_sector = {row["key"]["sector"]: row for row in hierarchy["levels"][0]["rows"]}
    assert rows_by_sector["Technology"]["weight_avg"] == pytest.approx(95.0)
    assert rows_by_sector["Health Care"]["weight_avg"] == pytest.approx(5.0)
    assert [
        point["portfolio_weight_pct"] for point in rows_by_sector["Technology"]["group_return"]["series"]
    ] == pytest.approx([10.0, 95.0])
    assert [
        point["portfolio_weight_pct"] for point in rows_by_sector["Health Care"]["group_return"]["series"]
    ] == pytest.approx([90.0, 5.0])


def test_hierarchy_group_returns_publish_explicit_zero_exposure_before_group_inception():
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": "2026-03-30",
            "report_end_date": "2026-04-01",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "emit": {"threshold_weight": 0.0},
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2026-03-30", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2026-03-31", "begin_mv": 1010, "end_mv": 1020},
                    {"perf_date": "2026-04-01", "begin_mv": 1020, "end_mv": 1030},
                ],
            },
            "positions_data": [
                {"position_id": "ANCHOR", "valuation_points": []},
                {"position_id": "LATE", "valuation_points": []},
            ],
        }
    )
    dates = [date(2026, 3, 30), date(2026, 3, 31), date(2026, 4, 1)]
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["ANCHOR", "ANCHOR", "ANCHOR", "LATE", "LATE"],
            PortfolioColumns.PERF_DATE.value: [dates[0], dates[1], dates[2], dates[1], dates[2]],
            PortfolioColumns.DAILY_ROR.value: [1.0, 1.5, 2.0, 3.0, 4.0],
            "capital_inst": [1000.0, 800.0, 700.0, 200.0, 300.0],
            "daily_weight": [1.0, 0.8, 0.7, 0.2, 0.3],
            "currency": ["USD"] * 5,
            "sector": ["Anchor", "Anchor", "Anchor", "Late", "Late"],
        }
    )
    position_series = [
        PositionContributionSeries(
            position_id="ANCHOR",
            series=[
                PositionDailyContribution(date=dates[0], contribution=1.0),
                PositionDailyContribution(date=dates[1], contribution=1.2),
                PositionDailyContribution(date=dates[2], contribution=1.4),
            ],
        ),
        PositionContributionSeries(
            position_id="LATE",
            series=[
                PositionDailyContribution(date=dates[1], contribution=0.6),
                PositionDailyContribution(date=dates[2], contribution=1.2),
            ],
        ),
    ]

    hierarchy = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=period_slice_df,
        portfolio_period_slice_df=pd.DataFrame({PortfolioColumns.PERF_DATE.value: dates}),
        position_series=position_series,
        proven_position_inception_dates={"LATE": dates[1]},
        request=request,
    )

    rows = {row["key"]["sector"]: row for row in hierarchy["levels"][0]["rows"]}
    assert {point["date"] for point in rows["Anchor"]["group_return"]["series"]} == set(dates)
    assert rows["Late"]["group_return"]["series"] == [
        {"date": dates[0], "return_pct": 0.0, "portfolio_weight_pct": 0.0},
        {"date": dates[1], "return_pct": 3.0, "portfolio_weight_pct": 20.0},
        {"date": dates[2], "return_pct": 4.0, "portfolio_weight_pct": 30.0},
    ]
    assert rows["Late"]["group_return"]["period_return_pct"] == pytest.approx(7.12)


def test_hierarchy_group_returns_refuse_post_inception_portfolio_calendar_gap():
    dates = [date(2026, 3, 30), date(2026, 3, 31), date(2026, 4, 1)]
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": str(dates[0]),
            "report_end_date": str(dates[-1]),
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "emit": {"threshold_weight": 0.0},
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": value, "begin_mv": 1000, "end_mv": 1010} for value in dates],
            },
            "positions_data": [{"position_id": "GAPPED", "valuation_points": []}],
        }
    )
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["GAPPED", "GAPPED"],
            PortfolioColumns.PERF_DATE.value: [dates[0], dates[2]],
            PortfolioColumns.DAILY_ROR.value: [1.0, 2.0],
            "capital_inst": [1000.0, 1010.0],
            "daily_weight": [1.0, 1.0],
            "currency": ["USD", "USD"],
            "sector": ["Technology", "Technology"],
        }
    )
    position_series = [
        PositionContributionSeries(
            position_id="GAPPED",
            series=[
                PositionDailyContribution(date=dates[0], contribution=1.0),
                PositionDailyContribution(date=dates[2], contribution=2.0),
            ],
        )
    ]

    hierarchy = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=period_slice_df,
        portfolio_period_slice_df=pd.DataFrame({PortfolioColumns.PERF_DATE.value: dates}),
        position_series=position_series,
        request=request,
    )

    group_return = hierarchy["levels"][0]["rows"][0]["group_return"]
    assert group_return["status"] == "UNAVAILABLE"
    assert group_return["reason"] == "SOURCE_POSITION_VALUATION_ECONOMICS_INCOMPLETE"
    assert group_return["series"] == []


def test_hierarchy_group_returns_use_source_history_for_subperiod_inception():
    dates = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": str(dates[0]),
            "report_end_date": str(dates[-1]),
            "analyses": [{"period": "MTD", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "emit": {"threshold_weight": 0.0},
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": value, "begin_mv": 1000, "end_mv": 1010} for value in dates],
            },
            "positions_data": [{"position_id": "RESUMED", "valuation_points": []}],
        }
    )
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["RESUMED", "RESUMED"],
            PortfolioColumns.PERF_DATE.value: dates[1:],
            PortfolioColumns.DAILY_ROR.value: [1.0, 2.0],
            "capital_inst": [1000.0, 1010.0],
            "daily_weight": [1.0, 1.0],
            "currency": ["USD", "USD"],
            "sector": ["Technology", "Technology"],
        }
    )
    position_series = [
        PositionContributionSeries(
            position_id="RESUMED",
            series=[
                PositionDailyContribution(date=dates[1], contribution=1.0),
                PositionDailyContribution(date=dates[2], contribution=2.0),
            ],
        )
    ]

    hierarchy = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=period_slice_df,
        portfolio_period_slice_df=pd.DataFrame({PortfolioColumns.PERF_DATE.value: dates}),
        position_series=position_series,
        proven_position_inception_dates={"RESUMED": date(2026, 8, 25)},
        request=request,
    )

    group_return = hierarchy["levels"][0]["rows"][0]["group_return"]
    assert group_return["status"] == "UNAVAILABLE"
    assert group_return["reason"] == "SOURCE_POSITION_VALUATION_ECONOMICS_INCOMPLETE"
    assert group_return["series"] == []


@pytest.mark.parametrize(
    ("missing_position_sector", "expected_status"),
    [("Technology", "UNAVAILABLE"), ("Health Care", "READY")],
)
def test_hierarchy_group_returns_use_source_membership_for_position_wholly_absent_from_subperiod(
    missing_position_sector,
    expected_status,
):
    prior_date = date(2026, 8, 31)
    dates = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": str(dates[0]),
            "report_end_date": str(dates[-1]),
            "analyses": [{"period": "MTD", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "emit": {"top_n_per_level": 1},
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": value, "begin_mv": 1000, "end_mv": 1010} for value in dates],
            },
            "positions_data": [
                {"position_id": "ACTIVE", "valuation_points": []},
                {"position_id": "MISSING", "valuation_points": []},
            ],
        }
    )
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["ACTIVE"] * 3,
            PortfolioColumns.PERF_DATE.value: dates,
            PortfolioColumns.DAILY_ROR.value: [1.0, 1.5, 2.0],
            "capital_inst": [700.0, 710.0, 720.0],
            "daily_weight": [0.7, 0.7, 0.7],
            "currency": ["USD"] * 3,
            "sector": ["Technology"] * 3,
        }
    )
    source_position_history_df = pd.concat(
        [
            pd.DataFrame(
                {
                    "position_id": ["MISSING"],
                    PortfolioColumns.PERF_DATE.value: [prior_date],
                    "sector": [missing_position_sector],
                }
            ),
            period_slice_df,
        ],
        ignore_index=True,
    )
    position_series = [
        PositionContributionSeries(
            position_id="ACTIVE",
            series=[PositionDailyContribution(date=value, contribution=0.7) for value in dates],
        )
    ]

    hierarchy = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=period_slice_df,
        portfolio_period_slice_df=pd.DataFrame({PortfolioColumns.PERF_DATE.value: dates}),
        source_position_history_df=source_position_history_df,
        position_series=position_series,
        request=request,
    )

    rows = {row["key"]["sector"]: row for row in hierarchy["levels"][0]["rows"]}
    active_group_return = rows["Technology"]["group_return"]
    assert active_group_return["status"] == expected_status
    if missing_position_sector == "Technology":
        assert set(rows) == {"Technology"}
        assert active_group_return["reason"] == "SOURCE_POSITION_VALUATION_ECONOMICS_INCOMPLETE"
        assert active_group_return["series"] == []
    else:
        assert set(rows) == {"Technology", "Health Care"}
        assert active_group_return["reason"] is None
        assert len(active_group_return["series"]) == len(dates)
        missing_group_return = rows["Health Care"]["group_return"]
        assert missing_group_return["status"] == "UNAVAILABLE"
        assert missing_group_return["reason"] == "SOURCE_POSITION_VALUATION_ECONOMICS_INCOMPLETE"
        assert missing_group_return["series"] == []


def test_hierarchy_preserves_period_when_every_source_group_is_absent():
    prior_date = date(2026, 8, 31)
    dates = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": str(dates[0]),
            "report_end_date": str(dates[-1]),
            "analyses": [{"period": "MTD", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "emit": {"threshold_weight": 0.99, "top_n_per_level": 1},
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": value, "begin_mv": 1000, "end_mv": 1010} for value in dates],
            },
            "positions_data": [
                {"position_id": "PRIOR_TECH", "valuation_points": []},
                {"position_id": "PRIOR_HEALTH", "valuation_points": []},
            ],
        }
    )
    source_position_history_df = pd.DataFrame(
        {
            "position_id": ["PRIOR_TECH", "PRIOR_HEALTH"],
            PortfolioColumns.PERF_DATE.value: [prior_date, prior_date],
            "sector": ["Technology", "Health Care"],
        }
    )

    hierarchy = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=source_position_history_df.iloc[0:0],
        portfolio_period_slice_df=pd.DataFrame({PortfolioColumns.PERF_DATE.value: dates}),
        source_position_history_df=source_position_history_df,
        source_position_window_complete=True,
        position_series=[],
        request=request,
    )

    assert hierarchy["summary"]["portfolio_contribution"] == 0.0
    rows = {row["key"]["sector"]: row for row in hierarchy["levels"][0]["rows"]}
    assert set(rows) == {"Technology", "Health Care"}
    for row in rows.values():
        assert row["contribution"] == 0.0
        assert row["weight_avg"] == 0.0
        assert row["group_return"] == {
            "status": "UNAVAILABLE",
            "currency": None,
            "series": [],
            "reason": "SOURCE_POSITION_VALUATION_ECONOMICS_INCOMPLETE",
        }


def test_hierarchy_group_returns_refuse_unproven_leading_gap_from_bounded_source():
    dates = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": str(dates[0]),
            "report_end_date": str(dates[-1]),
            "analyses": [{"period": "MTD", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "emit": {"threshold_weight": 0.0},
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": value, "begin_mv": 1000, "end_mv": 1010} for value in dates],
            },
            "positions_data": [{"position_id": "RESUMED", "valuation_points": []}],
        }
    )
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["RESUMED", "RESUMED"],
            PortfolioColumns.PERF_DATE.value: dates[1:],
            PortfolioColumns.DAILY_ROR.value: [1.0, 2.0],
            "capital_inst": [1000.0, 1010.0],
            "daily_weight": [1.0, 1.0],
            "currency": ["USD", "USD"],
            "sector": ["Technology", "Technology"],
        }
    )
    position_series = [
        PositionContributionSeries(
            position_id="RESUMED",
            series=[
                PositionDailyContribution(date=dates[1], contribution=1.0),
                PositionDailyContribution(date=dates[2], contribution=2.0),
            ],
        )
    ]

    hierarchy = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=period_slice_df,
        portfolio_period_slice_df=pd.DataFrame({PortfolioColumns.PERF_DATE.value: dates}),
        position_series=position_series,
        proven_position_inception_dates={},
        request=request,
    )

    group_return = hierarchy["levels"][0]["rows"][0]["group_return"]
    assert group_return["status"] == "UNAVAILABLE"
    assert group_return["reason"] == "SOURCE_POSITION_VALUATION_ECONOMICS_INCOMPLETE"
    assert group_return["series"] == []


def test_hierarchy_weights_preserve_selected_average_on_larger_portfolio_calendar():
    dates = [date(2026, 3, 30), date(2026, 3, 31), date(2026, 4, 1)]
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": str(dates[0]),
            "report_end_date": str(dates[-1]),
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "emit": {"threshold_weight": 0.20},
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": value, "begin_mv": 1000, "end_mv": 1010} for value in dates],
            },
            "positions_data": [{"position_id": "LATE", "valuation_points": []}],
        }
    )
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["LATE", "LATE"],
            PortfolioColumns.PERF_DATE.value: dates[1:],
            PortfolioColumns.DAILY_ROR.value: [1.0, 2.0],
            "capital_inst": [250.0, 250.0],
            "daily_weight": [0.25, 0.25],
            "currency": ["USD", "USD"],
            "sector": ["Private Credit", "Private Credit"],
        }
    )
    position_series = [
        PositionContributionSeries(
            position_id="LATE",
            series=[
                PositionDailyContribution(date=dates[1], contribution=0.25),
                PositionDailyContribution(date=dates[2], contribution=0.25),
            ],
        )
    ]

    hierarchy = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=period_slice_df,
        portfolio_period_slice_df=pd.DataFrame({PortfolioColumns.PERF_DATE.value: dates}),
        position_series=position_series,
        position_average_weights=pd.DataFrame({"position_id": ["LATE"], "selected_average_weight": [0.25]}),
        request=request,
    )

    row = hierarchy["levels"][0]["rows"][0]
    assert row["key"] == {"sector": "Private Credit"}
    assert row["weight_avg"] == pytest.approx(25.0)


def test_proven_position_inception_dates_require_opening_flow_economics():
    source_df = pd.DataFrame(
        {
            "position_id": ["A", "A", "B", None],
            PortfolioColumns.PERF_DATE.value: [
                "2026-08-25T23:30:00Z",
                date(2026, 9, 2),
                date(2026, 9, 3),
                date(2026, 8, 1),
            ],
            PortfolioColumns.BEGIN_MV.value: [0.0, 100.0, 75.0, 0.0],
            PortfolioColumns.BOD_CF.value: [100.0, 0.0, 0.0, 50.0],
        }
    )

    assert _proven_position_inception_dates(source_df) == {
        "A": date(2026, 8, 25),
    }


def test_hierarchy_metadata_helpers_align_dates_and_unclassified_policy():
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "report_start_date": "2026-03-30",
            "report_end_date": "2026-03-31",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "hierarchy": ["sector", "region"],
            "emit": {"include_unclassified": True, "threshold_weight": 0.0},
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2026-03-30", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2026-03-31", "begin_mv": 1010, "end_mv": 1020},
                ],
            },
            "positions_data": [
                {
                    "position_id": "SEC_A",
                    "valuation_points": [
                        {"perf_date": "2026-03-30", "begin_mv": 500, "end_mv": 505},
                    ],
                }
            ],
        }
    )
    position_series = [
        PositionContributionSeries(
            position_id="SEC_A",
            series=[PositionDailyContribution(date=date(2026, 3, 30), contribution=1.25)],
        )
    ]
    period_slice_df = pd.DataFrame(
        {
            "position_id": ["SEC_A"],
            PortfolioColumns.PERF_DATE.value: ["2026-03-30T12:00:00Z"],
            "daily_weight": [0.5],
            "sector": ["Technology"],
        }
    )

    records = _adjusted_position_hierarchy_records(position_series)
    metadata = _daily_hierarchy_metadata(period_slice_df, hierarchy_levels=request.hierarchy)
    merged_df = pd.DataFrame(records).merge(
        metadata,
        on=["position_id", PortfolioColumns.PERF_DATE.value],
        how="left",
    )
    classified_df = _apply_hierarchy_unclassified_policy(merged_df, request=request)

    assert records == [
        {
            "position_id": "SEC_A",
            PortfolioColumns.PERF_DATE.value: date(2026, 3, 30),
            "adjusted_contribution": 0.0125,
        }
    ]
    assert list(metadata.columns) == [
        "position_id",
        PortfolioColumns.PERF_DATE.value,
        PortfolioColumns.DAILY_ROR.value,
        "capital_inst",
        "daily_weight",
        "source_daily_weight",
        "selected_average_weight",
        "selected_weight_component",
        "currency",
        "sector",
        "region",
    ]
    assert metadata.iloc[0][PortfolioColumns.PERF_DATE.value] == date(2026, 3, 30)
    assert classified_df.iloc[0]["region"] == "Unclassified"

    exclude_request = request.model_copy(
        update={"emit": request.emit.model_copy(update={"include_unclassified": False})}
    )
    assert _apply_hierarchy_unclassified_policy(merged_df, request=exclude_request).empty
    assert (
        _prepared_adjusted_hierarchy_frames(
            period_slice_df=period_slice_df,
            position_series=position_series,
            request=exclude_request,
        )
        is None
    )


def test_hierarchy_metadata_columns_preserves_base_columns_and_unique_levels():
    assert _hierarchy_metadata_columns(
        [
            "sector",
            "daily_weight",
            "region",
            "sector",
            PortfolioColumns.PERF_DATE.value,
        ]
    ) == [
        "position_id",
        PortfolioColumns.PERF_DATE.value,
        PortfolioColumns.DAILY_ROR.value,
        "capital_inst",
        "daily_weight",
        "source_daily_weight",
        "selected_average_weight",
        "selected_weight_component",
        "currency",
        "sector",
        "region",
    ]


def test_other_hierarchy_row_for_emission_aggregates_overflow_rows_and_suppresses_when_disabled():
    overflow_rows = pd.DataFrame(
        {
            "contribution": [0.0125, -0.0025],
            "weight_avg": [0.15, 0.05],
        }
    )

    assert _other_hierarchy_row_for_emission(
        overflow_rows=overflow_rows,
        level_keys=["sector", "region"],
        include_other=True,
    ) == {
        "key": {"sector": "Other", "region": "Other"},
        "contribution": 1.0,
        "weight_avg": 20.0,
        "group_return": {
            "status": "UNAVAILABLE",
            "currency": None,
            "series": [],
            "reason": "OTHER_BUCKET_COMBINES_MULTIPLE_SOURCE_GROUPS",
        },
        "children_count": 2,
        "is_other": True,
    }
    assert (
        _other_hierarchy_row_for_emission(
            overflow_rows=overflow_rows,
            level_keys=["sector"],
            include_other=False,
        )
        is None
    )
    assert (
        _other_hierarchy_row_for_emission(
            overflow_rows=overflow_rows.iloc[0:0],
            level_keys=["sector"],
            include_other=True,
        )
        is None
    )


def test_residual_adjusted_position_rows_allocate_by_weight_and_equal_fallback():
    weighted_rows = _residual_adjusted_position_rows(
        position_id="SEC_A",
        position_slice=pd.DataFrame(
            {
                PortfolioColumns.PERF_DATE.value: [date(2026, 3, 30), date(2026, 3, 31)],
                "smoothed_contribution": [0.01, 0.01],
                "daily_weight": [-0.25, 0.75],
            }
        ),
        target_total=0.04,
    )
    equal_fallback_rows = _residual_adjusted_position_rows(
        position_id="SEC_B",
        position_slice=pd.DataFrame(
            {
                PortfolioColumns.PERF_DATE.value: [date(2026, 3, 30), date(2026, 3, 31)],
                "smoothed_contribution": [0.02, 0.00],
                "daily_weight": [0.0, 0.0],
            }
        ),
        target_total=0.00,
    )

    assert [row["adjusted_contribution"] for row in weighted_rows] == [0.015, 0.025]
    assert [row["adjusted_contribution"] for row in equal_fallback_rows] == [0.01, -0.01]


def test_target_total_contribution_by_position_projects_percentage_totals_to_ratios():
    targets = _target_total_contribution_by_position(
        [
            PositionContribution(
                position_id="SEC_A",
                total_contribution=2.5,
                average_weight=25.0,
                total_return=10.0,
            ),
            PositionContribution(
                position_id="SEC_B",
                total_contribution=0.0,
                average_weight=0.0,
                total_return=0.0,
            ),
        ]
    )

    assert targets == {"SEC_A": 0.025, "SEC_B": 0.0}


def test_residual_adjusted_daily_totals_by_date_aggregates_position_points():
    totals_by_date = _residual_adjusted_daily_totals_by_date(
        [
            PositionContributionSeries(
                position_id="SEC_A",
                series=[
                    PositionDailyContribution(date=date(2026, 3, 30), contribution=1.25),
                    PositionDailyContribution(date=date(2026, 3, 31), contribution=-0.25),
                ],
            ),
            PositionContributionSeries(
                position_id="SEC_B",
                series=[
                    PositionDailyContribution(date=date(2026, 3, 30), contribution=2.75),
                ],
            ),
        ]
    )

    assert totals_by_date == {
        date(2026, 3, 30): 4.0,
        date(2026, 3, 31): -0.25,
    }
