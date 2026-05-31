import pytest
from fastapi import HTTPException

from app.services.stateful_upstream_errors import (
    raise_for_stateful_control_plane_unavailable,
    raise_for_stateful_source_unavailable,
    stateful_control_plane_unavailable_detail,
)


def test_stateful_control_plane_unavailable_detail_guides_404_base_url_misconfiguration():
    detail = stateful_control_plane_unavailable_detail(
        source_label="stateful portfolio timeseries source",
        upstream_status=404,
    )

    assert detail.startswith("stateful portfolio timeseries source unavailable (404).")
    assert "CORE_CONTROL_PLANE_BASE_URL" in detail
    assert "query-control-plane" in detail


def test_raise_for_stateful_control_plane_unavailable_ignores_success_status():
    assert (
        raise_for_stateful_control_plane_unavailable(
            source_label="stateful portfolio timeseries source",
            upstream_status=200,
        )
        is None
    )


def test_raise_for_stateful_control_plane_unavailable_maps_upstream_failure_to_503():
    with pytest.raises(HTTPException) as exc:
        raise_for_stateful_control_plane_unavailable(
            source_label="stateful position timeseries source",
            upstream_status=503,
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "stateful position timeseries source unavailable (503)."


def test_raise_for_stateful_source_unavailable_preserves_plain_source_outage_message():
    assert raise_for_stateful_source_unavailable(source_label="benchmark assignment", upstream_status=200) is None

    with pytest.raises(HTTPException) as exc:
        raise_for_stateful_source_unavailable(source_label="benchmark assignment", upstream_status=404)

    assert exc.value.status_code == 503
    assert exc.value.detail == "benchmark assignment source unavailable (404)."
    assert "CORE_CONTROL_PLANE_BASE_URL" not in exc.value.detail
