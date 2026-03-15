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


def test_get_postgres_database_url_appends_search_path_to_existing_options(mocker):
    engine = mocker.MagicMock()
    connection = mocker.MagicMock()
    engine.begin.return_value.__enter__.return_value = connection
    mocked_create_engine = mocker.patch(
        "tests.benchmarks.postgres_runtime_helpers.create_engine",
        return_value=engine,
    )
    mocked_uuid4 = mocker.patch("tests.benchmarks.postgres_runtime_helpers.uuid4")
    mocked_uuid4.return_value.hex = "def456"
    mocker.patch(
        "tests.benchmarks.postgres_runtime_helpers.POSTGRES_RUNTIME_DATABASE_URL",
        "postgresql+psycopg://lotus:lotus@127.0.0.1:5435/lotus_performance?options=-ctimezone%3DUTC",
    )

    database_url = postgres_runtime_helpers.get_postgres_database_url()

    assert "options=-ctimezone%3DUTC+-csearch_path%3Dlotus_perf_bench_def456" in database_url
    mocked_create_engine.assert_called_once()
    engine.dispose.assert_called_once()


def test_get_postgres_database_url_skips_when_runtime_database_is_unavailable(mocker):
    engine = mocker.MagicMock()
    engine.begin.return_value.__enter__.side_effect = postgres_runtime_helpers.OperationalError(
        "SELECT 1", {}, Exception("boom")
    )
    mocker.patch("tests.benchmarks.postgres_runtime_helpers.create_engine", return_value=engine)

    try:
        postgres_runtime_helpers.get_postgres_database_url()
    except BaseException as exc:  # pragma: no cover - pytest skip raises a framework exception
        assert exc.__class__.__name__ == "Skipped"
        assert "PostgreSQL runtime proof database unavailable" in str(exc)
    else:
        raise AssertionError("Expected get_postgres_database_url to skip when PostgreSQL is unavailable")
    engine.dispose.assert_called_once()
