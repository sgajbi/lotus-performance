from tests.benchmarks import postgres_runtime_helpers


def test_get_postgres_database_url_uses_short_connect_timeout(mocker):
    engine = mocker.MagicMock()
    connection = mocker.MagicMock()
    engine.begin.return_value.__enter__.return_value = connection
    mocked_create_engine = mocker.patch(
        "tests.benchmarks.postgres_runtime_helpers.create_engine",
        return_value=engine,
    )
    mocked_uuid4 = mocker.patch("tests.benchmarks.postgres_runtime_helpers.uuid4")
    mocked_uuid4.return_value.hex = "abc123"

    database_url = postgres_runtime_helpers.get_postgres_database_url()

    assert database_url == (
        f"{postgres_runtime_helpers.POSTGRES_RUNTIME_DATABASE_URL}" "?options=-csearch_path%3Dlotus_perf_bench_abc123"
    )
    mocked_create_engine.assert_called_once_with(
        postgres_runtime_helpers.POSTGRES_RUNTIME_DATABASE_URL,
        future=True,
        connect_args={"connect_timeout": postgres_runtime_helpers.POSTGRES_RUNTIME_CONNECT_TIMEOUT_SECONDS},
    )
    connection.execute.assert_called_once()
    connection.exec_driver_sql.assert_called_once_with('CREATE SCHEMA IF NOT EXISTS "lotus_perf_bench_abc123"')
    engine.dispose.assert_called_once()
