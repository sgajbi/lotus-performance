from __future__ import annotations

from collections.abc import Iterable


class DurableSchemaMigrationRequiredError(RuntimeError):
    """Startup cannot safely use the schema; only the governed owner may repair it."""

    code = "DURABLE_SCHEMA_MIGRATION_REQUIRED"

    def __init__(self, issues: Iterable[str]):
        self.issues = tuple(sorted(set(issues)))
        super().__init__(
            f"{self.code}: required durable schema is absent or incompatible. "
            "Run make migration-apply from the matching application checkout before starting workloads. "
            + "; ".join(self.issues)
        )
