from scripts.validate_canonical_twr_inspection import validate_canonical_inspection_summary


def _clean_summary() -> dict:
    return {
        "inspection_id": "inspection-1",
        "subject_calculation_id": "calculation-1",
        "verdict": "supportable_with_warnings",
        "findings": [{"code": "WEEKEND_OBSERVATIONS_PRESENT"}],
        "check_coverage": {
            "completed_check_families": [
                "calculation_consistency",
                "source_quality",
                "economic_plausibility",
                "reconciliation",
                "cashflow_classification",
            ],
            "pending_check_families": [],
            "failed_check_families": [],
        },
        "evidence_summary": {
            "nonpositive_capital_base_count": 0,
            "reconciliation_gap_date_count": 0,
            "external_cashflow_normalization_gap_count": 0,
            "external_cashflow_timing_contradiction_count": 0,
            "noncanonical_cashflow_type_date_count": 0,
            "unsupported_cashflow_type_date_count": 0,
            "fee_cashflow_date_count": 1,
            "external_cashflow_date_count": 2,
            "largest_abs_daily_move_pct": 0.0141,
            "reconciliation_max_gap_amount": 0,
            "weekend_observation_count": 28,
        },
    }


def test_validate_canonical_inspection_summary_accepts_clean_refreshed_core_economics():
    validation = validate_canonical_inspection_summary(_clean_summary())

    assert validation.passed is True
    assert validation.errors == []
    assert validation.summary["finding_codes"] == ["WEEKEND_OBSERVATIONS_PRESENT"]
    assert validation.summary["evidence_summary"]["fee_cashflow_date_count"] == 1
    assert validation.summary["evidence_summary"]["external_cashflow_date_count"] == 2


def test_validate_canonical_inspection_summary_rejects_source_economics_gaps():
    summary = _clean_summary()
    summary["evidence_summary"]["external_cashflow_normalization_gap_count"] = 1

    validation = validate_canonical_inspection_summary(summary)

    assert validation.passed is False
    assert validation.errors == ["external_cashflow_normalization_gap_count expected 0, got 1"]


def test_validate_canonical_inspection_summary_rejects_unexpected_findings_and_incomplete_checks():
    summary = _clean_summary()
    summary["findings"].append({"code": "NONCANONICAL_CASHFLOW_TYPE_PRESENT"})
    summary["check_coverage"]["completed_check_families"].remove("cashflow_classification")
    summary["check_coverage"]["pending_check_families"] = ["cashflow_classification"]

    validation = validate_canonical_inspection_summary(summary)

    assert validation.passed is False
    assert validation.errors == [
        "disallowed finding codes present: NONCANONICAL_CASHFLOW_TYPE_PRESENT",
        "missing completed check families: cashflow_classification",
        "pending check families are present",
    ]
