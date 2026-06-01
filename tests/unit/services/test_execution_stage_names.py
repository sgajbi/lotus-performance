from app.services.execution_stage_names import EXECUTION_STAGE_NORMALIZATION, EXECUTION_STAGE_RETRIEVAL


def test_stateful_mode_execution_stage_names_are_canonical():
    assert EXECUTION_STAGE_RETRIEVAL == "retrieval"
    assert EXECUTION_STAGE_NORMALIZATION == "normalization"
