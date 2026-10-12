"""Observe source operations without changing arithmetic, scopes or sticky flags."""

from decimal import getcontext
from json import JSONEncoder

from core.errors import APIUnprocessableEntityError


def context_payload(context):
    return {
        "prec": context.prec,
        "rounding": context.rounding,
        "Emin": context.Emin,
        "Emax": context.Emax,
        "capitals": context.capitals,
        "clamp": context.clamp,
        "traps": {signal.__name__: value for signal, value in context.traps.items()},
        "entry_flags": flag_payload(context),
    }


def flag_payload(context):
    return {signal.__name__: value for signal, value in context.flags.items()}


def refuse(code, message):
    raise APIUnprocessableEntityError(message, error_code=code)


class ArithmeticCollector:
    def __init__(self):
        self.facts = []
        self.windows = []
        self.context = None
        self.exit_flags = None
        self.route = None
        self.checkpoints = []

    def select(self, facts, windows):
        if len(facts) > 120000 or len(windows) > 120:
            refuse("RESOURCE_LIMIT", "Precision capture exceeds its bounded input envelope.")
        encoder = JSONEncoder(ensure_ascii=True, allow_nan=False)
        size = 0
        for fact in facts:
            _bounded_original_numbers(fact)
        for item in (*facts, *windows):
            for token in encoder.iterencode(item.model_dump(mode="json")):
                size += len(token.encode("utf-8"))
                if size > 8 * 1024 * 1024:
                    refuse("RESOURCE_LIMIT", "Original precision inputs exceed eight MiB.")
        self.facts, self.windows = list(facts), list(windows)

    def start(self, *, scheduled):
        self.context = context_payload(getcontext().copy())
        self.route = "SCHEDULED_COMPONENT_SCOPED" if scheduled else "AMBIENT"

    def period(
        self,
        *,
        period_start,
        period_end,
        beginning_assets,
        ending_assets,
        weighted_return,
        next_cumulative_growth,
        cumulative_return,
    ):
        self.checkpoints.append(
            {
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "beginning_assets": str(beginning_assets),
                "ending_assets": str(ending_assets),
                "weighted_return": str(weighted_return),
                "next_cumulative_growth": str(next_cumulative_growth),
                "cumulative_return_before_quantize": str(cumulative_return),
            }
        )

    def finish(self):
        self.exit_flags = flag_payload(getcontext().copy())


def _bounded_original_numbers(fact):
    for value in (fact.return_value, fact.beginning_market_value, fact.ending_market_value):
        if value is not None and value.is_finite():
            if len(str(value)) > 160 or abs(value.as_tuple().exponent) > 160:
                refuse("RESOURCE_LIMIT", "Original precision fact exceeds the numeric envelope.")
