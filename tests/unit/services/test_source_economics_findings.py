from dataclasses import fields

from app.services.inspection.source_economics_collector import SourceEconomicsSamples
from app.services.inspection.source_economics_findings import (
    _build_detailed_cashflow_contract_findings,
    _build_external_cashflow_findings,
    _build_fee_source_economics_findings,
    build_source_economics_findings,
)


def _samples(**overrides: list[dict[str, object]]) -> SourceEconomicsSamples:
    values = {field.name: [] for field in fields(SourceEconomicsSamples)}
    values.update(overrides)
    return SourceEconomicsSamples(**values)


def test_build_fee_source_economics_findings_emits_fee_findings_in_source_order():
    samples = _samples(
        fee_normalization_samples=[{"valuation_date": "2026-03-12"}],
        duplicate_fee_signal_samples=[{"valuation_date": "2026-03-13"}],
        fee_timing_bucket_samples=[{"valuation_date": "2026-03-14"}],
    )

    findings = _build_fee_source_economics_findings(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        samples=samples,
    )

    assert [finding.code for finding in findings] == [
        "FEE_CASHFLOW_CLASSIFICATION_NOT_PRESERVED",
        "DUPLICATE_FEE_SOURCE_SIGNAL",
        "FEE_CASHFLOW_TIMING_BUCKET_UNSUPPORTED",
    ]
    assert [finding.owner_repo for finding in findings] == [
        "lotus-performance",
        "lotus-core",
        "lotus-core",
    ]
    assert [finding.severity for finding in findings] == ["high", "high", "warning"]
    assert findings[0].evidence == {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "sample_dates": ["2026-03-12"],
        "samples": [{"valuation_date": "2026-03-12"}],
    }


def test_build_external_cashflow_findings_emits_external_findings_in_source_order():
    samples = _samples(
        external_normalization_samples=[{"valuation_date": "2026-03-12"}],
        duplicate_external_signal_samples=[{"valuation_date": "2026-03-13"}],
        external_source_mismatch_samples=[{"valuation_date": "2026-03-14"}],
        external_timing_contradiction_samples=[{"valuation_date": "2026-03-15"}],
        external_mixed_timing_samples=[{"valuation_date": "2026-03-16"}],
        external_explicit_mixed_timing_samples=[{"valuation_date": "2026-03-17"}],
    )

    findings = _build_external_cashflow_findings(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        samples=samples,
    )

    assert [finding.code for finding in findings] == [
        "EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH",
        "DUPLICATE_EXTERNAL_CASHFLOW_SOURCE_SIGNAL",
        "EXTERNAL_CASHFLOW_SOURCE_TOTAL_MISMATCH",
        "EXTERNAL_CASHFLOW_TIMING_BUCKET_CONTRADICTION",
        "EXTERNAL_CASHFLOW_MIXED_TIMING_BUCKETS",
        "EXTERNAL_CASHFLOW_EXPLICIT_MIXED_TIMING_BUCKETS",
    ]
    assert [finding.owner_repo for finding in findings] == [
        "lotus-performance",
        "lotus-core",
        "lotus-core",
        "lotus-core",
        "lotus-core",
        "lotus-core",
    ]
    assert [finding.severity for finding in findings] == [
        "high",
        "high",
        "high",
        "high",
        "warning",
        "warning",
    ]


def test_build_detailed_cashflow_contract_findings_emits_source_contract_findings_in_order():
    samples = _samples(
        invalid_cashflow_collection_samples=[{"valuation_date": "2026-03-12"}],
        invalid_cashflow_row_samples=[{"valuation_date": "2026-03-13"}],
        invalid_amount_samples=[{"valuation_date": "2026-03-14"}],
        invalid_timing_samples=[{"valuation_date": "2026-03-15"}],
        missing_cashflow_type_samples=[{"valuation_date": "2026-03-16"}],
        noncanonical_cashflow_type_samples=[{"valuation_date": "2026-03-17"}],
        governed_alias_cashflow_type_samples=[{"valuation_date": "2026-03-18"}],
        unsupported_cashflow_type_samples=[{"valuation_date": "2026-03-19"}],
    )

    findings = _build_detailed_cashflow_contract_findings(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        samples=samples,
    )

    assert [finding.code for finding in findings] == [
        "INVALID_CASHFLOW_COLLECTION_PRESENT",
        "INVALID_CASHFLOW_ROW_PRESENT",
        "INVALID_CASHFLOW_AMOUNT_PRESENT",
        "INVALID_CASHFLOW_TIMING_PRESENT",
        "MISSING_CASHFLOW_TYPE_PRESENT",
        "NONCANONICAL_CASHFLOW_TYPE_PRESENT",
        "GOVERNED_ALIAS_CASHFLOW_TYPE_PRESENT",
        "UNSUPPORTED_CASHFLOW_TYPE_PRESENT",
    ]
    assert {finding.owner_repo for finding in findings} == {"lotus-core"}
    assert {finding.severity for finding in findings} == {"warning"}


def test_build_source_economics_findings_preserves_invalid_observation_before_fee_findings():
    samples = _samples(
        invalid_observation_date_samples=[{"valuation_date": None}],
        fee_normalization_samples=[{"valuation_date": "2026-03-12"}],
    )

    findings = build_source_economics_findings(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        samples=samples,
    )

    assert [finding.code for finding in findings] == [
        "INVALID_PORTFOLIO_OBSERVATION_DATE_PRESENT",
        "FEE_CASHFLOW_CLASSIFICATION_NOT_PRESERVED",
    ]


def test_build_source_economics_findings_preserves_external_findings_after_fee_findings():
    samples = _samples(
        fee_normalization_samples=[{"valuation_date": "2026-03-12"}],
        external_normalization_samples=[{"valuation_date": "2026-03-13"}],
        conflicting_explicit_amount_samples=[{"valuation_date": "2026-03-14"}],
    )

    findings = build_source_economics_findings(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        samples=samples,
    )

    assert [finding.code for finding in findings] == [
        "FEE_CASHFLOW_CLASSIFICATION_NOT_PRESERVED",
        "EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH",
        "CONFLICTING_EXPLICIT_SOURCE_TOTAL_PRESENT",
    ]
