from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.contribution_analytics_requests import ContributionAnalyticsRequest
from app.services.contribution_mode_service import resolve_contribution_request
from app.services.execution_registry import execution_registry


def _settings():
    return SimpleNamespace(
        CORE_QUERY_BASE_URL="http://core",
        CORE_TIMEOUT_SECONDS=5.0,
        CORE_MAX_RETRIES=2,
        CORE_RETRY_BACKOFF_SECONDS=0.1,
        STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS=90,
        STATEFUL_INPUT_REFERENCE_CHUNK_DAYS=365,
        STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS=4,
    )


@pytest.fixture(autouse=True)
def _execution_schema():
    execution_registry.create_schema()
    execution_registry.clear_all_records()
    yield
    execution_registry.clear_all_records()


@pytest.mark.asyncio
async def test_resolve_contribution_request_passthroughs_stateless_mode():
    request = ContributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "CONTRIB_1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                ],
            },
            "positions_data": [],
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="Contribution",
        portfolio_id=request.portfolio_id,
    )

    resolved = await resolve_contribution_request(request, settings=_settings())

    assert resolved.input_mode.value == "stateless"
    assert resolved.contribution_request.portfolio_data.metric_basis == "NET"


@pytest.mark.asyncio
async def test_resolve_contribution_request_sources_stateful_payload(monkeypatch):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                observations=[
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    },
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": "1010",
                        "ending_market_value": "1020",
                    },
                ],
            ),
            position_rows=[
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "600",
                    "ending_market_value_portfolio_currency": "606",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "valuation_date": "2025-01-02",
                    "beginning_market_value_portfolio_currency": "606",
                    "ending_market_value_portfolio_currency": "612.06",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                },
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    request = ContributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "CONTRIB_1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {"consumer_system": "lotus-performance"},
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="Contribution",
        portfolio_id=request.portfolio_id,
    )

    resolved = await resolve_contribution_request(request, settings=_settings())

    assert resolved.input_mode.value == "stateful"
    assert len(resolved.contribution_request.portfolio_data.valuation_points) == 2
    assert len(resolved.contribution_request.positions_data) == 1
    assert resolved.contribution_request.positions_data[0].meta["sector"] == "Technology"


@pytest.mark.asyncio
async def test_resolve_contribution_request_fails_retrieval_stage_on_source_error(monkeypatch):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        raise HTTPException(status_code=503, detail="stateful position timeseries source unavailable (503).")

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    request = ContributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "CONTRIB_1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {"consumer_system": "lotus-performance"},
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="Contribution",
        portfolio_id=request.portfolio_id,
    )

    with pytest.raises(HTTPException, match="stateful position timeseries source unavailable"):
        await resolve_contribution_request(request, settings=_settings())

    execution = execution_registry.get_execution(request.calculation_id)
    assert execution is not None
    stages = {stage.stage_name: stage for stage in execution.stages}
    assert stages["retrieval"].status.value == "failed"


@pytest.mark.asyncio
async def test_resolve_contribution_request_rejects_currency_mode_both(monkeypatch):
    async def _mock_retrieve_stateful_contribution_source_input(**kwargs):  # noqa: ARG001
        return SimpleNamespace(
            portfolio_input=SimpleNamespace(
                observations=[
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    },
                ],
            ),
            position_rows=[
                {
                    "position_id": "SEC_1",
                    "security_id": "SEC_1",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "1000",
                    "ending_market_value_portfolio_currency": "1010",
                    "beginning_market_value_position_currency": "900",
                    "ending_market_value_position_currency": "909",
                    "cash_flows": [],
                    "dimensions": {"sector": "Technology"},
                }
            ],
        )

    monkeypatch.setattr(
        "app.services.contribution_mode_service.retrieve_stateful_contribution_source_input",
        _mock_retrieve_stateful_contribution_source_input,
    )

    request = ContributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "CONTRIB_1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "currency_mode": "BOTH",
            "report_ccy": "USD",
            "input_mode": "stateful",
            "stateful_input": {"consumer_system": "lotus-performance"},
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="Contribution",
        portfolio_id=request.portfolio_id,
    )

    with pytest.raises(HTTPException, match="position-timeseries exposes position_currency"):
        await resolve_contribution_request(request, settings=_settings())

    execution = execution_registry.get_execution(request.calculation_id)
    assert execution is not None
    stages = {stage.stage_name: stage for stage in execution.stages}
    assert stages["normalization"].status.value == "failed"
