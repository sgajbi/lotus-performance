from datetime import date
from decimal import Decimal

from app.models.requests import Analysis, DailyInputData, PerformanceRequest
from app.services.inspection import source_economics, source_economics_collector
from app.services.inspection.source_economics import ObservationSourceEconomics, analyze_source_economics
from app.services.inspection.source_economics_collector import collect_source_economics_samples


def _source_economics_point(**overrides: object) -> ObservationSourceEconomics:
    values: dict[str, object] = {
        "valuation_date": "2026-03-12",
        "normalized_bod_cf": Decimal("0"),
        "normalized_eod_cf": Decimal("0"),
        "normalized_mgmt_fees": Decimal("0"),
        "detailed_external_bod": Decimal("0"),
        "detailed_external_eod": Decimal("0"),
        "detailed_fee_bod": Decimal("0"),
        "detailed_fee_eod": Decimal("0"),
        "explicit_bod_total": None,
        "explicit_eod_total": None,
        "explicit_fee_total": None,
        "conflicting_explicit_amount_fields": (),
        "invalid_explicit_amount_fields": (),
        "invalid_cashflow_collection": None,
        "invalid_cashflow_rows": (),
        "invalid_amount_rows": (),
        "invalid_timing_rows": (),
        "missing_cashflow_type_rows": (),
        "noncanonical_cashflow_types": (),
        "unsupported_cashflow_type_rows": (),
        "governed_alias_cashflow_type_rows": (),
        "fee_bod_timing_rows": (),
    }
    values.update(overrides)
    return ObservationSourceEconomics(**values)


def test_external_mixed_timing_sample_requires_detailed_bod_and_eod_flows():
    assert source_economics_collector._external_mixed_timing_sample(
        _source_economics_point(detailed_external_bod=Decimal("100"), detailed_external_eod=Decimal("-25"))
    ) == {
        "valuation_date": "2026-03-12",
        "detailed_external_bod": 100.0,
        "detailed_external_eod": -25.0,
    }
    assert (
        source_economics_collector._external_mixed_timing_sample(
            _source_economics_point(detailed_external_bod=Decimal("100"), detailed_external_eod=Decimal("0"))
        )
        is None
    )


def test_external_explicit_mixed_timing_sample_requires_explicit_bod_and_eod_flows():
    assert source_economics_collector._external_explicit_mixed_timing_sample(
        _source_economics_point(explicit_bod_total=Decimal("100"), explicit_eod_total=Decimal("-25"))
    ) == {
        "valuation_date": "2026-03-12",
        "explicit_external_bod": 100.0,
        "explicit_external_eod": -25.0,
    }
    assert (
        source_economics_collector._external_explicit_mixed_timing_sample(
            _source_economics_point(explicit_bod_total=Decimal("100"), explicit_eod_total=None)
        )
        is None
    )
    assert (
        source_economics_collector._external_explicit_mixed_timing_sample(
            _source_economics_point(explicit_bod_total=Decimal("100"), explicit_eod_total=Decimal("0"))
        )
        is None
    )


def test_external_timing_contradiction_sample_projects_artifact_fields():
    assert source_economics_collector._external_timing_contradiction_sample(
        valuation_date="2026-03-12",
        explicit_timing="bod",
        opposite_detailed_timing="eod",
        explicit_total=Decimal("100"),
        opposite_detailed_total=Decimal("-25"),
    ) == {
        "valuation_date": "2026-03-12",
        "explicit_timing": "bod",
        "opposite_detailed_timing": "eod",
        "explicit_cashflow_amount": "100",
        "opposite_detailed_cashflow_amount": "-25",
    }


def test_record_external_timing_contradictions_routes_bod_and_eod_conflicts():
    samples: list[dict[str, object]] = []

    source_economics_collector._record_external_timing_contradictions(
        source_point=_source_economics_point(
            explicit_bod_total=Decimal("100"),
            explicit_eod_total=Decimal("-25"),
            detailed_external_bod=Decimal("10"),
            detailed_external_eod=Decimal("-20"),
        ),
        sample_target=samples,
    )

    assert samples == []

    source_economics_collector._record_external_timing_contradictions(
        source_point=_source_economics_point(
            explicit_bod_total=Decimal("100"),
            detailed_external_bod=Decimal("0"),
            detailed_external_eod=Decimal("-20"),
        ),
        sample_target=samples,
    )
    source_economics_collector._record_external_timing_contradictions(
        source_point=_source_economics_point(
            explicit_eod_total=Decimal("-25"),
            detailed_external_bod=Decimal("10"),
            detailed_external_eod=Decimal("0"),
        ),
        sample_target=samples,
    )

    assert samples == [
        {
            "valuation_date": "2026-03-12",
            "explicit_timing": "bod",
            "opposite_detailed_timing": "eod",
            "explicit_cashflow_amount": "100",
            "opposite_detailed_cashflow_amount": "-20",
        },
        {
            "valuation_date": "2026-03-12",
            "explicit_timing": "eod",
            "opposite_detailed_timing": "bod",
            "explicit_cashflow_amount": "-25",
            "opposite_detailed_cashflow_amount": "10",
        },
    ]


