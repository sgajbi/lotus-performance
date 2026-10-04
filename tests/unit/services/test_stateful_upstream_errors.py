import pytest

from app.services.durable_failure_classification import classify_durable_failure, load_durable_failure
from app.services.stateful_upstream_errors import (
    raise_for_stateful_control_plane_unavailable,
    raise_for_stateful_source_unavailable,
    stateful_control_plane_unavailable_detail,
)
from core.errors import APIError


def _core_refusal():
    return {
        "type": "https://lotus-platform.dev/problems/query-control-plane/qcp_analytics_insufficient_data",
        "status": 422,
        "error_code": "QCP_ANALYTICS_INSUFFICIENT_DATA",
        "metadata": {"analytics_error_code": "INSUFFICIENT_DATA"},
        "detail": "UNTRUSTED_SECRET_MARKER",
        "title": "UNTRUSTED_SECRET_MARKER",
        "instance": "UNTRUSTED_SECRET_MARKER",
    }


@pytest.mark.parametrize("metadata_product", [None, "PortfolioTimeseriesInput"])
def test_direct_portfolio_source_refusal_survives_durable_replay_without_upstream_text(metadata_product):
    payload = _core_refusal()
    if metadata_product is not None:
        payload["metadata"]["source_product"] = metadata_product
    with pytest.raises(APIError) as caught:
        raise_for_stateful_control_plane_unavailable(
            source_label="stateful portfolio timeseries source",
            upstream_status=422,
            upstream_payload=payload,
            source_product="PortfolioTimeseriesInput",
        )
    failure = classify_durable_failure(caught.value)
    assert failure.status_code == 422
    assert failure.error_code == "QCP_ANALYTICS_INSUFFICIENT_DATA"
    assert failure.retryable is False
    assert "UNTRUSTED_SECRET_MARKER" not in failure.to_json()
    restored = load_durable_failure(failure.to_json(), identity="test")
    assert restored == failure
    assert restored.to_api_error().retryable is False


@pytest.mark.parametrize("payload", [None, [], "unknown", {}, {"detail": "UNTRUSTED_SECRET_MARKER"}])
def test_unrecognized_body_shape_is_safe_and_retryable(payload):
    with pytest.raises(APIError) as caught:
        raise_for_stateful_control_plane_unavailable(
            source_label="stateful portfolio timeseries source",
            upstream_status=422,
            upstream_payload=payload,
            source_product="PortfolioTimeseriesInput",
        )
    assert caught.value.status_code == 503
    assert caught.value.retryable is True
    assert "UNTRUSTED_SECRET_MARKER" not in str(caught.value)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502, 503, 504])
def test_recognized_body_cannot_override_http_status(status):
    with pytest.raises(APIError) as caught:
        raise_for_stateful_control_plane_unavailable(
            source_label="stateful portfolio timeseries source",
            upstream_status=status,
            upstream_payload=_core_refusal(),
            source_product="PortfolioTimeseriesInput",
        )
    assert caught.value.status_code == 503
    assert caught.value.retryable is True
    assert "UNTRUSTED_SECRET_MARKER" not in str(caught.value)


@pytest.mark.parametrize(
    "override",
    [
        {"status": "422"},
        {"status": True},
        {"status": 400},
        {"type": "https://untrusted.example/qcp_analytics_insufficient_data"},
        {"error_code": "QCP_ANALYTICS_UNSUPPORTED_CONFIGURATION"},
        {"metadata": None},
        {"metadata": {"analytics_error_code": "NOT_READY"}},
        {"metadata": {"analytics_error_code": "INSUFFICIENT_DATA", "source_product": "AnalyticsExportJob"}},
        {"retryable": True},
    ],
)
def test_mismatched_or_eventual_source_refusals_keep_existing_retry_policy(override):
    payload = _core_refusal() | override
    with pytest.raises(APIError) as caught:
        raise_for_stateful_control_plane_unavailable(
            source_label="stateful portfolio timeseries source",
            upstream_status=422,
            upstream_payload=payload,
            source_product="PortfolioTimeseriesInput",
        )
    assert caught.value.status_code == 503
    assert caught.value.retryable is True


@pytest.mark.parametrize("product", [None, "AnalyticsExportJob", "PositionTimeseriesInput"])
def test_refusal_recognition_requires_direct_portfolio_product(product):
    with pytest.raises(APIError) as caught:
        raise_for_stateful_control_plane_unavailable(
            source_label="stateful portfolio timeseries source",
            upstream_status=422,
            upstream_payload=_core_refusal(),
            source_product=product,
        )
    assert caught.value.status_code == 503
    assert caught.value.retryable is True


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
    with pytest.raises(APIError) as exc:
        raise_for_stateful_control_plane_unavailable(
            source_label="stateful position timeseries source",
            upstream_status=503,
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "stateful position timeseries source unavailable (503)."


def test_raise_for_stateful_source_unavailable_preserves_plain_source_outage_message():
    assert raise_for_stateful_source_unavailable(source_label="benchmark assignment", upstream_status=200) is None

    with pytest.raises(APIError) as exc:
        raise_for_stateful_source_unavailable(source_label="benchmark assignment", upstream_status=404)

    assert exc.value.status_code == 503
    assert exc.value.detail == "benchmark assignment source unavailable (404)."
    assert "CORE_CONTROL_PLANE_BASE_URL" not in exc.value.detail


def test_raise_for_stateful_source_unavailable_preserves_context_suffix():
    with pytest.raises(APIError) as exc:
        raise_for_stateful_source_unavailable(
            source_label="fx rate",
            upstream_status=503,
            context="for USD/SGD",
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "fx rate source unavailable for USD/SGD (503)."
