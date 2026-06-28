from datetime import date
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.models.contribution_analytics_requests import ContributionInputMode
from app.models.contribution_requests import ContributionRequest
from app.services import contribution_evidence
from app.services.contribution_source_economics import (
    _has_caller_supplied_position_flows,
    _has_non_zero_flow,
    _has_position_currency_metadata,
    _has_stateful_external_flow_economics,
    _has_unclassified_position_metadata,
    _has_unsupported_cash_flow_types,
    _is_non_zero_flow_field,
    _is_valid_source_cash_flow_type_count,
    _present_component_pnl_fields,
    _raw_source_cash_flow_type_counts,
    _source_cash_flow_type_counts,
    _stateful_cash_flow_economics,
    _stateful_metadata_economics,
    _stateful_reason_codes,
    _stateful_source_economics_evidence,
    _upstream_snapshot_lineage_reason_code,
    build_contribution_source_economics_evidence,
)
from app.services.execution_registry import UpstreamSnapshotRecord


def _request_with_position_meta(meta: dict) -> ContributionRequest:
    return ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "report_start_date": "2026-03-01",
            "report_end_date": "2026-03-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2026-03-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2026-03-02", "begin_mv": 1010, "end_mv": 1020},
                ],
            },
            "positions_data": [
                {
                    "position_id": "PB_SG_GLOBAL_BAL_001:SEC_A",
                    "meta": meta,
                    "valuation_points": [
                        {"perf_date": "2026-03-01", "begin_mv": 600, "end_mv": 606},
                        {"perf_date": "2026-03-02", "begin_mv": 606, "end_mv": 612},
                    ],
                }
            ],
        }
    )


def _snapshot(endpoint: str) -> UpstreamSnapshotRecord:
    return UpstreamSnapshotRecord(
        snapshot_id=f"{endpoint}-snapshot",
        upstream_endpoint=endpoint,
        source_identifier="PB_SG_GLOBAL_BAL_001",
        as_of_date=str(date(2026, 3, 2)),
        request_fingerprint=f"{endpoint}-request",
        response_fingerprint=f"{endpoint}-response",
        retrieval_status="200",
        paging_metadata={"page_token": None},
        created_at_utc="2026-03-02T00:00:00Z",
    )


def test_source_economics_evidence_preserves_source_rich_stateful_contract():
    request = _request_with_position_meta(
        {
            "asset_class": "Equity",
            "sector": "Technology",
            "position_to_portfolio_fx_rate": "1.10",
            "portfolio_to_reporting_fx_rate": "1.20",
            "_source_economics": {
                "cash_flow_type_counts": {
                    "external_flow": 1,
                    "internal_trade_flow": 1,
                    "fee": 1,
                }
            },
        }
    )

    evidence = build_contribution_source_economics_evidence(
        request=request,
        input_mode=ContributionInputMode.STATEFUL,
        upstream_snapshots=[_snapshot("portfolio_timeseries"), _snapshot("position_timeseries")],
    )

    assert evidence.source_owner == "lotus-core"
    assert evidence.status == "SOURCE_LIMITED"
    assert "external_flows" in evidence.available_economics
    assert "internal_trade_flows" in evidence.available_economics
    assert "fees" in evidence.available_economics
    assert "fx_rates" in evidence.available_economics
    assert evidence.cash_flow_type_counts["internal_trade_flow"] == 1
    assert evidence.source_snapshot_endpoints == ["portfolio_timeseries", "position_timeseries"]
    assert "COMPONENT_PNL_NOT_SOURCE_AUTHORED" in evidence.reason_codes
    assert "income_pnl" in evidence.unsupported_economics