def test_collect_source_economics_samples_routes_taxonomy_samples():
    samples = collect_source_economics_samples(
        source_points=[
            ObservationSourceEconomics(
                valuation_date="2026-03-12",
                normalized_bod_cf=Decimal("0"),
                normalized_eod_cf=Decimal("0"),
                normalized_mgmt_fees=Decimal("0"),
                detailed_external_bod=Decimal("10"),
                detailed_external_eod=Decimal("0"),
                detailed_fee_bod=Decimal("0"),
                detailed_fee_eod=Decimal("-2"),
                explicit_bod_total=None,
                explicit_eod_total=None,
                explicit_fee_total=None,
                conflicting_explicit_amount_fields=({"field": "bod_cashflow", "amount": "10"},),
                invalid_explicit_amount_fields=({"field": "fees", "amount": "bad"},),
                invalid_cashflow_collection={"raw_type": "str", "sample": "bad"},
                invalid_cashflow_rows=({"raw_type": "int", "raw_value": 1},),
                invalid_amount_rows=({"amount": "bad"},),
                invalid_timing_rows=({"timing": "intraday"},),
                missing_cashflow_type_rows=({"amount": "1"},),
                noncanonical_cashflow_types=("dividend",),
                unsupported_cashflow_type_rows=({"cash_flow_type": "dividend", "amount": "1"},),
                governed_alias_cashflow_type_rows=({"cash_flow_type": "deposit", "amount": "10"},),
                fee_bod_timing_rows=(),
            )
        ]
    )

    assert samples.fee_flow_dates == ["2026-03-12"]
    assert samples.external_flow_dates == ["2026-03-12"]
    assert samples.conflicting_explicit_amount_samples == [
        {"valuation_date": "2026-03-12", "rows": [{"field": "bod_cashflow", "amount": "10"}]}
    ]
    assert samples.invalid_cashflow_collection_samples == [
        {"valuation_date": "2026-03-12", "raw_type": "str", "sample": "bad"}
    ]
    assert samples.noncanonical_cashflow_type_samples == [
        {"valuation_date": "2026-03-12", "cash_flow_types": ["dividend"]}
    ]
    assert samples.unsupported_cashflow_type_samples == [
        {
            "valuation_date": "2026-03-12",
            "cash_flow_types": ["dividend"],
            "rows": [{"cash_flow_type": "dividend", "amount": "1"}],
        }
    ]
    assert samples.governed_alias_cashflow_type_samples == [
        {
            "valuation_date": "2026-03-12",
            "cash_flow_types": ["deposit"],
            "rows": [{"cash_flow_type": "deposit", "amount": "10"}],
        }
    ]


def test_collect_source_economics_samples_routes_fee_samples():
    samples = collect_source_economics_samples(
        source_points=[
            ObservationSourceEconomics(
                valuation_date="2026-03-12",
                normalized_bod_cf=Decimal("0"),
                normalized_eod_cf=Decimal("0"),
                normalized_mgmt_fees=Decimal("0"),
                detailed_external_bod=Decimal("0"),
                detailed_external_eod=Decimal("0"),
                detailed_fee_bod=Decimal("-5"),
                detailed_fee_eod=Decimal("-10"),
                explicit_bod_total=None,
                explicit_eod_total=None,
                explicit_fee_total=Decimal("-15"),
                conflicting_explicit_amount_fields=(),
                invalid_explicit_amount_fields=(),
                invalid_cashflow_collection=None,
                invalid_cashflow_rows=(),
                invalid_amount_rows=(),
                invalid_timing_rows=(),
                missing_cashflow_type_rows=(),
                noncanonical_cashflow_types=(),
                unsupported_cashflow_type_rows=(),
                governed_alias_cashflow_type_rows=(),
                fee_bod_timing_rows=({"amount": "-5", "timing": "bod", "cash_flow_type": "fee"},),
            ),
            ObservationSourceEconomics(
                valuation_date="2026-03-13",
                normalized_bod_cf=Decimal("0"),
                normalized_eod_cf=Decimal("0"),
                normalized_mgmt_fees=Decimal("0"),
                detailed_external_bod=Decimal("0"),
                detailed_external_eod=Decimal("0"),
                detailed_fee_bod=Decimal("-2"),
                detailed_fee_eod=Decimal("0"),
                explicit_bod_total=None,
                explicit_eod_total=None,
                explicit_fee_total=Decimal("3"),
                conflicting_explicit_amount_fields=(),
                invalid_explicit_amount_fields=(),
                invalid_cashflow_collection=None,
                invalid_cashflow_rows=(),
                invalid_amount_rows=(),
                invalid_timing_rows=(),
                missing_cashflow_type_rows=(),
                noncanonical_cashflow_types=(),
                unsupported_cashflow_type_rows=(),
                governed_alias_cashflow_type_rows=(),
                fee_bod_timing_rows=(),
            ),
        ]
    )

    assert samples.fee_normalization_samples[0] == {
        "valuation_date": "2026-03-12",
        "raw_fee_bod": -5.0,
        "raw_fee_eod": -10.0,
        "expected_fee_amount": "-15",
        "fee_source_kind": "detailed_fee_cash_flows",
        "normalized_bod_cf": 0.0,
        "normalized_eod_cf": 0.0,
        "normalized_mgmt_fees": 0.0,
    }
    assert samples.duplicate_fee_signal_samples == [
        {"valuation_date": "2026-03-12", "explicit_fee_amount": "-15", "fee_cashflow_amount": "-15"}
    ]
    assert samples.fee_source_mismatch_samples == [
        {"valuation_date": "2026-03-13", "explicit_fee_amount": "3", "fee_cashflow_amount": "-2"}
    ]
    assert samples.positive_fee_signal_samples == [
        {"valuation_date": "2026-03-13", "detailed_fee_amount": "-2", "explicit_fee_amount": "3"}
    ]
    assert samples.fee_timing_bucket_samples == [
        {
            "valuation_date": "2026-03-12",
            "rows": [{"amount": "-5", "timing": "bod", "cash_flow_type": "fee"}],
        }
    ]
    assert samples.fee_mixed_timing_samples == [
        {"valuation_date": "2026-03-12", "detailed_fee_bod": -5.0, "detailed_fee_eod": -10.0}
    ]


