from fastapi.responses import JSONResponse

from app.core.application_responses import ApplicationHttpResponse

_RESPONSE_DETAIL_KEY = "detail"
_RESPONSE_REASON_KEY = "reason"
_AUTHORIZATION_POLICY_DENIED_DETAIL = "authorization_policy_denied"
_PAYLOAD_TOO_LARGE_DETAIL = "payload_too_large"
_HTTP_STATUS_FORBIDDEN = 403
_HTTP_STATUS_PAYLOAD_TOO_LARGE = 413


def _payload_too_large_response() -> JSONResponse:
    return JSONResponse(
        status_code=_HTTP_STATUS_PAYLOAD_TOO_LARGE,
        content={_RESPONSE_DETAIL_KEY: _PAYLOAD_TOO_LARGE_DETAIL},
    )


def _authorization_denied_response_envelope(reason: str | None) -> JSONResponse:
    return JSONResponse(
        status_code=_HTTP_STATUS_FORBIDDEN,
        content=_authorization_denied_response_content(reason),
    )


def _authorization_denied_application_response(reason: str | None) -> ApplicationHttpResponse:
    return ApplicationHttpResponse(
        status_code=_HTTP_STATUS_FORBIDDEN,
        content=_authorization_denied_response_content(reason),
    )


def _authorization_denied_response_content(reason: str | None) -> dict[str, str | None]:
    return {
        _RESPONSE_DETAIL_KEY: _AUTHORIZATION_POLICY_DENIED_DETAIL,
        _RESPONSE_REASON_KEY: reason,
    }
