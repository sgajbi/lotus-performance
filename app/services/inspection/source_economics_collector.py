from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.inspection.source_economics import ObservationSourceEconomics


@dataclass(frozen=True)
class SourceEconomicsSamples:
    fee_flow_dates: list[str]
    external_flow_dates: list[str]
    fee_normalization_samples: list[dict[str, object]]
    duplicate_fee_signal_samples: list[dict[str, object]]
    fee_source_mismatch_samples: list[dict[str, object]]
    positive_fee_signal_samples: list[dict[str, object]]
    fee_timing_bucket_samples: list[dict[str, object]]
    external_normalization_samples: list[dict[str, object]]
    duplicate_external_signal_samples: list[dict[str, object]]
    external_source_mismatch_samples: list[dict[str, object]]
    external_timing_contradiction_samples: list[dict[str, object]]
    conflicting_explicit_amount_samples: list[dict[str, object]]
    invalid_explicit_amount_samples: list[dict[str, object]]
    invalid_amount_samples: list[dict[str, object]]
    invalid_timing_samples: list[dict[str, object]]
    missing_cashflow_type_samples: list[dict[str, object]]
    noncanonical_cashflow_type_samples: list[dict[str, object]]
    unsupported_cashflow_type_samples: list[dict[str, object]]
    governed_alias_cashflow_type_samples: list[dict[str, object]]