def test_source_economics_evidence_consumes_core_performance_component_economics_coverage():
    request = _request_with_position_meta(
        {
            "asset_class": "Equity",
            "_source_economics": {
                "cash_flow_type_counts": {
                    "external_flow": 1,
                },
                "performance_component_economics": {
                    "source_contract": "PerformanceComponentEconomics:v1",
                    "retrieval_status": 200,
                    "supportability_state": "READY",
                    "supportability_reason": "PERFORMANCE_COMPONENT_ECONOMICS_READY",
                    "source_row_count": 4,
                    "observed_component_families": [
                        "income",
                        "tax",
                        "fee",
                        "realized_capital_pnl",
                        "realized_fx_pnl",
                    ],
                    "missing_component_families": ["cashflow"],
                    "supported_component_families": [
                        "cashflow",
                        "fee",
                        "income",
                        "tax",
                        "realized_capital_pnl",
                        "realized_fx_pnl",
                    ],
                },
            },
        }
    )

    evidence = build_contribution_source_economics_evidence(
        request=request,
        input_mode=ContributionInputMode.STATEFUL,
        upstream_snapshots=[
            _snapshot("portfolio_timeseries"),
            _snapshot("position_timeseries"),
            _snapshot("performance_component_economics"),
        ],
    )

    assert "PerformanceComponentEconomics:v1" in evidence.source_contracts
    assert "PERFORMANCE_COMPONENT_ECONOMICS_SOURCE_USED" in evidence.reason_codes
    assert "source_component_income" in evidence.available_economics
    assert "source_component_fees" in evidence.available_economics
    assert "source_component_tax" in evidence.available_economics
    assert "source_realized_capital_pnl" in evidence.available_economics
    assert "source_realized_fx_pnl" in evidence.available_economics
    assert "income_pnl" not in evidence.unsupported_economics
    assert "fee_pnl" not in evidence.unsupported_economics
    assert "tax_pnl" not in evidence.unsupported_economics
    assert "price_pnl" in evidence.unsupported_economics
    assert "fx_pnl" in evidence.unsupported_economics


def test_source_economics_evidence_degrades_unavailable_core_performance_component_economics():
    request = _request_with_position_meta(
        {
            "_source_economics": {
                "performance_component_economics": {
                    "source_contract": "PerformanceComponentEconomics:v1",
                    "retrieval_status": 503,
                    "supportability_state": "UNAVAILABLE",
                    "supportability_reason": "PERFORMANCE_COMPONENT_ECONOMICS_UNAVAILABLE",
                    "source_row_count": 0,
                    "observed_component_families": [],
                    "missing_component_families": ["fee", "income", "tax"],
                    "supported_component_families": ["fee", "income", "tax"],
                }
            },
        }
    )

    evidence = build_contribution_source_economics_evidence(
        request=request,
        input_mode=ContributionInputMode.STATEFUL,
        upstream_snapshots=[_snapshot("performance_component_economics")],
    )

    assert evidence.status == "SOURCE_LIMITED"
    assert "performance_component_economics_unavailable" in evidence.degraded_economics
    assert "PERFORMANCE_COMPONENT_ECONOMICS_UNAVAILABLE" in evidence.reason_codes
    assert "source_component_income" not in evidence.available_economics
    assert "income_pnl" in evidence.unsupported_economics


def test_source_economics_evidence_does_not_use_partial_component_coverage_as_source_backed():
    request = _request_with_position_meta(
        {
            "_source_economics": {
                "performance_component_economics": {
                    "source_contract": "PerformanceComponentEconomics:v1",
                    "retrieval_status": 200,
                    "supportability_state": "UNAVAILABLE",
                    "supportability_reason": "PERFORMANCE_COMPONENT_ECONOMICS_PARTIAL",
                    "source_row_count": 2,
                    "observed_component_families": ["fee", "income", "tax"],
                    "missing_component_families": ["tax"],
                    "supported_component_families": ["fee", "income", "tax"],
                }
            },
        }
    )

    evidence = build_contribution_source_economics_evidence(
        request=request,
        input_mode=ContributionInputMode.STATEFUL,
        upstream_snapshots=[_snapshot("performance_component_economics")],
    )

    assert evidence.status == "SOURCE_LIMITED"
    assert "performance_component_economics_unavailable" in evidence.degraded_economics
    assert "source_component_income" not in evidence.available_economics
    assert "source_component_fees" not in evidence.available_economics
    assert "source_component_tax" not in evidence.available_economics
    assert "income_pnl" in evidence.unsupported_economics
    assert "fee_pnl" in evidence.unsupported_economics
    assert "tax_pnl" in evidence.unsupported_economics


def test_stateful_source_economics_evidence_reports_source_backed_contract_when_complete():
    request = _request_with_position_meta(
        {
            "asset_class": "Equity",
            "sector": "Technology",
            "price_pnl": 1,
            "income_pnl": 2,
            "fee_pnl": 3,
            "tax_pnl": 4,
            "fx_pnl": 5,
            "corporate_action_pnl": 6,
            "derivative_pnl": 7,
            "cash_pnl": 8,
            "residual_pnl": 9,
            "_source_economics": {
                "cash_flow_type_counts": {
                    "external_flow": 1,
                    "fee": 2,
                }
            },
        }
    )

    evidence = _stateful_source_economics_evidence(
        request=request,
        upstream_snapshots=[_snapshot("portfolio_timeseries")],
    )

    assert evidence.status == "SOURCE_BACKED"
    assert evidence.unsupported_economics == []
    assert evidence.degraded_economics == []
    assert evidence.cash_flow_type_counts == {"external_flow": 1, "fee": 2}
    assert evidence.source_snapshot_count == 1
    assert evidence.source_snapshot_endpoints == ["portfolio_timeseries"]
    assert "UPSTREAM_SNAPSHOT_LINEAGE_AVAILABLE" in evidence.reason_codes


