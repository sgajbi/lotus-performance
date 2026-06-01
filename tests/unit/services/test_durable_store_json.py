import logging

from app.services.durable_store_json import load_json_object_or_none


def test_load_json_object_or_none_returns_object_payload(caplog):
    logger = logging.getLogger("tests.durable_store_json")

    with caplog.at_level(logging.WARNING, logger="tests.durable_store_json"):
        payload = load_json_object_or_none(
            '{"ok": true}',
            logger=logger,
            payload_name="Test payload",
            identity_name="calculation_id",
            identity_value="calc-1",
        )

    assert payload == {"ok": True}
    assert caplog.text == ""


def test_load_json_object_or_none_logs_invalid_and_non_object_payloads(caplog):
    logger = logging.getLogger("tests.durable_store_json")

    with caplog.at_level(logging.WARNING, logger="tests.durable_store_json"):
        invalid = load_json_object_or_none(
            "{not-json",
            logger=logger,
            payload_name="Test payload",
            identity_name="calculation_id",
            identity_value="calc-1",
        )
        non_object = load_json_object_or_none(
            "[1, 2, 3]",
            logger=logger,
            payload_name="Test payload",
            identity_name="calculation_id",
            identity_value="calc-2",
        )

    assert invalid is None
    assert non_object is None
    assert "Test payload invalid JSON for calculation_id=calc-1." in caplog.text
    assert "Test payload is not an object for calculation_id=calc-2." in caplog.text


def test_load_json_object_or_none_ignores_absent_payload(caplog):
    logger = logging.getLogger("tests.durable_store_json")

    with caplog.at_level(logging.WARNING, logger="tests.durable_store_json"):
        payload = load_json_object_or_none(
            None,
            logger=logger,
            payload_name="Test payload",
            identity_name="calculation_id",
            identity_value="calc-1",
        )

    assert payload is None
    assert caplog.text == ""


def test_load_json_object_or_none_can_treat_empty_payload_as_invalid(caplog):
    logger = logging.getLogger("tests.durable_store_json")

    with caplog.at_level(logging.WARNING, logger="tests.durable_store_json"):
        payload = load_json_object_or_none(
            "",
            logger=logger,
            payload_name="Required payload",
            identity_name="calculation_id",
            identity_value="calc-1",
            empty_is_absent=False,
        )

    assert payload is None
    assert "Required payload invalid JSON for calculation_id=calc-1." in caplog.text
