from __future__ import annotations

from datetime import date as dt_date
from typing import Dict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.attribution_responses import (
    AttributionBenchmarkContext,
    SinglePeriodAttributionResult,
)
from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkReturnSource
from app.models.contribution_responses import (
    ContributionLevel,
    ContributionSummary,
    PositionContribution,
)
from app.models.mwr_analytics_requests import MWRInputMode
from app.models.twr_requests import TWRInputMode
from common.enums import AttributionModel, Frequency, LinkingMethod
from core.envelope import Audit, Diagnostics, Meta

WORKSPACE_SUMMARY_RESPONSE_EXAMPLES = [
    {
        "calculation_id": "0d000002-1111-4222-8333-abcdefabcdef",
        "portfolio_id": "WORKSPACE_SUMMARY_STATEFUL_01",
        "input_mode": "stateful",
        "results_by_period": {
            "YTD": {
                "portfolio_twr": {
                    "net": {
                        "summary": {
                            "economics": {
                                "begin_market_value": 1000000.0,
                                "end_market_value": 1054100.0,
                                "beginning_cash_flow": 25000.0,
                                "ending_cash_flow": -5000.0,
                                "fees": -350.0,
                                "net_cash_flow": 20000.0,
                                "flow_adjusted_end_market_value": 1034100.0,
                            },
                            "period_return": {"base": 3.41, "local": 3.18, "fx": 0.23},
                            "cumulative_return": {"base": 3.41, "local": 3.18, "fx": 0.23},
                            "annualized_return": {"base": 3.41, "local": 3.18, "fx": 0.23},
                        },
                        "breakdowns": {
                            "monthly": [
                                {
                                    "period": "2026-03",
                                    "period_start": "2026-03-01",
                                    "period_end": "2026-03-31",
                                    "economics": {
                                        "begin_market_value": 1039500.0,
                                        "end_market_value": 1054100.0,
                                        "beginning_cash_flow": 0.0,
                                        "ending_cash_flow": -5000.0,
                                        "fees": -350.0,
                                        "net_cash_flow": -5000.0,
                                        "flow_adjusted_end_market_value": 1059100.0,
                                    },
                                    "period_return": {"base": 1.4, "local": 1.25, "fx": 0.15},
                                    "cumulative_return": {"base": 1.4, "local": 1.25, "fx": 0.15},
                                    "annualized_return": {"base": 1.4, "local": 1.25, "fx": 0.15},
                                }
                            ]
                        },
                    },
                    "gross": {
                        "summary": {
                            "economics": {
                                "begin_market_value": 1000000.0,
                                "end_market_value": 1054100.0,
                                "beginning_cash_flow": 25000.0,
                                "ending_cash_flow": -5000.0,
                                "fees": -350.0,
                                "net_cash_flow": 20000.0,
                                "flow_adjusted_end_market_value": 1034100.0,
                            },
                            "period_return": {"base": 3.44, "local": 3.21, "fx": 0.23},
                            "cumulative_return": {"base": 3.44, "local": 3.21, "fx": 0.23},
                            "annualized_return": {"base": 3.44, "local": 3.21, "fx": 0.23},
                        },
                        "breakdowns": {
                            "monthly": [
                                {
                                    "period": "2026-03",
                                    "period_start": "2026-03-01",
                                    "period_end": "2026-03-31",
                                    "economics": {
                                        "begin_market_value": 1039500.0,
                                        "end_market_value": 1054100.0,
                                        "beginning_cash_flow": 0.0,
                                        "ending_cash_flow": -5000.0,
                                        "fees": -350.0,
                                        "net_cash_flow": -5000.0,
                                        "flow_adjusted_end_market_value": 1059100.0,
                                    },
                                    "period_return": {"base": 1.43, "local": 1.28, "fx": 0.15},
                                    "cumulative_return": {"base": 1.43, "local": 1.28, "fx": 0.15},
                                    "annualized_return": {"base": 1.43, "local": 1.28, "fx": 0.15},
                                }
                            ]
                        },
                    },
                },
                "benchmark": {
                    "summary": {
                        "period_return": {"base": 2.98},
                        "cumulative_return": {"base": 2.98},
                        "annualized_return": {"base": 2.98},
                    },
                    "breakdowns": {
                        "monthly": [
                            {
                                "period": "2026-03",
                                "period_start": "2026-03-01",
                                "period_end": "2026-03-31",
                                "period_return": {"base": 1.22},
                                "cumulative_return": {"base": 1.22},
                                "annualized_return": {"base": 1.22},
                            }
                        ]
                    },
                    "benchmark_id": "BMK_GLOBAL_60_40",
                    "benchmark_currency": "USD",
                    "input_mode": "stateful",
                    "return_source": "calculated",
                },
                "active": {
                    "net": {
                        "period_return": {"base": 0.43},
                        "cumulative_return": {"base": 0.43},
                        "annualized_return": {"base": 0.43},
                    },
                    "gross": {
                        "period_return": {"base": 0.46},
                        "cumulative_return": {"base": 0.46},
                        "annualized_return": {"base": 0.46},
                    },
                },
                "money_weighted_return": {
                    "input_mode": "stateful",
                    "method": "XIRR",
                    "period_return": 3.27,
                    "cumulative_return": 3.27,
                    "annualized_return": 3.27,
                    "economics": {
                        "begin_market_value": 1000000.0,
                        "end_market_value": 1054100.0,
                        "beginning_cash_flow": 25000.0,
                        "ending_cash_flow": -5000.0,
                        "fees": -350.0,
                        "net_cash_flow": 20000.0,
                        "flow_adjusted_end_market_value": 1034100.0,
                    },
                    "start_date": "2026-01-02",
                    "end_date": "2026-03-31",
                    "notes": ["Stateful workspace MWR summary resolved from the longest requested window."],
                },
                "contribution": {
                    "metric_basis": "NET",
                    "segmentation": ["sector", "country"],
                    "summary": {"total_contribution": 3.41, "portfolio_return": 3.41},
                    "levels": [
                        {
                            "level": 1,
                            "name": "sector",
                            "rows": [
                                {
                                    "key": {"sector": "technology"},
                                    "contribution": 2.11,
                                    "weight_avg": 58.0,
                                    "return": 3.64,
                                    "child_count": 2,
                                }
                            ],
                        }
                    ],
                    "position_contributions": [
                        {
                            "position_id": "AAPL_US",
                            "contribution": 1.42,
                            "average_weight": 24.0,
                            "total_return": 5.92,
                        }
                    ],
                },
                "attribution": {
                    "metric_basis": "NET",
                    "segmentation": ["sector", "country"],
                    "model": "brinson_fachler",
                    "linking": "carino",
                    "benchmark_context": {
                        "benchmark_id": "BMK_GLOBAL_60_40",
                        "return_source": "calculated",
                    },
                    "result": {
                        "levels": [
                            {
                                "dimension": "sector",
                                "rows": [
                                    {
                                        "key": {"sector": "technology"},
                                        "portfolio_weight_avg": 58.0,
                                        "benchmark_weight_avg": 52.0,
                                        "portfolio_return": 3.64,
                                        "benchmark_return": 3.2,
                                        "allocation": 0.12,
                                        "selection": 0.24,
                                        "interaction": 0.02,
                                        "total_effect": 0.38,
                                    }
                                ],
                                "totals": {
                                    "allocation": 0.12,
                                    "selection": 0.24,
                                    "interaction": 0.02,
                                    "total_effect": 0.38,
                                },
                            }
                        ],
                        "reconciliation": {
                            "total_active_return": 0.43,
                            "sum_of_effects": 0.43,
                            "residual": 0.0,
                        },
                    },
                },
            }
        },
        "meta": {
            "engine_version": "test-version",
            "calculation_hash": "workspace-hash",
            "input_fingerprint": "workspace-fingerprint",
        },
        "diagnostics": {
            "nip_days": 0,
            "reset_days": 0,
            "effective_period_start": "2026-01-02",
            "notes": [
                "Workspace benchmark summary enabled for all requested periods.",
                "Workspace contribution summary enabled with shared segmentation: sector, country.",
                "Workspace attribution summary enabled with shared segmentation: sector, country using benchmark BMK_GLOBAL_60_40.",
            ],
        },
        "audit": {
            "counts": {
                "input_rows": 64,
                "portfolio_chunk_count": 3,
                "portfolio_page_count": 6,
                "benchmark_chunk_count": 2,
                "workspace_detail_block_count": 2,
                "workspace_contribution_periods_emitted": 1,
                "workspace_attribution_periods_emitted": 1,
                "workspace_contribution_position_count": 5,
                "workspace_contribution_position_chunk_count": 2,
                "workspace_contribution_position_page_count": 3,
                "workspace_attribution_instrument_count": 12,
                "workspace_attribution_position_chunk_count": 2,
                "workspace_attribution_position_page_count": 3,
                "workspace_attribution_benchmark_chunk_count": 1,
                "workspace_attribution_benchmark_page_count": 1,
                "workspace_attribution_index_page_count": 1,
            }
        },
    }
]