def test_stateful_reason_codes_project_snapshot_lineage_policy():
    assert _upstream_snapshot_lineage_reason_code([_snapshot("portfolio_timeseries")]) == (
        "UPSTREAM_SNAPSHOT_LINEAGE_AVAILABLE"
    )
    assert _upstream_snapshot_lineage_reason_code([]) == "UPSTREAM_SNAPSHOT_LINEAGE_AVAILABLE_VIA_EXECUTION_ONLY"
    assert _stateful_reason_codes(
        unsupported_economics=[],
        degraded_economics=[],
        upstream_snapshots=[],
    ) == [
        "LOTUS_CORE_ANALYTICS_INPUTS_USED",
        "UPSTREAM_SNAPSHOT_LINEAGE_AVAILABLE_VIA_EXECUTION_ONLY",
    ]


def test_stateful_cash_flow_economics_projects_supported_source_flow_families():
    economics = _stateful_cash_flow_economics(
        {
            "external_flow": 1,
            "transfer": 1,
            "internal_trade_flow": 2,
            "fee": 3,
            "dividend": 4,
        }
    )

    assert economics == ["external_flows", "internal_trade_flows", "fees"]


def test_has_stateful_external_flow_economics_accepts_external_flows_and_transfers():
    assert _has_stateful_external_flow_economics({"external_flow": 1})
    assert _has_stateful_external_flow_economics({"transfer": 1})
    assert not _has_stateful_external_flow_economics({"internal_trade_flow": 1, "fee": 1})


def test_stateful_metadata_economics_projects_fx_and_classification_dimensions():
    request = _request_with_position_meta(
        {
            "asset_class": "Equity",
            "position_to_portfolio_fx_rate": "1.10",
        }
    )

    assert _stateful_metadata_economics(request) == ["fx_rates", "classification_dimensions"]


def test_source_cash_flow_type_counts_accepts_positive_integer_counts_only():
    counts = _source_cash_flow_type_counts(
        {
            "_source_economics": {
                "cash_flow_type_counts": {
                    "external_flow": 2,
                    "fee": True,
                    "zero": 0,
                    "negative": -1,
                    1: 3,
                }
            }
        }
    )

    assert counts == {"external_flow": 2}


def test_raw_source_cash_flow_type_counts_resolves_only_dict_payloads():
    raw_counts = {"external_flow": 2}

    assert _raw_source_cash_flow_type_counts({"_source_economics": {"cash_flow_type_counts": raw_counts}}) == raw_counts
    assert _raw_source_cash_flow_type_counts({}) is None
    assert _raw_source_cash_flow_type_counts({"_source_economics": []}) is None
    assert _raw_source_cash_flow_type_counts({"_source_economics": {"cash_flow_type_counts": []}}) is None


def test_source_cash_flow_type_count_entry_validation_rejects_non_source_counts():
    assert _is_valid_source_cash_flow_type_count("external_flow", 2)
    assert not _is_valid_source_cash_flow_type_count("fee", True)
    assert not _is_valid_source_cash_flow_type_count("zero", 0)
    assert not _is_valid_source_cash_flow_type_count(1, 3)


def test_source_cash_flow_type_counts_ignores_missing_or_invalid_source_economics():
    assert _source_cash_flow_type_counts({}) == {}
    assert _source_cash_flow_type_counts({"_source_economics": []}) == {}
    assert _source_cash_flow_type_counts({"_source_economics": {"cash_flow_type_counts": []}}) == {}


def test_source_economics_predicates_identify_unsupported_flows_and_unclassified_metadata():
    request = _request_with_position_meta({"asset_class": "Unclassified"})

    assert _has_unsupported_cash_flow_types({"external_flow": 1, "dividend": 1})
    assert not _has_unsupported_cash_flow_types({"external_flow": 1, "fee": 1, "missing": 1})
    assert _has_unclassified_position_metadata(request)


