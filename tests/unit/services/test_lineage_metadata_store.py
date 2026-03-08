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