@dataclass
class _SourceEconomicsSampleCollector:
    fee_flow_dates: list[str] = field(default_factory=list)
    external_flow_dates: list[str] = field(default_factory=list)
    fee_normalization_samples: list[dict[str, object]] = field(default_factory=list)
    duplicate_fee_signal_samples: list[dict[str, object]] = field(default_factory=list)
    fee_source_mismatch_samples: list[dict[str, object]] = field(default_factory=list)
    positive_fee_signal_samples: list[dict[str, object]] = field(default_factory=list)
    fee_timing_bucket_samples: list[dict[str, object]] = field(default_factory=list)
    external_normalization_samples: list[dict[str, object]] = field(default_factory=list)
    duplicate_external_signal_samples: list[dict[str, object]] = field(default_factory=list)
    external_source_mismatch_samples: list[dict[str, object]] = field(default_factory=list)
    external_timing_contradiction_samples: list[dict[str, object]] = field(default_factory=list)
    conflicting_explicit_amount_samples: list[dict[str, object]] = field(default_factory=list)
    invalid_explicit_amount_samples: list[dict[str, object]] = field(default_factory=list)
    invalid_amount_samples: list[dict[str, object]] = field(default_factory=list)
    invalid_timing_samples: list[dict[str, object]] = field(default_factory=list)
    missing_cashflow_type_samples: list[dict[str, object]] = field(default_factory=list)
    noncanonical_cashflow_type_samples: list[dict[str, object]] = field(default_factory=list)
    unsupported_cashflow_type_samples: list[dict[str, object]] = field(default_factory=list)
    governed_alias_cashflow_type_samples: list[dict[str, object]] = field(default_factory=list)

    def observe(self, source_point: ObservationSourceEconomics) -> None:
        self._record_taxonomy_samples(source_point)
        self._record_fee_samples(source_point)
        self._record_external_samples(source_point)

    def freeze(self) -> SourceEconomicsSamples:
        return SourceEconomicsSamples(
            fee_flow_dates=self.fee_flow_dates,
            external_flow_dates=self.external_flow_dates,
            fee_normalization_samples=self.fee_normalization_samples,
            duplicate_fee_signal_samples=self.duplicate_fee_signal_samples,
            fee_source_mismatch_samples=self.fee_source_mismatch_samples,
            positive_fee_signal_samples=self.positive_fee_signal_samples,
            fee_timing_bucket_samples=self.fee_timing_bucket_samples,
            external_normalization_samples=self.external_normalization_samples,
            duplicate_external_signal_samples=self.duplicate_external_signal_samples,
            external_source_mismatch_samples=self.external_source_mismatch_samples,
            external_timing_contradiction_samples=self.external_timing_contradiction_samples,
            conflicting_explicit_amount_samples=self.conflicting_explicit_amount_samples,
            invalid_explicit_amount_samples=self.invalid_explicit_amount_samples,
            invalid_amount_samples=self.invalid_amount_samples,
            invalid_timing_samples=self.invalid_timing_samples,
            missing_cashflow_type_samples=self.missing_cashflow_type_samples,
            noncanonical_cashflow_type_samples=self.noncanonical_cashflow_type_samples,
            unsupported_cashflow_type_samples=self.unsupported_cashflow_type_samples,
            governed_alias_cashflow_type_samples=self.governed_alias_cashflow_type_samples,
        )

    def _record_taxonomy_samples(self, source_point: ObservationSourceEconomics) -> None:
        if source_point.detailed_fee_bod != 0 or source_point.detailed_fee_eod != 0:
            self.fee_flow_dates.append(source_point.valuation_date)
        if source_point.detailed_external_bod != 0 or source_point.detailed_external_eod != 0:
            self.external_flow_dates.append(source_point.valuation_date)
        if source_point.conflicting_explicit_amount_fields:
            self.conflicting_explicit_amount_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "rows": list(source_point.conflicting_explicit_amount_fields),
                }
            )
        if source_point.invalid_explicit_amount_fields:
            self.invalid_explicit_amount_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "rows": list(source_point.invalid_explicit_amount_fields),
                }
            )
        if source_point.invalid_amount_rows:
            self.invalid_amount_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "rows": list(source_point.invalid_amount_rows),
                }
            )
        if source_point.invalid_timing_rows:
            self.invalid_timing_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "rows": list(source_point.invalid_timing_rows),
                }
            )
        if source_point.missing_cashflow_type_rows:
            self.missing_cashflow_type_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "rows": list(source_point.missing_cashflow_type_rows),
                }
            )
        if source_point.noncanonical_cashflow_types:
            self.noncanonical_cashflow_type_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "cash_flow_types": list(source_point.noncanonical_cashflow_types),
                }
            )
        if source_point.unsupported_cashflow_type_rows:
            self.unsupported_cashflow_type_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "cash_flow_types": _cashflow_types_from_rows(source_point.unsupported_cashflow_type_rows),
                    "rows": list(source_point.unsupported_cashflow_type_rows),
                }
            )
        if source_point.governed_alias_cashflow_type_rows:
            self.governed_alias_cashflow_type_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "cash_flow_types": _cashflow_types_from_rows(source_point.governed_alias_cashflow_type_rows),
                    "rows": list(source_point.governed_alias_cashflow_type_rows),
                }
            )

    def _record_fee_samples(self, source_point: ObservationSourceEconomics) -> None:
        expected_fee_total, fee_source_kind = _expected_fee_total(source_point)
        if expected_fee_total is not None and not _amounts_match(source_point.normalized_mgmt_fees, expected_fee_total):
            self.fee_normalization_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "raw_fee_bod": float(source_point.detailed_fee_bod),
                    "raw_fee_eod": float(source_point.detailed_fee_eod),
                    "expected_fee_amount": float(expected_fee_total),
                    "fee_source_kind": fee_source_kind,
                    "normalized_bod_cf": float(source_point.normalized_bod_cf),
                    "normalized_eod_cf": float(source_point.normalized_eod_cf),
                    "normalized_mgmt_fees": float(source_point.normalized_mgmt_fees),
                }
            )

        fee_total = source_point.detailed_fee_bod + source_point.detailed_fee_eod
        if source_point.explicit_fee_total is not None and _amounts_match(source_point.explicit_fee_total, fee_total):
            self.duplicate_fee_signal_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "explicit_fee_amount": float(source_point.explicit_fee_total),
                    "fee_cashflow_amount": float(fee_total),
                }
            )
        elif source_point.explicit_fee_total is not None and fee_total != 0:
            self.fee_source_mismatch_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "explicit_fee_amount": float(source_point.explicit_fee_total),
                    "fee_cashflow_amount": float(fee_total),
                }
            )
        if fee_total > 0 or (source_point.explicit_fee_total is not None and source_point.explicit_fee_total > 0):
            self.positive_fee_signal_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "detailed_fee_amount": float(fee_total),
                    "explicit_fee_amount": (
                        float(source_point.explicit_fee_total) if source_point.explicit_fee_total is not None else None
                    ),
                }
            )
        if source_point.fee_bod_timing_rows:
            self.fee_timing_bucket_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "rows": list(source_point.fee_bod_timing_rows),
                }
            )

    def _record_external_samples(self, source_point: ObservationSourceEconomics) -> None:
        expected_external_bod, bod_source_kind = _expected_external_total(source_point, timing="bod")
        expected_external_eod, eod_source_kind = _expected_external_total(source_point, timing="eod")
        if (
            expected_external_bod is not None
            and not _amounts_match(source_point.normalized_bod_cf, expected_external_bod)
        ) or (
            expected_external_eod is not None
            and not _amounts_match(source_point.normalized_eod_cf, expected_external_eod)
        ):
            self.external_normalization_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "raw_external_bod": float(source_point.detailed_external_bod),
                    "raw_external_eod": float(source_point.detailed_external_eod),
                    "expected_external_bod": (
                        float(expected_external_bod) if expected_external_bod is not None else None
                    ),
                    "expected_external_eod": (
                        float(expected_external_eod) if expected_external_eod is not None else None
                    ),
                    "bod_source_kind": bod_source_kind,
                    "eod_source_kind": eod_source_kind,
                    "normalized_bod_cf": float(source_point.normalized_bod_cf),
                    "normalized_eod_cf": float(source_point.normalized_eod_cf),
                }
            )

        if source_point.explicit_bod_total is not None and source_point.detailed_external_bod != 0:
            _record_external_source_signal(
                sample_target=self.duplicate_external_signal_samples,
                mismatch_target=self.external_source_mismatch_samples,
                valuation_date=source_point.valuation_date,
                timing="bod",
                explicit_total=source_point.explicit_bod_total,
                detailed_total=source_point.detailed_external_bod,
            )
        if source_point.explicit_eod_total is not None and source_point.detailed_external_eod != 0:
            _record_external_source_signal(
                sample_target=self.duplicate_external_signal_samples,
                mismatch_target=self.external_source_mismatch_samples,
                valuation_date=source_point.valuation_date,
                timing="eod",
                explicit_total=source_point.explicit_eod_total,
                detailed_total=source_point.detailed_external_eod,
            )
        _record_external_timing_contradictions(
            source_point=source_point,
            sample_target=self.external_timing_contradiction_samples,
        )