def test_source_economics_evidence_ignores_boolean_cash_flow_type_counts():
    request = _request_with_position_meta(
        {
            "_source_economics": {
                "cash_flow_type_counts": {
                    "external_flow": 2,
                    "fee": True,
                }
            },
        }
    )

    evidence = build_contribution_source_economics_evidence(
        request=request,
        input_mode=ContributionInputMode.STATEFUL,
        upstream_snapshots=[_snapshot("position_timeseries")],
    )

    assert evidence.cash_flow_type_counts == {"external_flow": 2}
    assert "external_flows" in evidence.available_economics
    assert "fees" not in evidence.available_economics


def test_source_economics_evidence_reports_source_limited_stateful_contract():
    request = _request_with_position_meta(
        {
            "asset_class": "Unclassified",
            "_source_economics": {
                "cash_flow_type_counts": {
                    "dividend": 1,
                }
            },
        }
    )

    evidence = build_contribution_source_economics_evidence(
        request=request,
        input_mode=ContributionInputMode.STATEFUL,
        upstream_snapshots=[],
    )

    assert evidence.status == "SOURCE_LIMITED"
    assert evidence.degraded_economics == [
        "missing_classification",
        "unsupported_cash_flow_types",
        "upstream_snapshot_lineage_not_embedded",
    ]
    assert "UNSUPPORTED_SOURCE_CASH_FLOW_TYPES_PRESENT" in evidence.reason_codes
    assert "UPSTREAM_SNAPSHOT_LINEAGE_AVAILABLE_VIA_EXECUTION_ONLY" in evidence.reason_codes


def test_source_economics_evidence_keeps_stateless_boundary_explicit():
    request = _request_with_position_meta({"currency": "USD"})

    evidence = build_contribution_source_economics_evidence(
        request=request,
        input_mode=ContributionInputMode.STATELESS,
        upstream_snapshots=[],
    )

    assert evidence.status == "CALLER_SUPPLIED"
    assert evidence.source_owner == "caller"
    assert evidence.source_contracts == ["ContributionRequest"]
    assert evidence.source_snapshot_count == 0


def test_stateless_source_economics_predicates_detect_flows_and_currency():
    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "report_start_date": "2026-03-01",
            "report_end_date": "2026-03-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2026-03-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2026-03-02", "begin_mv": 1010, "end_mv": 1020},
                ],
            },
            "positions_data": [
                {
                    "position_id": "PB_SG_GLOBAL_BAL_001:SEC_A",
                    "meta": {"currency": "USD"},
                    "valuation_points": [
                        {
                            "perf_date": "2026-03-01",
                            "begin_mv": 600,
                            "end_mv": 606,
                            "bod_cf": "0",
                            "eod_cf": "0",
                            "mgmt_fees": "1.25",
                        },
                    ],
                },
            ],
        }
    )

    assert _has_caller_supplied_position_flows(request)
    assert _has_position_currency_metadata(request)


def test_stateless_source_economics_flow_predicate_ignores_invalid_raw_flow_values():
    assert _has_non_zero_flow({"bod_cf": "bad-input", "eod_cf": "0", "mgmt_fees": "2"})
    assert not _has_non_zero_flow({"bod_cf": "bad-input", "eod_cf": "0", "mgmt_fees": "0"})


def test_non_zero_flow_field_handles_decimal_zero_and_invalid_values():
    assert _is_non_zero_flow_field({"bod_cf": "0.01"}, "bod_cf")
    assert not _is_non_zero_flow_field({"bod_cf": "0"}, "bod_cf")
    assert not _is_non_zero_flow_field({"bod_cf": "bad-input"}, "bod_cf")
    assert not _is_non_zero_flow_field({}, "bod_cf")


def test_present_component_pnl_fields_aggregates_canonical_fields_across_positions():
    request = _request_with_position_meta({"income_pnl": 15, "fee_pnl": -10, "custom_pnl": 5})

    assert _present_component_pnl_fields(request) == {"income_pnl", "fee_pnl"}


def test_contribution_snapshot_lookup_logs_durable_store_failures(monkeypatch, caplog):
    def _raise_sqlalchemy_error(calculation_id: str):
        raise SQLAlchemyError("durable store unavailable")

    monkeypatch.setattr(
        contribution_evidence.execution_registry,
        "list_upstream_snapshots",
        _raise_sqlalchemy_error,
    )

    with caplog.at_level("WARNING", logger="app.services.contribution_evidence"):
        snapshots = contribution_evidence._list_upstream_snapshots_for_contribution("calc-123")

    assert snapshots == []
    assert "Contribution upstream snapshot lineage lookup failed for calculation_id=calc-123" in caplog.text
