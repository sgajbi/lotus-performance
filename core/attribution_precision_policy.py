"""Supported end-to-end numerical policy for attribution calculations."""

from typing import Literal

from core.errors import HTTP_422_UNPROCESSABLE, APIError

SUPPORTED_ATTRIBUTION_PRECISION: Literal["FLOAT64"] = "FLOAT64"
ATTRIBUTION_PRECISION_UNSUPPORTED = "ATTRIBUTION_PRECISION_UNSUPPORTED"


def require_attribution_precision(precision_mode: object) -> Literal["FLOAT64"]:
    """Refuse strict claims while group effects and linking use binary64."""
    if precision_mode != SUPPORTED_ATTRIBUTION_PRECISION:
        raise APIError(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="Attribution supports FLOAT64 only; DECIMAL_STRICT attribution is not supported.",
            error_code=ATTRIBUTION_PRECISION_UNSUPPORTED,
            retryable=False,
        )
    return SUPPORTED_ATTRIBUTION_PRECISION
