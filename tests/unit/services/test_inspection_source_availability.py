import pytest

from app.services.inspection.source_availability import raise_inspection_source_unavailable


def test_raise_inspection_source_unavailable_formats_source_and_inspection_context():
    with pytest.raises(RuntimeError) as exc:
        raise_inspection_source_unavailable(
            source_label="Position timeseries",
            inspection_label="reconciliation",
            status_code=503,
        )

    assert str(exc.value) == "Position timeseries source unavailable for reconciliation inspection (503)."
