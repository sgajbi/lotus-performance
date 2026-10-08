"""Transform a verified gross factor; never invent a cash fee or asset debit."""

from decimal import Decimal

from engine.numerical_boundary import monetary_arithmetic_context


def periodic_model_net_return(gross_return: Decimal, period_fee_fraction: Decimal) -> Decimal:
    if not gross_return.is_finite() or gross_return < Decimal(-1):
        raise ValueError("Gross member return is outside the finite wealth-factor domain")
    if not period_fee_fraction.is_finite() or not Decimal(0) <= period_fee_fraction < Decimal(1):
        raise ValueError("Periodic model fee is outside the approved zero-inclusive, one-exclusive domain")
    with monetary_arithmetic_context([gross_return, period_fee_fraction, Decimal(1)], products=True):
        return (Decimal(1) + gross_return) * (Decimal(1) - period_fee_fraction) - Decimal(1)
