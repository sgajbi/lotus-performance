from app.services import durability_health_service


def test_durability_health_service_reports_ready(monkeypatch):
    registry = type(
        "Registry",
        (),
        {
            "ping": staticmethod(lambda: None),
            "list_table_names": staticmethod(lambda: list(durability_health_service.REQUIRED_DURABLE_TABLES)),
        },
    )()
    monkeypatch.setattr(durability_health_service, "get_execution_registry", lambda: registry)
    monkeypatch.setattr(
        durability_health_service,
        "check_lineage_storage_ready",
        lambda: durability_health_service.DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )

    status = durability_health_service.check_durable_metadata_store_ready()

    assert status.is_ready is True
    assert status.status == "ready"
    assert status.reason is None


def test_durability_health_service_reports_unavailable_on_ping_failure(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    registry = type(
        "Registry",
        (),
        {
            "ping": staticmethod(_boom),
            "list_table_names": staticmethod(lambda: list(durability_health_service.REQUIRED_DURABLE_TABLES)),
        },
    )()
    monkeypatch.setattr(durability_health_service, "get_execution_registry", lambda: registry)
    monkeypatch.setattr(
        durability_health_service,
        "check_lineage_storage_ready",
        lambda: durability_health_service.DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )

    status = durability_health_service.check_durable_metadata_store_ready()

    assert status.is_ready is False
    assert status.status == "unavailable"
    assert status.reason == "durable_metadata_store_unreachable"


def test_durability_health_service_reports_unavailable_on_missing_required_schema(monkeypatch):
    registry = type(
        "Registry",
        (),
        {
            "ping": staticmethod(lambda: None),
            "list_table_names": staticmethod(lambda: list(durability_health_service.REQUIRED_DURABLE_TABLES[:-1])),
        },
    )()
    monkeypatch.setattr(durability_health_service, "get_execution_registry", lambda: registry)
    monkeypatch.setattr(
        durability_health_service,
        "check_lineage_storage_ready",
        lambda: durability_health_service.DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )

    status = durability_health_service.check_durable_metadata_store_ready()

    assert status.is_ready is False
    assert status.status == "unavailable"
    assert status.reason == "durable_metadata_schema_incomplete"


def test_durability_health_service_reports_unavailable_when_lineage_storage_is_missing(monkeypatch):
    registry = type(
        "Registry",
        (),
        {
            "ping": staticmethod(lambda: None),
            "list_table_names": staticmethod(lambda: list(durability_health_service.REQUIRED_DURABLE_TABLES)),
        },
    )()
    monkeypatch.setattr(durability_health_service, "get_execution_registry", lambda: registry)
    monkeypatch.setattr(
        durability_health_service,
        "check_lineage_storage_ready",
        lambda: durability_health_service.DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="lineage_storage_path_missing",
        ),
    )

    status = durability_health_service.check_durable_metadata_store_ready()

    assert status.is_ready is False
    assert status.status == "unavailable"
    assert status.reason == "lineage_storage_path_missing"


def test_lineage_storage_health_reports_write_probe_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        durability_health_service,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "LINEAGE_STORAGE_PATH": tmp_path,
                "LINEAGE_STORAGE_HEALTHCHECK_WRITE_PROBE_ENABLED": True,
            },
        )(),
    )
    monkeypatch.setattr(durability_health_service, "_probe_lineage_storage_write", lambda _: False)

    status = durability_health_service.check_lineage_storage_ready()

    assert status.is_ready is False
    assert status.status == "unavailable"
    assert status.reason == "lineage_storage_write_probe_failed"


def test_lineage_storage_health_skips_write_probe_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(
        durability_health_service,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "LINEAGE_STORAGE_PATH": tmp_path,
                "LINEAGE_STORAGE_HEALTHCHECK_WRITE_PROBE_ENABLED": False,
            },
        )(),
    )
    monkeypatch.setattr(
        durability_health_service,
        "_probe_lineage_storage_write",
        lambda _: (_ for _ in ()).throw(AssertionError("write probe should not run")),
    )

    status = durability_health_service.check_lineage_storage_ready()

    assert status.is_ready is True
    assert status.status == "ready"
    assert status.reason is None


def test_lineage_storage_health_write_probe_cleans_up_temp_file(tmp_path):
    storage_path = tmp_path / "lineage"
    storage_path.mkdir()

    ready = durability_health_service._probe_lineage_storage_write(str(storage_path))

    assert ready is True
    assert list(storage_path.iterdir()) == []
