import logging

from app.services.durable_store_json import (
    _INVALID_JSON_PAYLOAD,
    _load_json_payload_or_invalid,
    load_json_object_or_none,
    load_json_string_list_or_default,
    read_json_file,
    read_json_object_file,
)


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


def test_load_json_string_list_or_default_returns_valid_string_list(caplog):
    logger = logging.getLogger("tests.durable_store_json")

    with caplog.at_level(logging.WARNING, logger="tests.durable_store_json"):
        payload = load_json_string_list_or_default(
            '["missing_final_valuation"]',
            logger=logger,
            payload_name="Reason codes",
            identity_name="row",
            identity_value="row-1",
            default_value=["invalid_payload"],
        )

    assert payload == ["missing_final_valuation"]
    assert caplog.text == ""


def test_load_json_string_list_or_default_returns_default_for_malformed_payloads(caplog):
    logger = logging.getLogger("tests.durable_store_json")

    with caplog.at_level(logging.WARNING, logger="tests.durable_store_json"):
        invalid_json = load_json_string_list_or_default(
            "{not-json",
            logger=logger,
            payload_name="Reason codes",
            identity_name="row",
            identity_value="row-1",
            default_value=["invalid_payload"],
        )
        invalid_shape = load_json_string_list_or_default(
            '["", 1]',
            logger=logger,
            payload_name="Reason codes",
            identity_name="row",
            identity_value="row-2",
            default_value=["invalid_payload"],
        )

    assert invalid_json == ["invalid_payload"]
    assert invalid_shape == ["invalid_payload"]
    assert "Reason codes invalid JSON for row=row-1." in caplog.text
    assert "Reason codes is not a string list for row=row-2." in caplog.text


def test_load_json_payload_or_invalid_logs_decode_failures(caplog):
    logger = logging.getLogger("tests.durable_store_json")

    with caplog.at_level(logging.WARNING, logger="tests.durable_store_json"):
        valid_payload = _load_json_payload_or_invalid(
            '{"ok": true}',
            logger=logger,
            payload_name="Payload",
            identity_name="row",
            identity_value="row-1",
        )
        invalid_payload = _load_json_payload_or_invalid(
            "{not-json",
            logger=logger,
            payload_name="Payload",
            identity_name="row",
            identity_value="row-2",
        )

    assert valid_payload == {"ok": True}
    assert invalid_payload is _INVALID_JSON_PAYLOAD
    assert "Payload invalid JSON for row=row-2." in caplog.text


def test_read_json_object_file_returns_object_payload(tmp_path):
    payload_path = tmp_path / "payload.json"
    payload_path.write_text('{"ok": true}', encoding="utf-8")

    assert read_json_object_file(payload_path) == {"ok": True}


def test_read_json_object_file_rejects_non_object_payload(tmp_path):
    payload_path = tmp_path / "payload.json"
    payload_path.write_text("[1, 2]", encoding="utf-8")

    try:
        read_json_object_file(payload_path, object_error_message="payload must be an object")
    except TypeError as exc:
        assert str(exc) == "payload must be an object"
    else:
        raise AssertionError("expected non-object payload to raise TypeError")


def test_read_json_file_returns_any_json_payload(tmp_path):
    payload_path = tmp_path / "payload.json"
    payload_path.write_text('["event-a"]', encoding="utf-8")

    assert read_json_file(payload_path) == ["event-a"]
