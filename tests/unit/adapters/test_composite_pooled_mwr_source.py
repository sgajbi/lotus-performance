"""Server-owned supplier installation cannot be omitted or replaced by a later caller."""

from unittest.mock import Mock

import pytest

from app.adapters import composite_pooled_mwr_source as source
from app.ports.composite_pooled_mwr import PooledSourceAdmissionError
from tests.unit.services.test_composite_pooled_mwr_admission import controlled_request


@pytest.fixture(autouse=True)
def isolated_deployment(monkeypatch):
    monkeypatch.setattr(source, "_deployment", source.PooledMonetarySourceDeployment())


@pytest.mark.parametrize("operation", ["read_population_scope", "read_pinned"])
def test_uninstalled_supplier_refuses_metadata_and_money_without_inventing_empty_source(operation):
    reader = source.get_pooled_monetary_source_reader()
    with pytest.raises(PooledSourceAdmissionError) as error:
        getattr(reader, operation)(controlled_request(), tenant_id="controlled-tenant")
    assert error.value.code == "SOURCE_AUTHORITY_UNAVAILABLE"


def test_empty_deployment_does_not_replace_unavailable_reader():
    with pytest.raises(ValueError, match="must supply"):
        source.install_pooled_monetary_source_deployment(source.PooledMonetarySourceDeployment())
    assert isinstance(source.get_pooled_monetary_source_reader(), source.UnavailablePooledMonetarySource)


def test_installed_server_reader_is_used_and_cannot_be_replaced():
    original, replacement = Mock(), Mock()
    source.install_pooled_monetary_source_deployment(source.PooledMonetarySourceDeployment(original))
    assert source.get_pooled_monetary_source_reader() is original
    with pytest.raises(RuntimeError, match="already installed"):
        source.install_pooled_monetary_source_deployment(source.PooledMonetarySourceDeployment(replacement))
    assert source.get_pooled_monetary_source_reader() is original
    original.assert_not_called()
    replacement.assert_not_called()
