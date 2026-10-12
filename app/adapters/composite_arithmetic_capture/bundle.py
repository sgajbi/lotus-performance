"""Trusted installed source closure, independent of developer paths and CRLF checkout."""

import decimal
import hashlib
import json
import platform
from importlib.resources import files

from app.adapters.composite_arithmetic_capture.codec import digest

SOURCE_PATHS = (
    "core/repro.py",
    "engine/composites.py",
    "engine/numerical_boundary.py",
    "app/models/composites.py",
    "app/models/composite_arithmetic_capture.py",
    "app/models/composite_authority.py",
    "app/services/reproducibility_service.py",
    "app/services/calculation_engine_version.py",
    "app/adapters/composite_result_candidate_storage.py",
    "app/services/composite_calculation_service.py",
    "app/services/composite_materialization/model_fee_calculation.py",
    "app/services/composite_materialization/model_fee_schedule_rates.py",
    "app/services/composite_arithmetic_capture/collector.py",
    "app/services/composite_arithmetic_capture/response.py",
    "app/services/composite_arithmetic_capture/replay.py",
    "app/services/composite_arithmetic_capture/capture.py",
    "app/services/composite_arithmetic_capture/validation.py",
    "app/adapters/composite_arithmetic_capture/codec.py",
    "app/adapters/composite_arithmetic_capture/bundle.py",
)


def normalized_source(value):
    text = value.decode("utf-8")
    if text.startswith("\ufeff"):
        raise ValueError("Source BOM is not supported")
    text = text.replace("\r\n", "\n")
    if "\r" in text:
        raise ValueError("Isolated source carriage return")
    return text.encode("utf-8")


def source_manifest():
    entries = []
    for path in sorted(SOURCE_PATHS):
        package, relative = path.split("/", 1)
        raw = files(package).joinpath(relative).read_bytes()
        value = normalized_source(raw)
        entries.append({"path": path, "normalized_length": len(value), "sha256": hashlib.sha256(value).hexdigest()})
    return {"bundle_version": "CompositeProjectionSourceBundle.v1", "files": entries}


def installed_source_digest():
    expected = json.loads(files(__package__).joinpath("source-manifest.json").read_text(encoding="utf-8"))
    actual = source_manifest()
    if expected != actual:
        raise ValueError("Installed projection source closure differs from its trusted manifest")
    return digest(actual)


def runtime_identity():
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "decimal_version": decimal.__version__,
        "libmpdec_version": decimal.__libmpdec_version__,
        "decimal_contextvar": decimal.HAVE_CONTEXTVAR,
    }


if __name__ == "__main__":
    print(json.dumps(source_manifest(), sort_keys=True, indent=2))