def test_has_positive_fee_signal_detects_explicit_or_detailed_positive_amounts():
    assert source_economics_collector._has_positive_fee_signal(
        explicit_fee_total=Decimal("1"),
        detailed_fee_total=Decimal("-2"),
    )
    assert source_economics_collector._has_positive_fee_signal(
        explicit_fee_total=None,
        detailed_fee_total=Decimal("1"),
    )
    assert not source_economics_collector._has_positive_fee_signal(
        explicit_fee_total=Decimal("-1"),
        detailed_fee_total=Decimal("0"),
    )


def test_analyze_source_economics_flags_fee_normalization_gap_and_duplicate_signal():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 12),
        metric_basis="NET",
        report_end_date=date(2026, 3, 12),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 12),
                begin_mv=1200.0,
                end_mv=1190.0,
                bod_cf=0.0,
                eod_cf=-275.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-12",
                "beginning_market_value": "1200.0",
                "ending_market_value": "1190.0",
                "fees": "-275.0",
                "cash_flows": [
                    {"amount": "-275.0", "timing": "eod", "cash_flow_type": "fee"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {
        "FEE_CASHFLOW_CLASSIFICATION_NOT_PRESERVED",
        "DUPLICATE_FEE_SOURCE_SIGNAL",
    }
    assert result.evidence_summary["fee_cashflow_date_count"] == 1
    assert result.evidence_summary["fee_normalization_gap_count"] == 1
    assert result.evidence_summary["duplicate_fee_signal_count"] == 1


def test_analyze_source_economics_flags_invalid_observation_date_identity():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 12),
        metric_basis="NET",
        report_end_date=date(2026, 3, 12),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 12),
                begin_mv=1200.0,
                end_mv=1190.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": None,
                "beginning_market_value": "1200.0",
                "ending_market_value": "1190.0",
                "cash_flows": [
                    {"amount": "-10.0", "timing": "eod", "cash_flow_type": "fee"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"INVALID_PORTFOLIO_OBSERVATION_DATE_PRESENT"}
    assert result.evidence_summary["invalid_observation_date_count"] == 1
    assert result.evidence_summary["fee_cashflow_date_count"] == 0
    assert result.artifact_payload["invalid_observation_date_samples"] == [
        {
            "valuation_date": None,
            "raw_type": "NoneType",
            "raw_value": None,
            "observation_keys": [
                "beginning_market_value",
                "cash_flows",
                "ending_market_value",
                "valuation_date",
            ],
        }
    ]


def test_analyze_source_economics_flags_non_iso_observation_date_identity():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 12),
        metric_basis="NET",
        report_end_date=date(2026, 3, 12),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 12),
                begin_mv=1200.0,
                end_mv=1190.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026/03/12",
                "beginning_market_value": "1200.0",
                "ending_market_value": "1190.0",
                "cash_flows": [
                    {"amount": "-10.0", "timing": "eod", "cash_flow_type": "fee"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"INVALID_PORTFOLIO_OBSERVATION_DATE_PRESENT"}
    assert result.evidence_summary["invalid_observation_date_count"] == 1
    assert result.evidence_summary["fee_cashflow_date_count"] == 0
    assert result.artifact_payload["invalid_observation_date_samples"][0]["valuation_date"] == "2026/03/12"
    assert result.artifact_payload["invalid_observation_date_samples"][0]["raw_type"] == "str"
    assert result.artifact_payload["invalid_observation_date_samples"][0]["raw_value"] == "2026/03/12"


def test_analyze_source_economics_flags_external_flow_normalization_and_source_conflicts():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 5),
        metric_basis="NET",
        report_end_date=date(2026, 3, 26),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 5),
                begin_mv=1200.0,
                end_mv=1600.0,
                bod_cf=80000.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
            DailyInputData(
                perf_date=date(2026, 3, 26),
                begin_mv=1600.0,
                end_mv=1300.0,
                bod_cf=0.0,
                eod_cf=-50000.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-05",
                "beginning_market_value": "1200.0",
                "ending_market_value": "1600.0",
                "bod_cashflow": "40000.0",
                "cash_flows": [
                    {"amount": "40000.0", "timing": "bod", "cash_flow_type": "external_flow"},
                ],
            },
            {
                "valuation_date": "2026-03-26",
                "beginning_market_value": "1600.0",
                "ending_market_value": "1300.0",
                "eod_cashflow": "-25000.0",
                "cash_flows": [
                    {"amount": "-20000.0", "timing": "eod", "cash_flow_type": "external_flow"},
                ],
            },
        ],
    )

    assert {finding.code for finding in result.findings} == {
        "EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH",
        "DUPLICATE_EXTERNAL_CASHFLOW_SOURCE_SIGNAL",
        "EXTERNAL_CASHFLOW_SOURCE_TOTAL_MISMATCH",
    }
    assert result.evidence_summary["external_cashflow_date_count"] == 2
    assert result.evidence_summary["external_cashflow_normalization_gap_count"] == 2
    assert result.evidence_summary["duplicate_external_cashflow_signal_count"] == 1
    assert result.evidence_summary["external_cashflow_source_mismatch_count"] == 1


