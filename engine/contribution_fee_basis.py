from __future__ import annotations

from decimal import Decimal

import pandas as pd

from core.envelope import DataPolicy
from engine.config import PrecisionMode
from engine.schema import PortfolioColumns

_DEFAULT_OUTLIER_SCOPE = {"SECURITY_RETURNS"}
_OUTLIER_SCOPE_BY_ENTITY_TYPE = {
    "PORTFOLIO": "PORTFOLIO_RETURNS",
    "POSITION": "SECURITY_RETURNS",
}


def contribution_data_policy_for_entity(
    data_policy: DataPolicy | None,
    *,
    entity_type: str,
    entity_id: str,
) -> DataPolicy | None:
    """Restrict contribution policies to the portfolio or position engine run they name."""
    if data_policy is None:
        return None

    payload = data_policy.model_dump(exclude_unset=True)
    _scope_overrides(payload, entity_type=entity_type, entity_id=entity_id)
    _scope_outliers(payload, entity_type=entity_type)
    payload["ignore_days"] = _matching_ignore_days(
        payload.get("ignore_days"),
        entity_type=entity_type,
        entity_id=entity_id,
    )
    return DataPolicy.model_validate(payload)


def _scope_outliers(payload: dict, *, entity_type: str) -> None:
    outliers = payload.get("outliers")
    if not outliers:
        return
    scopes = set(outliers.get("scope", _DEFAULT_OUTLIER_SCOPE))
    if _OUTLIER_SCOPE_BY_ENTITY_TYPE[entity_type] not in scopes:
        payload["outliers"] = None


def _scope_overrides(payload: dict, *, entity_type: str, entity_id: str) -> None:
    overrides = payload.get("overrides")
    if not overrides:
        return
    for override_type in ("market_values", "cash_flows"):
        overrides[override_type] = _matching_overrides(
            overrides.get(override_type),
            entity_type=entity_type,
            entity_id=entity_id,
        )


def _matching_overrides(
    overrides: list[dict] | None,
    *,
    entity_type: str,
    entity_id: str,
) -> list[dict]:
    return [
        item for item in overrides or [] if _override_targets_entity(item, entity_type=entity_type, entity_id=entity_id)
    ]


def _matching_ignore_days(
    ignore_days: list[dict] | None,
    *,
    entity_type: str,
    entity_id: str,
) -> list[dict]:
    return [
        item
        for item in ignore_days or []
        if item.get("entity_type") == entity_type and item.get("entity_id") == entity_id
    ]


def _override_targets_entity(item: dict, *, entity_type: str, entity_id: str) -> bool:
    if entity_type == "POSITION":
        return item.get("position_id") == entity_id
    return "position_id" not in item and item.get("portfolio_id", entity_id) == entity_id


def normalize_after_fee_ending_values(
    valuation_frame: pd.DataFrame,
    precision_mode: PrecisionMode,
) -> None:
    """Translate after-fee contribution values to the engine's fee-exclusive basis.

    The contribution API and Core source adapter expose ending market values after
    booked fees. The shared return engine accepts an ending value before the
    separately supplied ``mgmt_fees`` amount, then applies that amount for NET and
    omits it for GROSS. Reconstructing that engine input once prevents fee drag or
    refunds from being counted twice.
    """
    ending_values = valuation_frame[PortfolioColumns.END_MV.value]
    management_fees = valuation_frame[PortfolioColumns.MGMT_FEES.value]
    if precision_mode == PrecisionMode.DECIMAL_STRICT:
        valuation_frame[PortfolioColumns.END_MV.value] = [
            Decimal(str(ending_value)) - Decimal(str(management_fee))
            for ending_value, management_fee in zip(ending_values, management_fees)
        ]
        return
    valuation_frame[PortfolioColumns.END_MV.value] = ending_values - management_fees
