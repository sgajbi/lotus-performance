"""Capability-owned exact example/OpenAPI/behavior-ledger certification."""

import ast
from pathlib import Path

POST_PATH = "/performance/composites/analytics"
GET_PATH = POST_PATH + "/results/{calculation_id}"
EXPECTED_MODES = frozenset(
    {
        "request",
        "correction_request",
        "accepted",
        "pending",
        "original_ready",
        "original_replay",
        "corrected_ready",
        "source_unavailable",
        "purpose_unavailable",
        "incomplete_groups",
        "strict_precision",
    }
)


def certify_attribution_examples(spec, examples, generated, ledger, *, root: Path):
    """Fail closed for stale values, missing modes or missing executable proof."""
    if examples != generated:
        raise ValueError("Packaged BF examples differ from production-backed factory")
    modes = [entry["mode"] for entry in ledger["modes"]]
    if len(modes) != len(EXPECTED_MODES) + 1 or set(modes) != EXPECTED_MODES or modes.count("source_unavailable") != 2:
        raise ValueError("BF named mode inventory differs")
    if ledger["evidence_class"] != "CONTROLLED_SYNTHETIC_ONLY" or ledger["institutional_acceptance"] != "NOT_ATTESTED":
        raise ValueError("Synthetic examples cannot certify institutional acceptance")
    expected_names = {}
    for entry in ledger["modes"]:
        method, status = entry["method"], entry["status"]
        operation = spec["paths"][POST_PATH if method == "post" else GET_PATH][method]
        content = operation["requestBody"] if status == "request" else operation["responses"][status]
        published = content["content"]["application/json"]["examples"]
        mode = entry["mode"]
        expected = examples[mode] if mode in examples else examples["errors"][mode]
        if entry["example"] not in published or published[entry["example"]]["value"] != expected:
            raise ValueError("Published BF example differs: " + mode)
        expected_names.setdefault((method, status), set()).add(entry["example"])
        reference = entry.get("behavior", "")
        path, separator, function = reference.partition("::")
        if not separator or not path.startswith("tests/") or not function.startswith("test_"):
            raise ValueError("Missing BF behavior reference: " + mode)
        source = root / path
        functions = {
            node.name
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
            if isinstance(node, ast.FunctionDef)
        }
        if function not in functions:
            raise ValueError("Missing executable BF behavior: " + mode)
    for (method, status), names in expected_names.items():
        operation = spec["paths"][POST_PATH if method == "post" else GET_PATH][method]
        content = operation["requestBody"] if status == "request" else operation["responses"][status]
        actual = {name for name in content["content"]["application/json"]["examples"] if name.startswith("bf_")}
        if actual != names:
            raise ValueError("Unregistered BF named example")