def test_analyze_source_economics_flags_positive_fee_source_signal():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 13),
        metric_basis="NET",
        report_end_date=date(2026, 3, 13),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 13),
                begin_mv=1200.0,
                end_mv=1210.0,
                bod_cf=0.0,
                eod_cf=5.0,
                mgmt_fees=5.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-13",
                "beginning_market_value": "1200.0",
                "ending_market_value": "1210.0",
                "fees": "5.0",
                "cash_flows": [
                    {"amount": "5.0", "timing": "eod", "cash_flow_type": "fee"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {
        "DUPLICATE_FEE_SOURCE_SIGNAL",
        "POSITIVE_FEE_SOURCE_SIGNAL",
    }
    assert result.evidence_summary["positive_fee_signal_count"] == 1


def test_analyze_source_economics_flags_fee_source_total_mismatch():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 14),
        metric_basis="NET",
        report_end_date=date(2026, 3, 14),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 14),
                begin_mv=1210.0,
                end_mv=1198.0,
                bod_cf=0.0,
                eod_cf=-8.0,
                mgmt_fees=-8.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-14",
                "beginning_market_value": "1210.0",
                "ending_market_value": "1198.0",
                "fees": "-10.0",
                "cash_flows": [
                    {"amount": "-8.0", "timing": "eod", "cash_flow_type": "fee"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"FEE_SOURCE_TOTAL_MISMATCH"}
    assert result.evidence_summary["fee_source_mismatch_count"] == 1


def test_analyze_source_economics_flags_beginning_of_day_fee_timing_bucket():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 16),
        metric_basis="NET",
        report_end_date=date(2026, 3, 16),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 16),
                begin_mv=1200.0,
                end_mv=1175.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=-25.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-16",
                "beginning_market_value": "1200.0",
                "ending_market_value": "1175.0",
                "cash_flows": [
                    {"amount": "-25.0", "timing": "bod", "cash_flow_type": "fee"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"FEE_CASHFLOW_TIMING_BUCKET_UNSUPPORTED"}
    assert result.evidence_summary["fee_cashflow_date_count"] == 1
    assert result.evidence_summary["fee_normalization_gap_count"] == 0
    assert result.evidence_summary["fee_timing_bucket_anomaly_count"] == 1
    assert result.artifact_payload["fee_timing_bucket_samples"] == [
        {
            "valuation_date": "2026-03-16",
            "rows": [{"timing": "bod", "amount": "-25.0", "cash_flow_type": "fee"}],
        }
    ]


def test_analyze_source_economics_flags_mixed_fee_timing_buckets():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 16),
        metric_basis="NET",
        report_end_date=date(2026, 3, 16),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 16),
                begin_mv=1200.0,
                end_mv=1170.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=-30.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-16",
                "beginning_market_value": "1200.0",
                "ending_market_value": "1170.0",
                "cash_flows": [
                    {"amount": "-10.0", "timing": "bod", "cash_flow_type": "fee"},
                    {"amount": "-20.0", "timing": "eod", "cash_flow_type": "fee"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {
        "FEE_CASHFLOW_TIMING_BUCKET_UNSUPPORTED",
        "FEE_CASHFLOW_MIXED_TIMING_BUCKETS",
    }
    assert result.evidence_summary["fee_timing_bucket_anomaly_count"] == 1
    assert result.evidence_summary["fee_cashflow_mixed_timing_date_count"] == 1
    assert result.artifact_payload["fee_cashflow_mixed_timing_samples"] == [
        {
            "valuation_date": "2026-03-16",
            "detailed_fee_bod": -10.0,
            "detailed_fee_eod": -20.0,
        }
    ]


def test_analyze_source_economics_flags_explicit_fee_normalization_mismatch_without_detailed_fee_rows():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 17),
        metric_basis="NET",
        report_end_date=date(2026, 3, 17),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 17),
                begin_mv=1200.0,
                end_mv=1188.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=-8.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-17",
                "beginning_market_value": "1200.0",
                "ending_market_value": "1188.0",
                "fees": "-10.0",
                "cash_flows": [],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"FEE_CASHFLOW_CLASSIFICATION_NOT_PRESERVED"}
    assert result.evidence_summary["fee_normalization_gap_count"] == 1


def test_analyze_source_economics_flags_explicit_external_normalization_mismatch_without_detailed_rows():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 18),
        metric_basis="NET",
        report_end_date=date(2026, 3, 18),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 18),
                begin_mv=1200.0,
                end_mv=5188.0,
                bod_cf=3000.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-18",
                "beginning_market_value": "1200.0",
                "ending_market_value": "5188.0",
                "bod_cashflow": "4000.0",
                "cash_flows": [],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH"}
    assert result.evidence_summary["external_cashflow_normalization_gap_count"] == 1


