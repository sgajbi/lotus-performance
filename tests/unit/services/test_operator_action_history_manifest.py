from app.services.operator_action_history_manifest import validate_history_manifest_header


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