WORKSPACE_SUMMARY_ACCEPTED_RESPONSE_EXAMPLES = [
    {
        "calculation_id": "0d000003-1111-4222-8333-abcdefabcdef",
        "poll_path": "/performance/executions/0d000003-1111-4222-8333-abcdefabcdef",
        "result_path": "/performance/workspace-summary/results/0d000003-1111-4222-8333-abcdefabcdef",
    }
]


class WorkspaceEconomicContext(BaseModel):
    begin_market_value: float = Field(
        description="Beginning market value for the resolved window in reporting currency units.",
        examples=[1000000.0],
    )
    end_market_value: float = Field(
        description="Ending market value for the resolved window in reporting currency units.",
        examples=[1015000.0],
    )
    beginning_cash_flow: float = Field(
        description="Sum of beginning-of-day external cash flows for the resolved window in reporting currency units.",
        examples=[25000.0],
    )
    ending_cash_flow: float = Field(
        description="Sum of end-of-day external cash flows for the resolved window in reporting currency units.",
        examples=[-5000.0],
    )
    fees: float = Field(
        description="Sum of fees observed in the resolved window in reporting currency units.",
        examples=[-350.0],
    )
    net_cash_flow: float = Field(
        description="Total external cash flow for the resolved window in reporting currency units.",
        examples=[20000.0],
    )
    flow_adjusted_end_market_value: float = Field(
        description="Ending market value after subtracting the resolved window net cash flow.",
        examples=[995000.0],
    )


