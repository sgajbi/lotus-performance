import pytest

from tests.source_refusal_contract_helpers import assert_durable_source_refusal, assert_retryable_source_failure


def test_source_refusal_worker_restart_and_public_polling(tmp_path, monkeypatch, caplog):
    assert_durable_source_refusal(f"sqlite:///{tmp_path / 'runtime.db'}", monkeypatch, tmp_path, caplog)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429, 500, 502, 503, 504, "timeout", "malformed"])
def test_source_refusal_unknown_eventual_and_transport_preserve_retry_budget(tmp_path, monkeypatch, status, caplog):
    assert_retryable_source_failure(f"sqlite:///{tmp_path / 'runtime.db'}", monkeypatch, status, tmp_path, caplog)