def test_analyze_source_economics_flags_external_timing_bucket_contradiction():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 19),
        metric_basis="NET",
        report_end_date=date(2026, 3, 19),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 19),
                begin_mv=5188.0,
                end_mv=3188.0,
                bod_cf=0.0,
                eod_cf=-2000.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-19",
                "beginning_market_value": "5188.0",
                "ending_market_value": "3188.0",
                "bod_cashflow": "-2000.0",
                "cash_flows": [
                    {"amount": "-2000.0", "timing": "eod", "cash_flow_type": "external_flow"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {
        "EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH",
        "EXTERNAL_CASHFLOW_TIMING_BUCKET_CONTRADICTION",
    }
    assert result.evidence_summary["external_cashflow_timing_contradiction_count"] == 1


def test_analyze_source_economics_flags_mixed_external_timing_buckets():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 24),
        metric_basis="NET",
        report_end_date=date(2026, 3, 24),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 24),
                begin_mv=3200.0,
                end_mv=3200.0,
                bod_cf=1000.0,
                eod_cf=-500.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-24",
                "beginning_market_value": "3200.0",
                "ending_market_value": "3200.0",
                "cash_flows": [
                    {"amount": "1000.0", "timing": "bod", "cash_flow_type": "external_flow"},
                    {"amount": "-500.0", "timing": "eod", "cash_flow_type": "external_flow"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"EXTERNAL_CASHFLOW_MIXED_TIMING_BUCKETS"}
    assert result.evidence_summary["external_cashflow_date_count"] == 1
    assert result.evidence_summary["external_cashflow_normalization_gap_count"] == 0
    assert result.evidence_summary["external_cashflow_mixed_timing_date_count"] == 1
    assert result.artifact_payload["external_cashflow_mixed_timing_samples"] == [
        {
            "valuation_date": "2026-03-24",
            "detailed_external_bod": 1000.0,
            "detailed_external_eod": -500.0,
        }
    ]


def test_analyze_source_economics_flags_explicit_mixed_external_timing_buckets():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 25),
        metric_basis="NET",
        report_end_date=date(2026, 3, 25),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 25),
                begin_mv=3200.0,
                end_mv=3200.0,
                bod_cf=1000.0,
                eod_cf=-500.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-25",
                "beginning_market_value": "3200.0",
                "ending_market_value": "3200.0",
                "bod_cashflow": "1000.0",
                "eod_cashflow": "-500.0",
                "cash_flows": [],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"EXTERNAL_CASHFLOW_EXPLICIT_MIXED_TIMING_BUCKETS"}
    assert result.evidence_summary["external_cashflow_normalization_gap_count"] == 0
    assert result.evidence_summary["external_cashflow_explicit_mixed_timing_date_count"] == 1
    assert result.artifact_payload["external_cashflow_explicit_mixed_timing_samples"] == [
        {
            "valuation_date": "2026-03-25",
            "explicit_external_bod": 1000.0,
            "explicit_external_eod": -500.0,
        }
    ]


def test_analyze_source_economics_flags_invalid_cashflow_amount_rows():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 20),
        metric_basis="NET",
        report_end_date=date(2026, 3, 20),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 20),
                begin_mv=3188.0,
                end_mv=3188.0,
                bod_cf=50.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-20",
                "beginning_market_value": "3188.0",
                "ending_market_value": "3188.0",
                "cash_flows": [
                    {"amount": "n/a", "timing": "eod", "cash_flow_type": "external_flow"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"INVALID_CASHFLOW_AMOUNT_PRESENT"}
    assert result.evidence_summary["invalid_cashflow_amount_date_count"] == 1
    assert result.artifact_payload["invalid_cashflow_amount_samples"] == [
        {
            "valuation_date": "2026-03-20",
            "rows": [{"timing": "eod", "amount": "n/a", "cash_flow_type": "external_flow"}],
        }
    ]


def test_analyze_source_economics_flags_invalid_explicit_source_amounts():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 20),
        metric_basis="NET",
        report_end_date=date(2026, 3, 20),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 20),
                begin_mv=3188.0,
                end_mv=3188.0,
                bod_cf=50.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-20",
                "beginning_market_value": "3188.0",
                "ending_market_value": "3188.0",
                "management_fees": "oops",
                "ending_cash_flow": "bad",
                "cash_flows": [],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"INVALID_EXPLICIT_SOURCE_AMOUNT_PRESENT"}
    assert result.evidence_summary["invalid_explicit_source_amount_date_count"] == 1
    assert result.artifact_payload["invalid_explicit_source_amount_samples"] == [
        {
            "valuation_date": "2026-03-20",
            "rows": [
                {"field": "ending_cash_flow", "semantic": "eod_cashflow_total", "raw_value": "bad"},
                {"field": "management_fees", "semantic": "fee_total", "raw_value": "oops"},
            ],
        }
    ]


def test_analyze_source_economics_flags_invalid_cashflow_collection_shape():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 20),
        metric_basis="NET",
        report_end_date=date(2026, 3, 20),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 20),
                begin_mv=3188.0,
                end_mv=3188.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-20",
                "beginning_market_value": "3188.0",
                "ending_market_value": "3188.0",
                "cash_flows": {"amount": "50.0", "timing": "bod", "cash_flow_type": "external_flow"},
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"INVALID_CASHFLOW_COLLECTION_PRESENT"}
    assert result.evidence_summary["invalid_cashflow_collection_date_count"] == 1
    assert result.evidence_summary["invalid_cashflow_amount_date_count"] == 0
    assert result.artifact_payload["invalid_cashflow_collection_samples"] == [
        {
            "valuation_date": "2026-03-20",
            "raw_type": "dict",
            "raw_value": {"amount": "50.0", "timing": "bod", "cash_flow_type": "external_flow"},
        }
    ]


