from __future__ import annotations


def raise_inspection_source_unavailable(*, source_label: str, inspection_label: str, status_code: int) -> None:
    raise RuntimeError(f"{source_label} source unavailable for {inspection_label} inspection ({status_code}).")
