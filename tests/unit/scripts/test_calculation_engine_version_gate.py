from pathlib import Path

from scripts.calculation_engine_version_gate import collect_findings


def _write_python(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_calculation_engine_version_gate_rejects_app_version_hash_identity(tmp_path: Path) -> None:
    path = _write_python(
        tmp_path,
        "def build(settings, request):\n    return generate_canonical_hash(request, settings.APP_VERSION)\n",
    )

    findings = collect_findings([path])

    assert [finding.code for finding in findings] == ["APP_VERSION_USED_FOR_CALCULATION_IDENTITY"]


def test_calculation_engine_version_gate_rejects_legacy_returns_series_token(tmp_path: Path) -> None:
    path = _write_python(
        tmp_path,
        "def build(request):\n    return generate_canonical_hash(request, 'returns-series-v1')\n",
    )

    findings = collect_findings([path])

    assert [finding.code for finding in findings] == ["HARDCODED_CALCULATION_ENGINE_VERSION"]


def test_calculation_engine_version_gate_accepts_governed_helper(tmp_path: Path) -> None:
    path = _write_python(
        tmp_path,
        "from app.services.calculation_engine_version import calculation_engine_version\n"
        "def build(settings, request):\n"
        "    return generate_canonical_hash(request, calculation_engine_version(settings))\n",
    )

    assert collect_findings([path]) == []