def test_analyze_source_economics_flags_invalid_cashflow_row_shape():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 20),
        metric_basis="NET",
        report_end_date=date(2026, 3, 20),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 20),
                begin_mv=3188.0,
                end_mv=3188.0,
                bod_cf=50.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-20",
                "beginning_market_value": "3188.0",
                "ending_market_value": "3188.0",
                "cash_flows": [
                    "bad-row",
                    {"amount": "50.0", "timing": "bod", "cash_flow_type": "external_flow"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"INVALID_CASHFLOW_ROW_PRESENT"}
    assert result.evidence_summary["invalid_cashflow_row_date_count"] == 1
    assert result.evidence_summary["external_cashflow_normalization_gap_count"] == 0
    assert result.artifact_payload["invalid_cashflow_row_samples"] == [
        {
            "valuation_date": "2026-03-20",
            "rows": [{"raw_type": "str", "raw_value": "bad-row"}],
        }
    ]


def test_analyze_source_economics_flags_conflicting_explicit_source_alias_values():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 20),
        metric_basis="NET",
        report_end_date=date(2026, 3, 20),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 20),
                begin_mv=3188.0,
                end_mv=3188.0,
                bod_cf=50.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-20",
                "beginning_market_value": "3188.0",
                "ending_market_value": "3188.0",
                "bod_cashflow": "50.0",
                "beginning_cash_flow": "55.0",
                "cash_flows": [],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"CONFLICTING_EXPLICIT_SOURCE_TOTAL_PRESENT"}
    assert result.evidence_summary["conflicting_explicit_source_amount_date_count"] == 1
    assert result.artifact_payload["conflicting_explicit_source_amount_samples"] == [
        {
            "valuation_date": "2026-03-20",
            "rows": [
                {
                    "field": "beginning_cash_flow",
                    "semantic": "bod_cashflow_total",
                    "raw_value": "55.0",
                    "resolved_field": "bod_cashflow",
                    "resolved_value": "50.0",
                    "conflicting_value": "55.0",
                }
            ],
        }
    ]


def test_analyze_source_economics_flags_noncanonical_cashflow_type_labels():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 20),
        metric_basis="NET",
        report_end_date=date(2026, 3, 20),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 20),
                begin_mv=3188.0,
                end_mv=3191.0,
                bod_cf=0.0,
                eod_cf=3.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-20",
                "beginning_market_value": "3188.0",
                "ending_market_value": "3191.0",
                "cash_flows": [
                    {"amount": "3.0", "timing": "eod", "cash_flow_type": "dividend"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {
        "NONCANONICAL_CASHFLOW_TYPE_PRESENT",
        "UNSUPPORTED_CASHFLOW_TYPE_PRESENT",
    }
    assert result.evidence_summary["noncanonical_cashflow_type_date_count"] == 1
    assert result.evidence_summary["unsupported_cashflow_type_date_count"] == 1


def test_analyze_source_economics_accepts_operational_expense_emitted_as_canonical_fee():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 12),
        metric_basis="NET",
        report_end_date=date(2026, 3, 12),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 12),
                begin_mv=1200.0,
                end_mv=925.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=-275.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-12",
                "beginning_market_value": "1200.0",
                "ending_market_value": "925.0",
                "cash_flows": [
                    {
                        "amount": "-275.0",
                        "timing": "eod",
                        "cash_flow_type": "fee",
                        "flow_scope": "operational",
                        "source_classification": "EXPENSE",
                    },
                ],
            }
        ],
    )

    assert result.findings == []
    assert result.evidence_summary["fee_cashflow_date_count"] == 1
    assert result.evidence_summary["external_cashflow_date_count"] == 0
    assert result.evidence_summary["fee_normalization_gap_count"] == 0
    assert result.evidence_summary["noncanonical_cashflow_type_date_count"] == 0
    assert result.evidence_summary["governed_alias_cashflow_type_date_count"] == 0
    assert result.evidence_summary["unsupported_cashflow_type_date_count"] == 0
    assert result.artifact_payload["fee_cashflow_dates"] == ["2026-03-12"]


def test_analyze_source_economics_accepts_refreshed_core_canonical_flow_story():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 5),
        metric_basis="NET",
        report_end_date=date(2026, 3, 26),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 5),
                begin_mv=1200.0,
                end_mv=41200.0,
                bod_cf=40000.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
            DailyInputData(
                perf_date=date(2026, 3, 12),
                begin_mv=41200.0,
                end_mv=40925.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=-275.0,
            ),
            DailyInputData(
                perf_date=date(2026, 3, 26),
                begin_mv=40925.0,
                end_mv=15925.0,
                bod_cf=0.0,
                eod_cf=-25000.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-05",
                "beginning_market_value": "1200.0",
                "ending_market_value": "41200.0",
                "cash_flows": [
                    {"amount": "40000.0", "timing": "bod", "cash_flow_type": "external_flow"},
                ],
            },
            {
                "valuation_date": "2026-03-12",
                "beginning_market_value": "41200.0",
                "ending_market_value": "40925.0",
                "cash_flows": [
                    {
                        "amount": "-275.0",
                        "timing": "eod",
                        "cash_flow_type": "fee",
                        "flow_scope": "operational",
                        "source_classification": "EXPENSE",
                    },
                ],
            },
            {
                "valuation_date": "2026-03-26",
                "beginning_market_value": "40925.0",
                "ending_market_value": "15925.0",
                "cash_flows": [
                    {"amount": "-25000.0", "timing": "eod", "cash_flow_type": "external_flow"},
                ],
            },
        ],
    )

    assert result.findings == []
    assert result.evidence_summary["fee_cashflow_date_count"] == 1
    assert result.evidence_summary["external_cashflow_date_count"] == 2
    assert result.evidence_summary["fee_normalization_gap_count"] == 0
    assert result.evidence_summary["external_cashflow_normalization_gap_count"] == 0
    assert result.evidence_summary["duplicate_external_cashflow_signal_count"] == 0
    assert result.evidence_summary["external_cashflow_source_mismatch_count"] == 0
    assert result.evidence_summary["noncanonical_cashflow_type_date_count"] == 0
    assert result.evidence_summary["unsupported_cashflow_type_date_count"] == 0
    assert result.artifact_payload["fee_cashflow_dates"] == ["2026-03-12"]
    assert result.artifact_payload["external_cashflow_dates"] == ["2026-03-05", "2026-03-26"]


