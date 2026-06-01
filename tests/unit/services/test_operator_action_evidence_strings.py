import pytest

from app.services.operator_action_evidence_strings import (
    is_optional_evidence_string,
    is_required_evidence_string,
    normalize_optional_evidence_identifier,
    normalize_required_evidence_identifier,
    optional_evidence_string,
    optional_evidence_string_fields_valid,
    required_evidence_bool_fields_present,
    required_evidence_int_fields_present,
    required_evidence_string,
    required_evidence_string_fields_present,
)


def test_normalize_required_evidence_identifier_trims_and_rejects_blank():
    assert normalize_required_evidence_identifier(" ops-user ", field_name="operator_id") == "ops-user"

    with pytest.raises(ValueError, match="operator_id must not be blank"):
        normalize_required_evidence_identifier(" ", field_name="operator_id")


def test_evidence_string_predicates_require_nonblank_strings():
    assert is_required_evidence_string(" ops-user ")
    assert not is_required_evidence_string(" ")
    assert not is_required_evidence_string(123)
    assert is_optional_evidence_string(None)
    assert is_optional_evidence_string(" tenant-a ")
    assert not is_optional_evidence_string(" ")
    assert not is_optional_evidence_string(123)


def test_evidence_field_predicates_validate_string_int_and_bool_sets():
    payload = {
        "operator_id": "ops-user",
        "tenant_id": None,
        "retention_days": 30,
        "apply": False,
    }

    assert required_evidence_string_fields_present(payload, ("operator_id",))
    assert optional_evidence_string_fields_valid(payload, ("tenant_id",))
    assert required_evidence_int_fields_present(payload, ("retention_days",))
    assert required_evidence_bool_fields_present(payload, ("apply",))
    assert not required_evidence_string_fields_present({"operator_id": " "}, ("operator_id",))
    assert not optional_evidence_string_fields_valid({"tenant_id": " "}, ("tenant_id",))
    assert not required_evidence_int_fields_present({"retention_days": True}, ("retention_days",))
    assert not required_evidence_bool_fields_present({"apply": 1}, ("apply",))


def test_normalize_optional_evidence_identifier_trims_blank_to_absent():
    assert normalize_optional_evidence_identifier(" tenant-a ") == "tenant-a"
    assert normalize_optional_evidence_identifier(" ") is None
    assert normalize_optional_evidence_identifier(None) is None


def test_required_evidence_string_trims_and_rejects_invalid_values():
    assert required_evidence_string({"operator_id": " ops-user "}, "operator_id") == "ops-user"

    with pytest.raises(ValueError, match="operator_id must be a nonblank string"):
        required_evidence_string({"operator_id": " "}, "operator_id")


def test_optional_evidence_string_trims_blank_to_absent_and_rejects_non_string():
    assert optional_evidence_string({"tenant_id": " tenant-a "}, "tenant_id") == "tenant-a"
    assert optional_evidence_string({"tenant_id": " "}, "tenant_id") is None
    assert optional_evidence_string({}, "tenant_id") is None

    with pytest.raises(ValueError, match="tenant_id must be a string when present"):
        optional_evidence_string({"tenant_id": 123}, "tenant_id")
