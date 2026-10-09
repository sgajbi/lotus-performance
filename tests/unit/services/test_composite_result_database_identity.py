"""Installed identity admission: actual SQLite files and representative PG rows.

PostgreSQL URL controls are guard proof, not a live two-cluster execution claim.
The required PostgreSQL lane separately exercises actual TCP candidate custody.
"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.adapters.composite_result_candidate_storage import require_same_result_database
from core.errors import APIError


class InstalledPostgresEngine:
    def __init__(self, url, installed):
        self.url = make_url(url)
        self.dialect = SimpleNamespace(name="postgresql")
        self.installed = installed
        self.queries = []

    @contextmanager
    def connect(self):
        yield self

    def execute(self, statement):
        self.queries.append(str(statement))
        assert str(statement) == (
            "SELECT current_database(), current_schema(), inet_server_addr()::text, inet_server_port()"
        )
        return SimpleNamespace(one=lambda: self.installed)


TCP_URL = "postgresql+psycopg://user@server-a/lotus"
TCP_INSTALLED = ("lotus", "public", "192.0.2.10", 5432)


def _require(left, right):
    require_same_result_database(SimpleNamespace(_engine=left), SimpleNamespace(_engine=right))


def test_explicit_and_default_tcp_port_share_the_installed_identity():
    left = InstalledPostgresEngine(TCP_URL, TCP_INSTALLED)
    right = InstalledPostgresEngine("postgresql+psycopg://user@server-a:5432/lotus", TCP_INSTALLED)
    _require(left, right)
    assert len(left.queries) == len(right.queries) == 1


@pytest.mark.parametrize(
    "url,installed",
    [
        ("postgresql+psycopg://user@server-b/lotus", TCP_INSTALLED),
        (TCP_URL, ("different", "public", "192.0.2.10", 5432)),
        (TCP_URL, ("lotus", "other_schema", "192.0.2.10", 5432)),
        (TCP_URL, ("lotus", "public", "192.0.2.11", 5432)),
        (TCP_URL, ("lotus", "public", "192.0.2.10", 5433)),
    ],
)
def test_configured_or_installed_tcp_identity_mismatch_refuses(url, installed):
    with pytest.raises(APIError, match="same installed owning database"):
        _require(InstalledPostgresEngine(TCP_URL, TCP_INSTALLED), InstalledPostgresEngine(url, installed))


@pytest.mark.parametrize("second_socket", ["cluster-a", "cluster-b"])
def test_socket_urls_never_qualify_a_shared_installed_identity(second_socket):
    left = InstalledPostgresEngine(
        "postgresql+psycopg://user@/lotus?host=/tmp/cluster-a", ("lotus", "public", None, None)
    )
    right = InstalledPostgresEngine(
        f"postgresql+psycopg://user@/lotus?host=/tmp/{second_socket}", ("lotus", "public", None, None)
    )
    with pytest.raises(APIError, match="explicit TCP"):
        _require(left, right)
    assert not left.queries and not right.queries


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://user@/lotus",
        "postgresql+psycopg://user@server-a",
        TCP_URL + "?host=/tmp/cluster-a",
        TCP_URL + "?host=server-b",
        TCP_URL + "?hostaddr=192.0.2.11",
        TCP_URL + "?port=5433",
        TCP_URL + "?dbname=different",
        TCP_URL + "?service=other_cluster",
        TCP_URL + "?servicefile=/tmp/pg_service.conf",
    ],
)
def test_implicit_or_overridden_connection_destination_refuses_before_query(url):
    engine = InstalledPostgresEngine(url, TCP_INSTALLED)
    with pytest.raises(APIError, match="explicit TCP"):
        _require(engine, engine)
    assert not engine.queries


@pytest.mark.parametrize("missing", range(4))
def test_incomplete_installed_tcp_evidence_refuses_even_when_both_rows_match(missing):
    installed = list(TCP_INSTALLED)
    installed[missing] = None
    engine = InstalledPostgresEngine(TCP_URL, tuple(installed))
    with pytest.raises(APIError, match="Installed PostgreSQL"):
        _require(engine, engine)
    assert len(engine.queries) == 1


def test_sqlite_same_file_accepts_and_distinct_files_refuse(tmp_path):
    engines = [create_engine(f"sqlite:///{tmp_path / name}") for name in ("a.db", "a.db", "b.db")]
    try:
        for engine in engines:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE IF NOT EXISTS marker (id INTEGER)"))
        _require(engines[0], engines[1])
        with pytest.raises(APIError, match="same installed owning database"):
            _require(engines[0], engines[2])
    finally:
        for engine in engines:
            engine.dispose()
