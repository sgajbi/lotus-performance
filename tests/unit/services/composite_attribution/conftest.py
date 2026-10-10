"""Unit-only controlled fixture registration."""

import pytest

from tests.composite_attribution_helpers import controlled_financial_case


@pytest.fixture
def financial_case():
    return controlled_financial_case()
