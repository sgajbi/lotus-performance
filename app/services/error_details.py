from __future__ import annotations


def coded_error_detail(*, code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
