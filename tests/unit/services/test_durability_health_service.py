from app.services import durability_health_service


def test_durability_health_service_reports_ready(monkeypatch):
    monkeypatch.setattr(durability_health_service.execution_registry, "ping", lambda: None)
    monkeypatch.setattr(
        "app.services.durability_health_service.inspect",
        lambda _engine: type("Inspector", (), {"get_table_names": lambda self: list(durability_health_service.REQUIRED_DURABLE_TABLES)})(),
    )

    status = durability_health_service.check_durable_metadata_store_ready()

    assert status.is_ready is True
    assert status.status == "ready"
    assert status.reason is None


def test_durability_health_service_reports_unavailable_on_ping_failure(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(durability_health_service.execution_registry, "ping", _boom)

    status = durability_health_service.check_durable_metadata_store_ready()

    assert status.is_ready is False
    assert status.status == "unavailable"
    assert status.reason == "durable_metadata_store_unreachable"


def test_durability_health_service_reports_unavailable_on_missing_required_schema(monkeypatch):
    monkeypatch.setattr(durability_health_service.execution_registry, "ping", lambda: None)
    monkeypatch.setattr(
        "app.services.durability_health_service.inspect",
        lambda _engine: type(
            "Inspector",
            (),
            {"get_table_names": lambda self: list(durability_health_service.REQUIRED_DURABLE_TABLES[:-1])},
        )(),
    )

    status = durability_health_service.check_durable_metadata_store_ready()

    assert status.is_ready is False
    assert status.status == "unavailable"
    assert status.reason == "durable_metadata_schema_incomplete"
