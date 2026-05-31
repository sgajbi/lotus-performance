from app.services.operator_action_history_manifest import (
    validate_history_entry_strings,
    validate_history_manifest_header,
)


def test_validate_history_manifest_header_accepts_safe_payload():
    header = validate_history_manifest_header(
        {
            "latest_file_name": "latest.json",
            "retained_file_names": ["latest.json", "previous.json"],
            "retention_limit": 30,
            "retention_max_age_days": 90,
            "entries": [{"evidence_file_name": "latest.json"}],
        }
    )

    assert header is not None
    assert header.latest_file_name == "latest.json"
    assert header.retained_file_names == ["latest.json", "previous.json"]
    assert header.retention_limit == 30
    assert header.retention_max_age_days == 90
    assert header.entries == [{"evidence_file_name": "latest.json"}]


def test_validate_history_manifest_header_rejects_unsafe_file_names():
    assert (
        validate_history_manifest_header(
            {
                "latest_file_name": "../outside.json",
                "retained_file_names": ["../outside.json"],
                "entries": [],
            }
        )
        is None
    )
    assert (
        validate_history_manifest_header(
            {
                "latest_file_name": None,
                "retained_file_names": ["nested/evidence.json"],
                "entries": [],
            }
        )
        is None
    )


def test_validate_history_manifest_header_rejects_mismatched_latest_file():
    assert (
        validate_history_manifest_header(
            {
                "latest_file_name": "missing.json",
                "retained_file_names": ["latest.json"],
                "entries": [],
            }
        )
        is None
    )


def test_validate_history_entry_strings_accepts_required_and_optional_values():
    assert validate_history_entry_strings(
        {
            "evidence_file_name": "evidence.json",
            "generated_at_utc": "2026-03-15T00:00:00Z",
            "operator_id": "ops-user",
            "tenant_id": None,
            "status": "passed",
        },
        required_keys=("evidence_file_name", "generated_at_utc", "operator_id", "status"),
        optional_keys=("tenant_id", "correlation_id"),
    ) == {
        "evidence_file_name": "evidence.json",
        "generated_at_utc": "2026-03-15T00:00:00Z",
        "operator_id": "ops-user",
        "status": "passed",
        "tenant_id": None,
        "correlation_id": None,
    }


def test_validate_history_entry_strings_rejects_bad_required_or_optional_values():
    assert (
        validate_history_entry_strings(
            {
                "evidence_file_name": "nested/evidence.json",
                "generated_at_utc": "2026-03-15T00:00:00Z",
                "operator_id": "ops-user",
            },
            required_keys=("evidence_file_name", "generated_at_utc", "operator_id"),
            optional_keys=(),
        )
        is None
    )
    assert (
        validate_history_entry_strings(
            {
                "evidence_file_name": "evidence.json",
                "generated_at_utc": "2026-03-15T00:00:00Z",
                "operator_id": "ops-user",
                "tenant_id": 123,
            },
            required_keys=("evidence_file_name", "generated_at_utc", "operator_id"),
            optional_keys=("tenant_id",),
        )
        is None
    )