def test_analyze_source_economics_does_not_whitelist_expense_cashflow_type():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 12),
        metric_basis="NET",
        report_end_date=date(2026, 3, 12),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 12),
                begin_mv=1200.0,
                end_mv=925.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-12",
                "beginning_market_value": "1200.0",
                "ending_market_value": "925.0",
                "cash_flows": [
                    {
                        "amount": "-275.0",
                        "timing": "eod",
                        "cash_flow_type": "expense",
                        "flow_scope": "operational",
                        "source_classification": "EXPENSE",
                    },
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {
        "NONCANONICAL_CASHFLOW_TYPE_PRESENT",
        "UNSUPPORTED_CASHFLOW_TYPE_PRESENT",
    }
    assert result.evidence_summary["fee_cashflow_date_count"] == 0
    assert result.evidence_summary["governed_alias_cashflow_type_date_count"] == 0
    assert result.evidence_summary["unsupported_cashflow_type_date_count"] == 1


def test_analyze_source_economics_flags_missing_cashflow_type_labels():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 20),
        metric_basis="NET",
        report_end_date=date(2026, 3, 20),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 20),
                begin_mv=3188.0,
                end_mv=3193.0,
                bod_cf=0.0,
                eod_cf=5.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-20",
                "beginning_market_value": "3188.0",
                "ending_market_value": "3193.0",
                "cash_flows": [
                    {"amount": "5.0", "timing": "eod"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"MISSING_CASHFLOW_TYPE_PRESENT"}
    assert result.evidence_summary["missing_cashflow_type_date_count"] == 1
    assert result.artifact_payload["missing_cashflow_type_samples"] == [
        {
            "valuation_date": "2026-03-20",
            "rows": [{"timing": "eod", "amount": "5.0"}],
        }
    ]
    assert result.artifact_payload["missing_cashflow_type_date_count"] == 1


def test_analyze_source_economics_treats_blank_cashflow_type_as_missing_label():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 22),
        metric_basis="NET",
        report_end_date=date(2026, 3, 22),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 22),
                begin_mv=3193.0,
                end_mv=3197.0,
                bod_cf=0.0,
                eod_cf=4.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-22",
                "beginning_market_value": "3193.0",
                "ending_market_value": "3197.0",
                "cash_flows": [
                    {"amount": "4.0", "timing": "eod", "cash_flow_type": "   "},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"MISSING_CASHFLOW_TYPE_PRESENT"}
    assert result.evidence_summary["missing_cashflow_type_date_count"] == 1
    assert result.evidence_summary["noncanonical_cashflow_type_date_count"] == 0
    assert result.artifact_payload["missing_cashflow_type_samples"] == [
        {
            "valuation_date": "2026-03-22",
            "rows": [{"timing": "eod", "amount": "4.0"}],
        }
    ]
    assert result.artifact_payload["noncanonical_cashflow_types"] == []


def test_analyze_source_economics_flags_invalid_cashflow_timing_labels():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 23),
        metric_basis="NET",
        report_end_date=date(2026, 3, 23),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 23),
                begin_mv=3197.0,
                end_mv=3201.0,
                bod_cf=0.0,
                eod_cf=0.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-23",
                "beginning_market_value": "3197.0",
                "ending_market_value": "3201.0",
                "cash_flows": [
                    {"amount": "4.0", "timing": "intraday", "cash_flow_type": "external_flow"},
                ],
            }
        ],
    )

    assert {finding.code for finding in result.findings} == {"INVALID_CASHFLOW_TIMING_PRESENT"}
    assert result.evidence_summary["invalid_cashflow_timing_date_count"] == 1
    assert result.evidence_summary["missing_cashflow_type_date_count"] == 0
    assert result.artifact_payload["invalid_cashflow_timing_samples"] == [
        {
            "valuation_date": "2026-03-23",
            "rows": [{"timing": "intraday", "amount": "4.0", "cash_flow_type": "external_flow"}],
        }
    ]
    assert result.artifact_payload["invalid_cashflow_timing_date_count"] == 1