class WorkspaceReturnValue(BaseModel):
    base: float = Field(description="Return in percentage-point output units.", examples=[1.25])
    local: float | None = Field(
        default=None,
        description="Local-market return component in percentage-point output units when available.",
        examples=[1.1],
    )
    fx: float | None = Field(
        default=None,
        description="FX return component in percentage-point output units when available.",
        examples=[0.15],
    )


class WorkspaceReturnSummary(BaseModel):
    period_return: WorkspaceReturnValue = Field(
        description="Return earned within the resolved window in percentage-point output units."
    )
    cumulative_return: WorkspaceReturnValue = Field(
        description="Cumulative linked return for the resolved window in percentage-point output units."
    )
    annualized_return: WorkspaceReturnValue = Field(
        description="Annualized return for the resolved window in percentage-point output units. For periods up to one year this equals cumulative_return."
    )


class WorkspaceEconomicReturnSummary(WorkspaceReturnSummary):
    economics: WorkspaceEconomicContext = Field(description="Economic context for the resolved window.")


class WorkspaceBreakdownItem(BaseModel):
    period: str = Field(description="Resolved label for this breakdown bucket.", examples=["2026-03"])
    period_start: dt_date = Field(description="Inclusive bucket start date.", examples=["2026-03-01"])
    period_end: dt_date = Field(description="Inclusive bucket end date.", examples=["2026-03-31"])
    economics: WorkspaceEconomicContext | None = Field(
        default=None,
        description="Economic context for this breakdown bucket when the surface owns market-value and cash-flow economics.",
    )
    period_return: WorkspaceReturnValue = Field(
        description="Return earned within this bucket in percentage-point output units."
    )
    cumulative_return: WorkspaceReturnValue = Field(
        description="Cumulative linked return through the end of this bucket in percentage-point output units."
    )
    annualized_return: WorkspaceReturnValue = Field(
        description="Annualized return through the end of this bucket in percentage-point output units. For periods up to one year this equals cumulative_return."
    )


WorkspaceBreakdowns = Dict[Frequency, list[WorkspaceBreakdownItem]]


class WorkspacePerformanceBlock(BaseModel):
    summary: WorkspaceEconomicReturnSummary
    breakdowns: WorkspaceBreakdowns


class WorkspaceBasisPair(BaseModel):
    net: WorkspacePerformanceBlock
    gross: WorkspacePerformanceBlock


class WorkspaceBenchmarkBlock(BaseModel):
    summary: WorkspaceReturnSummary = Field(description="Benchmark return summary for the resolved window.")
    breakdowns: Dict[Frequency, list[WorkspaceBreakdownItem]] = Field(
        description="Benchmark breakdowns using the same requested frequencies and return units."
    )
    benchmark_id: str = Field(description="Resolved benchmark identifier.", examples=["BMK_GLOBAL_60_40"])
    benchmark_currency: str | None = Field(default=None, description="Resolved benchmark base currency.")
    input_mode: BenchmarkInputMode = Field(description="Resolved benchmark input mode.")
    return_source: BenchmarkReturnSource = Field(description="Resolved benchmark return source.")


