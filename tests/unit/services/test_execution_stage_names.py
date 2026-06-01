from app.services.execution_stage_names import (
    EXECUTION_STAGE_ARTIFACT_MATERIALIZATION,
    EXECUTION_STAGE_EXECUTION,
    EXECUTION_STAGE_FINDING_SYNTHESIS,
    EXECUTION_STAGE_LINEAGE_MATERIALIZATION,
    EXECUTION_STAGE_MATH_RECONCILIATION,
    EXECUTION_STAGE_NORMALIZATION,
    EXECUTION_STAGE_RETRIEVAL,
    EXECUTION_STAGE_SOURCE_ECONOMICS_ASSESSMENT,
    EXECUTION_STAGE_SOURCE_QUALITY_ASSESSMENT,
    EXECUTION_STAGE_SOURCE_STATE_RECONCILIATION,
    EXECUTION_STAGE_SUBJECT_RESOLUTION,
    EXECUTION_STAGE_SUBMISSION,
)


def test_stateful_mode_execution_stage_names_are_canonical():
    assert EXECUTION_STAGE_RETRIEVAL == "retrieval"
    assert EXECUTION_STAGE_NORMALIZATION == "normalization"
    assert EXECUTION_STAGE_SUBMISSION == "submission"


def test_execution_lifecycle_stage_names_are_canonical():
    assert EXECUTION_STAGE_EXECUTION == "execution"
    assert EXECUTION_STAGE_LINEAGE_MATERIALIZATION == "lineage_materialization"


def test_inspection_artifact_stage_name_is_canonical():
    assert EXECUTION_STAGE_ARTIFACT_MATERIALIZATION == "artifact_materialization"


def test_twr_inspection_stage_names_are_canonical():
    assert EXECUTION_STAGE_SUBJECT_RESOLUTION == "subject_resolution"
    assert EXECUTION_STAGE_MATH_RECONCILIATION == "math_reconciliation"
    assert EXECUTION_STAGE_SOURCE_QUALITY_ASSESSMENT == "source_quality_assessment"
    assert EXECUTION_STAGE_SOURCE_STATE_RECONCILIATION == "source_state_reconciliation"
    assert EXECUTION_STAGE_SOURCE_ECONOMICS_ASSESSMENT == "source_economics_assessment"
    assert EXECUTION_STAGE_FINDING_SYNTHESIS == "finding_synthesis"
