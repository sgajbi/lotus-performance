from app.services.operator_action_evidence_paths import (
    is_safe_evidence_file_name,
    resolve_evidence_file_path,
)


def test_operator_action_evidence_file_name_validation_rejects_paths():
    assert is_safe_evidence_file_name("2026-03-15t00-00-00z.json") is True
    assert is_safe_evidence_file_name("evidence_file.json") is True

    for evidence_file_name in (
        "",
        "../outside.json",
        "nested/evidence.json",
        r"..\outside.json",
        r"nested\evidence.json",
        "/tmp/outside.json",
        r"C:\tmp\outside.json",
    ):
        assert is_safe_evidence_file_name(evidence_file_name) is False


def test_operator_action_evidence_path_resolution_stays_under_artifact_directory(tmp_path):
    artifact_directory = tmp_path / "artifacts"
    artifact_directory.mkdir()

    resolved_path = resolve_evidence_file_path(
        artifact_directory=artifact_directory,
        evidence_file_name="evidence.json",
    )

    assert resolved_path == artifact_directory.resolve() / "evidence.json"
    assert (
        resolve_evidence_file_path(
            artifact_directory=artifact_directory,
            evidence_file_name="../outside.json",
        )
        is None
    )
