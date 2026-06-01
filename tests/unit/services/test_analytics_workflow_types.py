from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR, ANALYTICS_WORKFLOW_TWR_INSPECTION


def test_twr_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_TWR == "TWR"


def test_twr_inspection_workflow_type_is_canonical():
    assert ANALYTICS_WORKFLOW_TWR_INSPECTION == "TWR_INSPECTION"
