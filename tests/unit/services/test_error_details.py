from app.services.error_details import coded_error_detail


def test_coded_error_detail_preserves_public_error_shape():
    assert coded_error_detail(code="INSUFFICIENT_DATA", message="No observations.") == {
        "code": "INSUFFICIENT_DATA",
        "message": "No observations.",
    }
