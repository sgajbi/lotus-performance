from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DECLARATION_DIR = ROOT / "contracts" / "domain-data-products"


def _resolve_platform_root() -> Path:
    configured_root = os.environ.get("LOTUS_PLATFORM_ROOT")
    candidates = []
    if configured_root:
        candidates.append(Path(configured_root))
    candidates.extend(
        [
            ROOT.parent / "lotus-platform",
            ROOT / ".lotus-platform",
            ROOT / "lotus-platform",
        ]
    )

    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if (resolved / "platform-contracts").exists():
            return resolved

    return candidates[0].expanduser().resolve()


PLATFORM_ROOT = _resolve_platform_root()
PLATFORM_DECLARATION_DIR = PLATFORM_ROOT / "platform-contracts" / "domain-data-products"
PLATFORM_VOCABULARY_DIR = PLATFORM_ROOT / "platform-contracts" / "domain-vocabulary"
PLATFORM_VALIDATOR_PATH = PLATFORM_DECLARATION_DIR / "validate_domain_data_product_contracts.py"

PRODUCT_PATTERN = "*-products.v1.json"
CONSUMER_PATTERN = "*-consumers.v1.json"
UPSTREAM_DEPENDENCY_INVENTORY_PATH = LOCAL_DECLARATION_DIR / "lotus-performance-upstream-dependency-inventory.v1.json"
REQUIRED_UPSTREAM_DEPENDENCY_METHODS = {
    "get_benchmark_assignment",
    "get_benchmark_composition_window",
    "get_benchmark_definition",
    "get_benchmark_market_series",
    "get_benchmark_return_series",
    "get_fx_rates",
    "get_index_catalog",
    "get_index_price_series",
    "get_performance_component_economics",
    "get_portfolio_analytics_reference",
    "get_portfolio_analytics_timeseries",
    "get_position_analytics_timeseries",
    "get_risk_free_series",
}
REQUIRED_DEPENDENCY_FIELDS = {
    "client_method",
    "upstream_route",
    "status",
    "route_contract_version",
    "freshness_trust_metadata",
    "failure_posture",
    "validation_lanes",
    "allowed_downstream_interpretation",
    "evidence_tests",
}
REQUIRED_EXCEPTION_FIELDS = {
    "exception_id",
    "upstream_onboarding_owner",
    "expires_on",
    "promotion_condition",
}


