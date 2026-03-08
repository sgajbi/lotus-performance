from uuid import uuid4

from app.services.lineage_metadata_store import LineageMetadataStore, LineageStatus


def test_lineage_metadata_store_pending_complete_and_failed(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
    pending = store.get_record(calculation_id)
    assert pending is not None
    assert pending.status == LineageStatus.PENDING
    assert pending.artifact_names == []

    store.mark_complete(calculation_id=calculation_id, artifact_names=["response.json", "request.json"])
    complete = store.get_record(calculation_id)
    assert complete is not None
    assert complete.status == LineageStatus.COMPLETE
    assert complete.artifact_names == ["request.json", "response.json"]

    store.mark_failed(calculation_id=calculation_id, error_message="write failed")
    failed = store.get_record(calculation_id)
    assert failed is not None
    assert failed.status == LineageStatus.FAILED
    assert failed.error_message == "write failed"


def test_lineage_metadata_store_raises_for_missing_record_updates(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    calculation_id = uuid4()

    try:
        store.mark_complete(calculation_id=calculation_id, artifact_names=["request.json"])
    except KeyError as exc:
        assert "Lineage record not found" in str(exc)
    else:
        raise AssertionError("Expected mark_complete to raise KeyError")

    try:
        store.mark_failed(calculation_id=calculation_id, error_message="boom")
    except KeyError as exc:
        assert "Lineage record not found" in str(exc)
    else:
        raise AssertionError("Expected mark_failed to raise KeyError")


def test_lineage_metadata_store_payload_queue_roundtrip(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.enqueue_lineage_payload(
        calculation_id=calculation_id,
        calculation_type="TWR",
        request_json='{"request": true}',
        response_json='{"response": true}',
        details={"details.csv": "a,b\n1,2\n"},
    )

    payloads = store.list_pending_payloads(limit=10)
    assert len(payloads) == 1
    assert payloads[0].calculation_id == calculation_id
    assert payloads[0].details == {"details.csv": "a,b\n1,2\n"}
    assert payloads[0].attempt_count == 0

    store.increment_attempt_count(calculation_id)
    assert store.list_pending_payloads(limit=10)[0].attempt_count == 1

    store.delete_payload(calculation_id)
    assert store.list_pending_payloads(limit=10) == []


def test_lineage_metadata_store_raises_when_incrementing_missing_payload(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()

    try:
        store.increment_attempt_count(uuid4())
    except KeyError as exc:
        assert "Lineage payload not found" in str(exc)
    else:
        raise AssertionError("Expected increment_attempt_count to raise KeyError")