class WorkspaceActiveBlock(BaseModel):
    net: WorkspaceReturnSummary = Field(description="Net active return summary for the resolved window.")
    gross: WorkspaceReturnSummary = Field(description="Gross active return summary for the resolved window.")


class WorkspaceMoneyWeightedReturnSummary(BaseModel):
    input_mode: MWRInputMode = Field(description="Resolved MWR input mode.")
    method: str = Field(description="Money-weighted return method used for the summary.")
    period_return: float = Field(
        description="Money-weighted return earned within the resolved window in percentage-point output units.",
        examples=[8.42],
    )
    cumulative_return: float = Field(
        description="Money-weighted return in percentage-point output units.",
        examples=[8.42],
    )
    annualized_return: float = Field(
        description="Annualized money-weighted return in percentage-point output units. For periods up to one year this equals cumulative_return.",
        examples=[8.42],
    )
    economics: WorkspaceEconomicContext = Field(description="Economic context for the resolved MWR window.")
    start_date: dt_date = Field(description="Inclusive MWR start date.", examples=["2026-01-01"])
    end_date: dt_date = Field(description="Inclusive MWR end date.", examples=["2026-03-31"])
    notes: list[str] = Field(description="Method or validation notes returned by the engine.")


class WorkspaceContributionSummaryBlock(BaseModel):
    metric_basis: str = Field(description="Metric basis used for the contribution summary block.", examples=["NET"])
    segmentation: list[str] = Field(
        description="Shared segmentation dimensions used for grouped contribution rows.",
        examples=[["sector"]],
    )
    summary: ContributionSummary | None = Field(
        default=None,
        description="Contribution summary totals for the resolved workspace period.",
    )
    levels: list[ContributionLevel] | None = Field(
        default=None,
        description="Grouped contribution rows using the shared workspace segmentation model.",
    )
    position_contributions: list[PositionContribution] = Field(
        description="Position-level contribution rows kept first-class for top and bottom contributor workflows.",
    )


class WorkspaceAttributionSummaryBlock(BaseModel):
    metric_basis: str = Field(description="Metric basis used for the attribution summary block.", examples=["NET"])
    segmentation: list[str] = Field(
        description="Shared segmentation dimensions used for grouped attribution rows.",
        examples=[["sector"]],
    )
    model: AttributionModel = Field(description="Attribution model used for the lightweight summary block.")
    linking: LinkingMethod = Field(description="Linking method used for the lightweight summary block.")
    benchmark_context: AttributionBenchmarkContext | None = Field(
        default=None,
        description="Resolved benchmark context used for attribution.",
    )
    result: SinglePeriodAttributionResult = Field(
        description="Per-period attribution result using the same canonical structure as the dedicated attribution endpoint."
    )


class WorkspacePeriodSummaryResult(BaseModel):
    portfolio_twr: WorkspaceBasisPair
    benchmark: WorkspaceBenchmarkBlock | None = None
    active: WorkspaceActiveBlock | None = None
    money_weighted_return: WorkspaceMoneyWeightedReturnSummary
    contribution: WorkspaceContributionSummaryBlock | None = None
    attribution: WorkspaceAttributionSummaryBlock | None = None


class WorkspaceSummaryResponse(BaseModel):
    calculation_id: UUID = Field(description="Stable calculation handle for this workspace summary.")
    portfolio_id: str = Field(description="Portfolio identifier.", examples=["PORTFOLIO_001"])
    input_mode: TWRInputMode = Field(description="Resolved portfolio input mode for the workspace summary.")
    results_by_period: Dict[str, WorkspacePeriodSummaryResult] = Field(
        description="Workspace summary outputs keyed by the requested workspace period label."
    )
    meta: Meta = Field(description="Shared metadata envelope for the workspace summary.")
    diagnostics: Diagnostics = Field(description="Diagnostic details for the workspace summary.")
    audit: Audit = Field(description="Audit details for the workspace summary.")

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": WORKSPACE_SUMMARY_RESPONSE_EXAMPLES})


class WorkspaceSummaryAcceptedResponse(BaseModel):
    calculation_id: UUID
    poll_path: str
    result_path: str

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": WORKSPACE_SUMMARY_ACCEPTED_RESPONSE_EXAMPLES},
    )