def _load_platform_validator():
    if not PLATFORM_VALIDATOR_PATH.exists():
        raise FileNotFoundError(
            f"Platform validator not found at {PLATFORM_VALIDATOR_PATH}. "
            "Ensure lotus-platform is available as a sibling checkout, under this repository, "
            "or through LOTUS_PLATFORM_ROOT."
        )

    spec = importlib.util.spec_from_file_location("lotus_platform_domain_product_validator", PLATFORM_VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load platform validator from {PLATFORM_VALIDATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_local_declaration_paths(source_directory: Path) -> list[Path]:
    return sorted(source_directory.glob(PRODUCT_PATTERN)) + sorted(source_directory.glob(CONSUMER_PATTERN))


def _collect_consumer_product_names(source_directory: Path) -> set[str]:
    product_names: set[str] = set()
    for path in sorted(source_directory.glob(CONSUMER_PATTERN)):
        payload = _load_json(path)
        for dependency in payload.get("dependencies", []):
            if not isinstance(dependency, dict):
                continue
            product_name = dependency.get("product_name")
            if isinstance(product_name, str) and product_name:
                product_names.add(product_name)
    return product_names


def _core_integration_service_methods() -> set[str]:
    source = (ROOT / "app" / "services" / "core_integration_service.py").read_text(encoding="utf-8")
    return set(re.findall(r"async def (get_[a-zA-Z0-9_]+)\(", source))


def _inventory_path_for(source_directory: Path) -> Path:
    return source_directory / UPSTREAM_DEPENDENCY_INVENTORY_PATH.name


def validate_upstream_dependency_inventory(source_directory: Path = LOCAL_DECLARATION_DIR) -> list[str]:
    source_directory = source_directory.resolve()
    inventory_path = _inventory_path_for(source_directory)
    if not inventory_path.exists():
        return [f"{inventory_path}: upstream dependency inventory is required"]

    issues: list[str] = []
    payload = _load_json(inventory_path)
    if payload.get("contract_id") != "upstream-dependency-inventory":
        issues.append(f"{inventory_path}: contract_id must be upstream-dependency-inventory")
    if payload.get("consumer_repository") != "lotus-performance":
        issues.append(f"{inventory_path}: consumer_repository must be lotus-performance")

    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        return [*issues, f"{inventory_path}: dependencies must be a non-empty list"]

    consumer_product_names = _collect_consumer_product_names(source_directory)
    core_methods = _core_integration_service_methods()
    missing_from_code = sorted(REQUIRED_UPSTREAM_DEPENDENCY_METHODS - core_methods)
    if missing_from_code:
        issues.append(
            f"{inventory_path}: required upstream method(s) absent from CoreIntegrationService: "
            + ", ".join(missing_from_code)
        )

    seen_methods: set[str] = set()
    today = date.today()
    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, dict):
            issues.append(f"{inventory_path}: dependencies[{index}] must be an object")
            continue

        missing_fields = sorted(REQUIRED_DEPENDENCY_FIELDS - set(dependency))
        client_method = dependency.get("client_method", f"dependencies[{index}]")
        if missing_fields:
            issues.append(f"{inventory_path}: {client_method} missing field(s): {', '.join(missing_fields)}")

        if isinstance(client_method, str):
            seen_methods.add(client_method)
            if client_method not in core_methods:
                issues.append(f"{inventory_path}: {client_method} is not an active CoreIntegrationService method")

        status = dependency.get("status")
        if status == "consumer_declaration":
            product_name = dependency.get("consumer_product_name")
            if not isinstance(product_name, str) or not product_name:
                issues.append(f"{inventory_path}: {client_method} consumer_declaration requires consumer_product_name")
            elif product_name not in consumer_product_names:
                issues.append(
                    f"{inventory_path}: {client_method} references undeclared consumer product {product_name}"
                )
        elif status == "time_bound_exception":
            missing_exception_fields = sorted(REQUIRED_EXCEPTION_FIELDS - set(dependency))
            if missing_exception_fields:
                issues.append(
                    f"{inventory_path}: {client_method} exception missing field(s): "
                    + ", ".join(missing_exception_fields)
                )
            expires_on = dependency.get("expires_on")
            if isinstance(expires_on, str):
                try:
                    expiry = date.fromisoformat(expires_on)
                except ValueError:
                    issues.append(f"{inventory_path}: {client_method} expires_on must be an ISO date")
                else:
                    if expiry < today:
                        issues.append(f"{inventory_path}: {client_method} exception expired on {expires_on}")
        else:
            issues.append(
                f"{inventory_path}: {client_method} status must be consumer_declaration or time_bound_exception"
            )

        for list_field in ("freshness_trust_metadata", "validation_lanes", "evidence_tests"):
            value = dependency.get(list_field)
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                issues.append(f"{inventory_path}: {client_method} {list_field} must be a non-empty string list")

        for evidence_path in dependency.get("evidence_tests", []):
            if isinstance(evidence_path, str) and not (ROOT / evidence_path).exists():
                issues.append(f"{inventory_path}: {client_method} evidence path does not exist: {evidence_path}")

    missing_methods = sorted(REQUIRED_UPSTREAM_DEPENDENCY_METHODS - seen_methods)
    extra_methods = sorted(seen_methods - REQUIRED_UPSTREAM_DEPENDENCY_METHODS)
    if missing_methods:
        issues.append(f"{inventory_path}: missing inventory coverage for: {', '.join(missing_methods)}")
    if extra_methods:
        issues.append(f"{inventory_path}: unexpected inventory method(s): {', '.join(extra_methods)}")

    return issues


def _collect_required_upstream_product_paths(source_directory: Path) -> list[Path]:
    required_repositories: set[str] = set()
    local_producer_repositories: set[str] = set()

    for path in sorted(source_directory.glob(PRODUCT_PATTERN)):
        payload = _load_json(path)
        producer_repository = payload.get("producer_repository")
        if isinstance(producer_repository, str) and producer_repository:
            local_producer_repositories.add(producer_repository)

    for path in sorted(source_directory.glob(CONSUMER_PATTERN)):
        payload = _load_json(path)
        for dependency in payload.get("dependencies", []):
            if not isinstance(dependency, dict):
                continue
            producer_repository = dependency.get("producer_repository")
            if isinstance(producer_repository, str) and producer_repository:
                required_repositories.add(producer_repository)

    upstream_paths: list[Path] = []
    for producer_repository in sorted(required_repositories - local_producer_repositories):
        candidate = PLATFORM_DECLARATION_DIR / f"{producer_repository}-products.v1.json"
        if not candidate.exists():
            raise FileNotFoundError(
                f"Required upstream producer declaration not found at {candidate}. "
                "Machine-readable consumer coverage cannot validate until the upstream producer declaration exists."
            )
        upstream_paths.append(candidate)

    return upstream_paths


def platform_validation_dependencies_available(source_directory: Path = LOCAL_DECLARATION_DIR) -> bool:
    required_paths = [
        PLATFORM_VALIDATOR_PATH,
        PLATFORM_VOCABULARY_DIR / "domain-data-product-semantics.v1.json",
        PLATFORM_VOCABULARY_DIR / "domain-data-product-trust-metadata.v1.json",
    ]

    try:
        required_paths.extend(_collect_required_upstream_product_paths(source_directory))
    except FileNotFoundError:
        return False

    return all(path.exists() for path in required_paths)


def validate_repo_native_contracts(source_directory: Path = LOCAL_DECLARATION_DIR) -> list[str]:
    source_directory = source_directory.resolve()
    if not source_directory.exists():
        return [f"{source_directory}: repo-native declaration directory does not exist"]

    validator = _load_platform_validator()
    local_paths = _collect_local_declaration_paths(source_directory)

    if not local_paths:
        return [f"{source_directory}: no repo-native declaration files were found"]

    upstream_paths = _collect_required_upstream_product_paths(source_directory)
    inventory_issues = validate_upstream_dependency_inventory(source_directory)
    if inventory_issues:
        return inventory_issues

    with tempfile.TemporaryDirectory(prefix="lotus-performance-domain-products-") as temp_dir_string:
        temp_root = Path(temp_dir_string)
        temp_declaration_dir = temp_root / "domain-data-products"
        temp_vocabulary_dir = temp_root / "domain-vocabulary"
        temp_declaration_dir.mkdir(parents=True, exist_ok=True)
        temp_vocabulary_dir.mkdir(parents=True, exist_ok=True)

        for declaration_path in local_paths:
            shutil.copy2(declaration_path, temp_declaration_dir / declaration_path.name)

        for upstream_path in upstream_paths:
            shutil.copy2(upstream_path, temp_declaration_dir / upstream_path.name)

        for vocabulary_file_name in (
            "domain-data-product-semantics.v1.json",
            "domain-data-product-trust-metadata.v1.json",
        ):
            shutil.copy2(
                PLATFORM_VOCABULARY_DIR / vocabulary_file_name,
                temp_vocabulary_dir / vocabulary_file_name,
            )

        return validator.validate_contract_directory(temp_declaration_dir)


def main() -> int:
    issues = validate_repo_native_contracts()
    if issues:
        for issue in issues:
            print(issue)
        return 1

    producer_count = len(list(LOCAL_DECLARATION_DIR.glob(PRODUCT_PATTERN)))
    consumer_count = len(list(LOCAL_DECLARATION_DIR.glob(CONSUMER_PATTERN)))
    print(
        "Validated "
        f"{producer_count} repo-native producer declaration(s) and "
        f"{consumer_count} repo-native consumer declaration(s), plus upstream dependency inventory "
        f"in {LOCAL_DECLARATION_DIR}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
