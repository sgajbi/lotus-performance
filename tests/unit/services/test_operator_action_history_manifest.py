import logging

from app.services.operator_action_history_manifest import (
    HistoryManifestHeader,
    HistoryManifestReadReasons,
    build_history_manifest_payload,
    read_history_manifest_payload,
    validate_history_entry_strings,
    validate_history_manifest_header,
    validate_history_manifest_payload,
)


def _read_reasons() -> HistoryManifestReadReasons:
    return HistoryManifestReadReasons(
        directory_missing="directory_missing",
        manifest_missing="manifest_missing",
        manifest_unreadable="manifest_unreadable",
        manifest_invalid="manifest_invalid",
    )


def test_read_history_manifest_payload_maps_missing_directory(tmp_path):
    result = read_history_manifest_payload(
        directory=tmp_path / "missing",
        reasons=_read_reasons(),
    )

    assert result.payload is None
    assert result.reason == "directory_missing"


def test_read_history_manifest_payload_maps_missing_manifest(tmp_path):
    result = read_history_manifest_payload(directory=tmp_path, reasons=_read_reasons())

    assert result.payload is None
    assert result.reason == "manifest_missing"


def test_read_history_manifest_payload_maps_unreadable_manifest(tmp_path, monkeypatch, caplog):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    def _raise_os_error(*args, **kwargs):  # noqa: ARG001
        raise OSError("denied")

    monkeypatch.setattr(manifest_path.__class__, "read_text", _raise_os_error)

    with caplog.at_level(logging.WARNING, logger="app.services.operator_action_history_manifest"):
        result = read_history_manifest_payload(directory=tmp_path, reasons=_read_reasons())

    assert result.payload is None
    assert result.reason == "manifest_unreadable"
    assert f"Operator action history manifest unreadable at {manifest_path}" in caplog.text
    assert "OSError: denied" in caplog.text


def test_read_history_manifest_payload_maps_invalid_json(tmp_path, caplog):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="app.services.operator_action_history_manifest"):
        result = read_history_manifest_payload(directory=tmp_path, reasons=_read_reasons())

    assert result.payload is None
    assert result.reason == "manifest_invalid"
    assert f"Operator action history manifest invalid at {manifest_path}" in caplog.text
    assert "json.decoder.JSONDecodeError" in caplog.text


def test_read_history_manifest_payload_returns_payload(tmp_path):
    (tmp_path / "manifest.json").write_text('{"entries": []}', encoding="utf-8")

    result = read_history_manifest_payload(directory=tmp_path, reasons=_read_reasons())

    assert result.payload == {"entries": []}
    assert result.reason is None


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


def test_validate_history_manifest_payload_projects_validated_entries():
    payload = {
        "latest_file_name": "latest.json",
        "retained_file_names": ["latest.json"],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [{"evidence_file_name": "latest.json", "status": "passed"}],
    }

    result = validate_history_manifest_payload(
        payload,
        validate_entry=lambda entry: {"status": entry["status"]} if isinstance(entry, dict) else None,
    )

    assert result == {
        "latest_file_name": "latest.json",
        "retained_file_names": ["latest.json"],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [{"status": "passed"}],
    }


def test_validate_history_manifest_payload_rejects_bad_header_or_entry():
    assert validate_history_manifest_payload(None, validate_entry=lambda entry: {}) is None
    assert (
        validate_history_manifest_payload(
            {
                "latest_file_name": None,
                "retained_file_names": [],
                "entries": [{"evidence_file_name": "bad.json"}],
            },
            validate_entry=lambda entry: None,
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
    assert (
        validate_history_entry_strings(
            {
                "evidence_file_name": "evidence.json",
                "generated_at_utc": "2026-03-15T00:00:00Z",
                "operator_id": "   ",
            },
            required_keys=("evidence_file_name", "generated_at_utc", "operator_id"),
            optional_keys=(),
        )
        is None
    )


def test_build_history_manifest_payload_projects_header_and_entries():
    header = HistoryManifestHeader(
        latest_file_name="latest.json",
        retained_file_names=["latest.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[{"raw": "entry"}],
    )
    entries = [{"evidence_file_name": "latest.json"}]

    assert build_history_manifest_payload(header=header, entries=entries) == {
        "latest_file_name": "latest.json",
        "retained_file_names": ["latest.json"],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": entries,
    }