def collect_source_economics_samples(source_points: list[ObservationSourceEconomics]) -> SourceEconomicsSamples:
    collector = _SourceEconomicsSampleCollector()
    for source_point in source_points:
        collector.observe(source_point)
    return collector.freeze()


def _cashflow_types_from_rows(rows: tuple[dict[str, object], ...]) -> list[str]:
    return sorted(
        {
            cash_flow_type
            for row in rows
            for cash_flow_type in [row.get("cash_flow_type")]
            if isinstance(cash_flow_type, str)
        }
    )


def _expected_fee_total(source_point: ObservationSourceEconomics) -> tuple[Decimal | None, str | None]:
    detailed_fee_total = source_point.detailed_fee_bod + source_point.detailed_fee_eod
    if detailed_fee_total != 0:
        return detailed_fee_total, "detailed_fee_cash_flows"
    if source_point.explicit_fee_total is not None:
        return source_point.explicit_fee_total, "explicit_fee_total"
    return None, None


def _expected_external_total(
    source_point: ObservationSourceEconomics,
    *,
    timing: str,
) -> tuple[Decimal | None, str | None]:
    detailed_total = source_point.detailed_external_bod if timing == "bod" else source_point.detailed_external_eod
    explicit_total = source_point.explicit_bod_total if timing == "bod" else source_point.explicit_eod_total
    if detailed_total != 0:
        return detailed_total, "detailed_external_cash_flows"
    if explicit_total is not None:
        return explicit_total, f"explicit_{timing}_cashflow_total"
    return None, None


def _record_external_source_signal(
    *,
    sample_target: list[dict[str, object]],
    mismatch_target: list[dict[str, object]],
    valuation_date: str,
    timing: str,
    explicit_total: Decimal,
    detailed_total: Decimal,
) -> None:
    sample = {
        "valuation_date": valuation_date,
        "timing": timing,
        "explicit_cashflow_amount": float(explicit_total),
        "detailed_cashflow_amount": float(detailed_total),
    }
    if _amounts_match(explicit_total, detailed_total):
        sample_target.append(sample)
    else:
        mismatch_target.append(sample)


def _record_external_timing_contradictions(
    *,
    source_point: ObservationSourceEconomics,
    sample_target: list[dict[str, object]],
) -> None:
    if (
        source_point.explicit_bod_total is not None
        and source_point.detailed_external_bod == 0
        and source_point.detailed_external_eod != 0
    ):
        sample_target.append(
            {
                "valuation_date": source_point.valuation_date,
                "explicit_timing": "bod",
                "opposite_detailed_timing": "eod",
                "explicit_cashflow_amount": float(source_point.explicit_bod_total),
                "opposite_detailed_cashflow_amount": float(source_point.detailed_external_eod),
            }
        )
    if (
        source_point.explicit_eod_total is not None
        and source_point.detailed_external_eod == 0
        and source_point.detailed_external_bod != 0
    ):
        sample_target.append(
            {
                "valuation_date": source_point.valuation_date,
                "explicit_timing": "eod",
                "opposite_detailed_timing": "bod",
                "explicit_cashflow_amount": float(source_point.explicit_eod_total),
                "opposite_detailed_cashflow_amount": float(source_point.detailed_external_bod),
            }
        )


def _amounts_match(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= Decimal("0.01")
