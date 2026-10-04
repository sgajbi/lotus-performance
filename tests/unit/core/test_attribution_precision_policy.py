import pytest

from core.attribution_precision_policy import require_attribution_precision
from core.errors import APIError
from engine.config import PrecisionMode


@pytest.mark.parametrize("mode", ["FLOAT64", PrecisionMode.FLOAT64])
def test_supported_attribution_policy_is_explicit(mode):
    assert require_attribution_precision(mode) == "FLOAT64"


@pytest.mark.parametrize("mode", ["DECIMAL_STRICT", PrecisionMode.DECIMAL_STRICT, None, True, "", "float64", []])
def test_unsupported_attribution_policy_has_stable_nonretryable_refusal(mode):
    with pytest.raises(APIError) as caught:
        require_attribution_precision(mode)
    assert caught.value.status_code == 422
    assert caught.value.error_code == "ATTRIBUTION_PRECISION_UNSUPPORTED"
    assert caught.value.retryable is False