def test_analyze_source_economics_artifact_captures_timing_and_taxonomy_samples():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 21),
        metric_basis="NET",
        report_end_date=date(2026, 3, 21),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2026, 3, 21),
                begin_mv=3191.0,
                end_mv=1191.0,
                bod_cf=0.0,
                eod_cf=-2000.0,
                mgmt_fees=0.0,
            ),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-21",
                "beginning_market_value": "3191.0",
                "ending_market_value": "1191.0",
                "bod_cashflow": "-2000.0",
                "cash_flows": [
                    {"amount": "-2000.0", "timing": "eod", "cash_flow_type": "dividend"},
                ],
            }
        ],
    )

    assert result.artifact_payload["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert result.artifact_payload["portfolio_observation_count"] == 1
    assert result.artifact_payload["external_cashflow_date_count"] == 0
    assert result.artifact_payload["external_cashflow_dates"] == []
    assert result.artifact_payload["external_cashflow_timing_contradiction_count"] == 0
    assert result.artifact_payload["external_cashflow_timing_contradiction_samples"] == []
    assert result.artifact_payload["noncanonical_cashflow_type_date_count"] == 1
    assert result.artifact_payload["noncanonical_cashflow_type_samples"] == [
        {
            "valuation_date": "2026-03-21",
            "cash_flow_types": ["dividend"],
        }
    ]
    assert result.artifact_payload["unsupported_cashflow_type_date_count"] == 1
    assert result.artifact_payload["unsupported_cashflow_type_samples"] == [
        {
            "valuation_date": "2026-03-21",
            "cash_flow_types": ["dividend"],
            "rows": [{"timing": "eod", "amount": "-2000.0", "cash_flow_type": "dividend"}],
        }
    ]
    assert result.artifact_payload["missing_cashflow_type_date_count"] == 0
    assert result.artifact_payload["noncanonical_cashflow_types"] == ["dividend"]
    assert result.artifact_payload["unsupported_cashflow_types"] == ["dividend"]


def test_analyze_source_economics_captures_governed_alias_and_raw_collection_samples():
    performance_request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 3, 24),
        metric_basis="NET",
        report_end_date=date(2026, 3, 25),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 3, 24), begin_mv=1000.0, end_mv=1100.0, eod_cf=100.0),
            DailyInputData(perf_date=date(2026, 3, 25), begin_mv=1100.0, end_mv=1100.0),
        ],
    )

    result = analyze_source_economics(
        performance_request=performance_request,
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        observations=[
            {
                "valuation_date": "2026-03-24",
                "beginning_market_value": "1000.0",
                "ending_market_value": "1100.0",
                "cash_flows": [
                    {"amount": "100.0", "timing": "eod", "cash_flow_type": "deposit"},
                    {"amount": "1.0", "timing": "eod", "cash_flow_type": object()},
                ],
            },
            {
                "valuation_date": "2026-03-25",
                "beginning_market_value": "1100.0",
                "ending_market_value": "1100.0",
                "cash_flows": {"bad": "shape"},
            },
        ],
    )

    assert result.evidence_summary["governed_alias_cashflow_type_date_count"] == 1
    assert result.artifact_payload["governed_alias_cashflow_type_samples"] == [
        {
            "valuation_date": "2026-03-24",
            "cash_flow_types": ["deposit"],
            "rows": [{"timing": "eod", "amount": "100.0", "cash_flow_type": "deposit"}],
        }
    ]
    assert result.artifact_payload["invalid_cashflow_collection_samples"] == [
        {
            "valuation_date": "2026-03-25",
            "raw_type": "dict",
            "raw_value": {"bad": "shape"},
        }
    ]
    assert source_economics._sample_raw_collection_value(["not", "scalar"]) == "['not', 'scalar']"
    assert source_economics._parse_decimal(object()) is None


def test_sum_detailed_cash_flows_accumulates_totals_and_row_quality_samples():
    result = source_economics._sum_detailed_cash_flows(
        [
            {"amount": "100.0", "timing": " bod ", "cash_flow_type": "external_flow"},
            {"amount": "-7.5", "timing": "eod", "cash_flow_type": "fee"},
            {"amount": "-2.5", "timing": "bod", "cash_flow_type": "fee"},
            {"amount": "3.0", "timing": "eod"},
            {"amount": "4.0", "timing": "intraday", "cash_flow_type": "external_flow"},
            {"amount": "bad", "timing": "bod", "cash_flow_type": "external_flow"},
            "not-a-row",
        ]
    )

    assert result.external_bod == Decimal("100.0")
    assert result.external_eod == Decimal("3.0")
    assert result.fee_bod == Decimal("-2.5")
    assert result.fee_eod == Decimal("-7.5")
    assert result.missing_cashflow_type_rows == ({"timing": "eod", "amount": "3.0"},)
    assert result.invalid_timing_rows == ({"timing": "intraday", "amount": "4.0", "cash_flow_type": "external_flow"},)
    assert result.invalid_amount_rows == ({"timing": "bod", "amount": "bad", "cash_flow_type": "external_flow"},)
    assert result.invalid_cashflow_rows == ({"raw_type": "str", "raw_value": "not-a-row"},)
    assert result.fee_bod_timing_rows == ({"timing": "bod", "amount": "-2.5", "cash_flow_type": "fee"},)


def test_record_detailed_cash_flow_routes_governed_alias_amount_and_sample():
    accumulator = source_economics._DetailedCashFlowAccumulator()

    source_economics._record_detailed_cash_flow(
        accumulator,
        {"amount": "12.5", "timing": " eod ", "cash_flow_type": "deposit"},
    )

    result = accumulator.to_result()
    assert result.external_eod == Decimal("12.5")
    assert result.governed_alias_cashflow_type_rows == (
        {"timing": "eod", "amount": "12.5", "cash_flow_type": "deposit"},
    )
