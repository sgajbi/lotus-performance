from app.services.execution_stage_names import (
    EXECUTION_STAGE_ARTIFACT_MATERIALIZATION,
    EXECUTION_STAGE_EXECUTION,
    EXECUTION_STAGE_LINEAGE_MATERIALIZATION,
    EXECUTION_STAGE_NORMALIZATION,
    EXECUTION_STAGE_RETRIEVAL,
)


def test_stateful_mode_execution_stage_names_are_canonical():
    assert EXECUTION_STAGE_RETRIEVAL == "retrieval"
    assert EXECUTION_STAGE_NORMALIZATION == "normalization"


def test_execution_lifecycle_stage_names_are_canonical():
    assert EXECUTION_STAGE_EXECUTION == "execution"
    assert EXECUTION_STAGE_LINEAGE_MATERIALIZATION == "lineage_materialization"


def test_inspection_artifact_stage_name_is_canonical():
    assert EXECUTION_STAGE_ARTIFACT_MATERIALIZATION == "artifact_materialization"
