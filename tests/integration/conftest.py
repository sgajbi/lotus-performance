import pytest

from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores


@pytest.fixture(scope="session", autouse=True)
def integration_schema_owner():
    """Apply the complete owner before even module-scoped HTTP clients start."""
    bootstrap_durable_metadata_stores()
