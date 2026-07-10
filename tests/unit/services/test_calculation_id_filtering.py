from pathlib import Path

from app.services.calculation_id_filtering import normalize_calculation_id_prefix

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_normalize_calculation_id_prefix_uses_canonical_lowercase():
    assert normalize_calculation_id_prefix("ABCDEF12") == "abcdef12"
    assert normalize_calculation_id_prefix(None) is None


def test_runtime_operator_calculation_id_filters_do_not_use_substring_contains():
    for relative_path in (
        "app/services/compute_job_store.py",
        "app/services/lineage_metadata_store.py",
    ):
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")

        assert ".calculation_id.contains(" not in text
        assert "apply_calculation_id_prefix_filter(" in text
