from __future__ import annotations

_SOURCE_UNAVAILABLE_CODE = "SOURCE_UNAVAILABLE"
_RESOURCE_NOT_FOUND_CODE = "RESOURCE_NOT_FOUND"
_INSUFFICIENT_DATA_CODE = "INSUFFICIENT_DATA"
_INVALID_REQUEST_CODE = "INVALID_REQUEST"
_UPSTREAM_CONTRACT_VIOLATION_CODE = "CONTRACT_VIOLATION_UPSTREAM"


def coded_error_detail(*, code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def source_unavailable_detail(message: str) -> dict[str, str]:
    return coded_error_detail(code=_SOURCE_UNAVAILABLE_CODE, message=message)


def resource_not_found_detail(message: str) -> dict[str, str]:
    return coded_error_detail(code=_RESOURCE_NOT_FOUND_CODE, message=message)


def insufficient_data_detail(message: str) -> dict[str, str]:
    return coded_error_detail(code=_INSUFFICIENT_DATA_CODE, message=message)


def invalid_request_detail(message: str) -> dict[str, str]:
    return coded_error_detail(code=_INVALID_REQUEST_CODE, message=message)


def upstream_contract_violation_detail(message: str) -> dict[str, str]:
    return coded_error_detail(code=_UPSTREAM_CONTRACT_VIOLATION_CODE, message=message)
