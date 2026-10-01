from __future__ import annotations

import pytest

from app.services.stateful_position_source_completeness import position_source_rows_are_complete


def test_group_return_evidence_position_source_completeness_accepts_retained_core_counters() -> None:
    assert position_source_rows_are_complete(
        payload={
            "retrieval_metadata": {
                "source_row_count": 4,
                "retained_row_count": 4,
                "discarded_source_row_count": 0,
            }
        },
        retained_row_count=4,
    )


@pytest.mark.parametrize(
    ("payload", "retained_row_count"),
    [
        ({}, 1),
        (
            {
                "retrieval_metadata": {
                    "source_row_count": True,
                    "retained_row_count": 1,
                    "discarded_source_row_count": 0,
                }
            },
            1,
        ),
        ({"retrieval_metadata": {"source_row_count": 1, "retained_row_count": 0, "discarded_source_row_count": 0}}, 1),
        ({"retrieval_metadata": {"source_row_count": 1, "retained_row_count": 1, "discarded_source_row_count": 1}}, 1),
        ({"retrieval_metadata": {"source_row_count": -1, "retained_row_count": 1, "discarded_source_row_count": 0}}, 1),
    ],
)
def test_group_return_evidence_position_source_completeness_refuses_missing_or_lossy_counters(
    payload: dict[str, object],
    retained_row_count: int,
) -> None:
    assert not position_source_rows_are_complete(payload=payload, retained_row_count=retained_row_count)
