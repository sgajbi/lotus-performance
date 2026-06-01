import pytest

from app.services.operator_action_evidence_strings import (
    normalize_optional_evidence_identifier,
    normalize_required_evidence_identifier,
    optional_evidence_string,
    required_evidence_string,
)


def test_normalize_required_evidence_identifier_trims_and_rejects_blank():
    assert normalize_required_evidence_identifier(" ops-user ", field_name="operator_id") == "ops-user"

    with pytest.raises(ValueError, match="operator_id must not be blank"):
        normalize_required_evidence_identifier(" ", field_name="operator_id")


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
