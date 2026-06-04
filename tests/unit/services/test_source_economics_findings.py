from dataclasses import fields

from app.services.inspection.source_economics_collector import SourceEconomicsSamples
from app.services.inspection.source_economics_findings import (
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
