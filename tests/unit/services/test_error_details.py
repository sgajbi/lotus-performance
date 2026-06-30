from app.services.error_details import (
    coded_error_detail,
    insufficient_data_detail,
    invalid_request_detail,
    resource_not_found_detail,
    source_unavailable_detail,
    upstream_contract_violation_detail,
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
