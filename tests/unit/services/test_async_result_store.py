from uuid import uuid4

from app.services.async_result_store import AsyncResultStatus, AsyncResultStore


def test_async_result_store_records_success_and_failure(tmp_path):
    store = AsyncResultStore(f"sqlite:///{tmp_path / 'async_results.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.record_success(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        response_payload={"calculation_id": str(calculation_id), "status": "ok"},
    )
    success = store.get_result(calculation_id)
    assert success is not None
    assert success.result_status == AsyncResultStatus.COMPLETE
    assert success.response_payload == {"calculation_id": str(calculation_id), "status": "ok"}

    store.record_failure(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        error_message="boom",
        error_type="RuntimeError",
    )
    failure = store.get_result(calculation_id)
    assert failure is not None
    assert failure.result_status == AsyncResultStatus.FAILED
    assert failure.response_payload is None
    assert failure.error_message == "boom"
    assert failure.error_type == "RuntimeError"
