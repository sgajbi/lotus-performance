from app.services.error_details import (
    coded_error_detail,
    error_code_for_status,
    insufficient_data_detail,
    invalid_request_detail,
    resource_not_found_detail,
    safe_error_envelope,
    source_unavailable_detail,
    upstream_contract_violation_detail,
)
from core.errors import (
    HTTP_404_NOT_FOUND,
    HTTP_422_UNPROCESSABLE,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_503_SERVICE_UNAVAILABLE,
)


def test_coded_error_detail_preserves_public_error_shape():
    assert coded_error_detail(code="INSUFFICIENT_DATA", message="No observations.") == {
        "code": "INSUFFICIENT_DATA",
        "message": "No observations.",
    }


def test_shared_error_detail_builders_preserve_governed_codes():
    assert source_unavailable_detail("Source down.") == {
        "code": "SOURCE_UNAVAILABLE",
        "message": "Source down.",
        "retryable": True,
    }
    assert resource_not_found_detail("Missing source.") == {
        "code": "RESOURCE_NOT_FOUND",
        "message": "Missing source.",
    }
    assert insufficient_data_detail("No observations.") == {
        "code": "INSUFFICIENT_DATA",
        "message": "No observations.",
    }
    assert invalid_request_detail("Bad request.") == {
        "code": "INVALID_REQUEST",
        "message": "Bad request.",
    }
    assert upstream_contract_violation_detail("Bad upstream shape.") == {
        "code": "CONTRACT_VIOLATION_UPSTREAM",
        "message": "Bad upstream shape.",
    }


def test_error_code_for_status_preserves_public_status_mapping():
    assert error_code_for_status(HTTP_404_NOT_FOUND) == "RESOURCE_NOT_FOUND"
    assert error_code_for_status(HTTP_422_UNPROCESSABLE) == "INVALID_REQUEST"
    assert error_code_for_status(HTTP_503_SERVICE_UNAVAILABLE) == "SOURCE_UNAVAILABLE"
    assert error_code_for_status(HTTP_500_INTERNAL_SERVER_ERROR) == "INTERNAL_SERVER_ERROR"


def test_safe_error_envelope_preserves_client_details_and_masks_server_details():
    client_envelope = safe_error_envelope(
        status_code=HTTP_404_NOT_FOUND,
        detail={"message": "No benchmark assignment found."},
    )
    retryable_envelope = safe_error_envelope(
        status_code=HTTP_503_SERVICE_UNAVAILABLE,
        detail=source_unavailable_detail("Benchmark source unavailable."),
    )
    server_envelope = safe_error_envelope(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        detail="database password leaked",
    )

    assert client_envelope["error_code"] == "RESOURCE_NOT_FOUND"
    assert client_envelope["detail"] == {"message": "No benchmark assignment found."}
    assert client_envelope["message"] == "No benchmark assignment found."
    assert client_envelope["retryable"] is False
    assert retryable_envelope["error_code"] == "SOURCE_UNAVAILABLE"
    assert retryable_envelope["message"] == "Benchmark source unavailable."
    assert retryable_envelope["retryable"] is True
    assert server_envelope["detail"] == (
        "The service encountered an internal error. Use the correlation_id for support."
    )
    assert server_envelope["message"] == (
        "The service encountered an internal error. Use the correlation_id for support."
    )
