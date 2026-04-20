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
            "support_brief_generation_status": "GENERATED",
            "support_brief_workflow_pack_run_id": "packrun_twr_inspection_support_brief_req_001",
            "weekend_observation_count": 28,
        },
        "artifacts": {
            "support_brief.md": "/performance/inspections/inspection-1/artifacts/support_brief.md",
        },
        "workflow_pack_run": {
            "run_id": "packrun_twr_inspection_support_brief_req_001",
            "runtime_state": "COMPLETED",
            "review_state": "AWAITING_REVIEW",
            "supportability_status": "ACTION_REQUIRED",
            "workflow_authority_owner": "lotus-performance",
            "allowed_review_actions": ["ACCEPT", "REJECT", "REVISE"],
        },
    }


def test_validate_canonical_inspection_summary_accepts_clean_refreshed_core_economics():
    validation = validate_canonical_inspection_summary(_clean_summary())

    assert validation.passed is True
    assert validation.errors == []
    assert validation.summary["finding_codes"] == ["WEEKEND_OBSERVATIONS_PRESENT"]
    assert validation.summary["evidence_summary"]["fee_cashflow_date_count"] == 1
    assert validation.summary["evidence_summary"]["external_cashflow_date_count"] == 2


def test_validate_canonical_inspection_summary_allows_current_canonical_policy_findings_by_default():
    summary = _clean_summary()
    summary["findings"].append({"code": "MONTHLY_RETURN_DAY_DOMINANCE_DETECTED"})

    validation = validate_canonical_inspection_summary(summary)

    assert validation.passed is True
    assert validation.errors == []
    assert validation.summary["finding_codes"] == [
        "WEEKEND_OBSERVATIONS_PRESENT",
        "MONTHLY_RETURN_DAY_DOMINANCE_DETECTED",
    ]


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


def test_validate_canonical_inspection_summary_accepts_required_support_brief_posture():
    validation = validate_canonical_inspection_summary(
        _clean_summary(),
        require_support_brief=True,
    )

    assert validation.passed is True
    assert validation.errors == []
    assert validation.summary["support_brief"]["artifact_path"].endswith("/artifacts/support_brief.md")
    assert validation.summary["support_brief"]["workflow_pack_run"]["run_id"] == (
        "packrun_twr_inspection_support_brief_req_001"
    )


def test_validate_canonical_inspection_summary_rejects_missing_required_support_brief_posture():
    summary = _clean_summary()
    summary["evidence_summary"]["support_brief_generation_status"] = "NOT_CONFIGURED"
    summary["artifacts"] = {}
    summary["workflow_pack_run"] = {}

    validation = validate_canonical_inspection_summary(
        summary,
        require_support_brief=True,
    )

    assert validation.passed is False
    assert validation.errors == [
        "support_brief_generation_status expected 'GENERATED', got 'NOT_CONFIGURED'",
        "support_brief artifact path missing or invalid: None",
        "workflow_pack_run.run_id missing for support brief path",
        "support_brief_workflow_pack_run_id did not match workflow_pack_run.run_id",
        "workflow_pack_run.workflow_authority_owner expected 'lotus-performance', got None",
        "workflow_pack_run.runtime_state expected 'COMPLETED', got None",
        "workflow_pack_run.allowed_review_actions missing for support brief path",
    ]
