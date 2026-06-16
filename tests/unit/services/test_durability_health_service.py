import logging

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


def test_durable_metadata_schema_health_reports_ready_without_lineage_storage(monkeypatch):
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
        lambda: (_ for _ in ()).throw(AssertionError("lineage storage should not be consulted")),
    )

    status = durability_health_service.check_durable_metadata_schema_ready()

    assert status.is_ready is True
    assert status.status == "ready"
    assert status.reason is None


def test_durability_health_service_reports_unavailable_on_ping_failure(monkeypatch, caplog):
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

    with caplog.at_level(logging.WARNING, logger="app.services.durability_health_service"):
        status = durability_health_service.check_durable_metadata_store_ready()

    assert status.is_ready is False
    assert status.status == "unavailable"
    assert status.reason == "durable_metadata_store_unreachable"
    assert "Durable metadata store readiness ping failed." in caplog.text
    assert "RuntimeError: db down" in caplog.text


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


def test_lineage_storage_health_reports_invalid_storage_path(monkeypatch, tmp_path):
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        durability_health_service,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "LINEAGE_STORAGE_PATH": file_path,
                "LINEAGE_STORAGE_HEALTHCHECK_WRITE_PROBE_ENABLED": False,
            },
        )(),
    )

    status = durability_health_service.check_lineage_storage_ready()

    assert status.is_ready is False
    assert status.reason == "lineage_storage_path_invalid"


def test_lineage_storage_health_reports_unreadable_storage_path(monkeypatch, tmp_path):
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
    monkeypatch.setattr(durability_health_service.os, "access", lambda *args: False)

    status = durability_health_service.check_lineage_storage_ready()

    assert status.is_ready is False
    assert status.reason == "lineage_storage_path_unreadable"


def test_lineage_storage_path_status_accepts_readable_directory(tmp_path):
    assert durability_health_service._lineage_storage_path_unavailable_status(tmp_path) is None


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


def test_lineage_storage_health_write_probe_logs_os_errors(monkeypatch, tmp_path, caplog):
    def _raise_os_error(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(durability_health_service.tempfile, "mkstemp", _raise_os_error)

    with caplog.at_level(logging.WARNING, logger="app.services.durability_health_service"):
        ready = durability_health_service._probe_lineage_storage_write(str(tmp_path))

    assert ready is False
    assert "Lineage storage write probe failed." in caplog.text
    assert "OSError: disk unavailable" in caplog.text


def test_get_lineage_storage_capacity_returns_free_space_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(
        durability_health_service,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "LINEAGE_STORAGE_PATH": tmp_path,
            },
        )(),
    )
    monkeypatch.setattr(
        durability_health_service.shutil,
        "disk_usage",
        lambda _: type("Usage", (), {"total": 1000, "used": 250, "free": 750})(),
    )

    snapshot = durability_health_service.get_lineage_storage_capacity()

    assert snapshot.total_bytes == 1000
    assert snapshot.used_bytes == 250
    assert snapshot.free_bytes == 750
    assert snapshot.free_ratio == 0.75
    assert snapshot.used_ratio == 0.25


def test_get_lineage_storage_capacity_requires_configured_path(monkeypatch):
    monkeypatch.setattr(
        durability_health_service,
        "get_settings",
        lambda: type("Settings", (), {"LINEAGE_STORAGE_PATH": None})(),
    )

    try:
        durability_health_service.get_lineage_storage_capacity()
    except FileNotFoundError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_get_lineage_storage_capacity_handles_zero_total_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(
        durability_health_service,
        "get_settings",
        lambda: type("Settings", (), {"LINEAGE_STORAGE_PATH": tmp_path})(),
    )
    monkeypatch.setattr(
        durability_health_service.shutil,
        "disk_usage",
        lambda _: type("Usage", (), {"total": 0, "used": 0, "free": 0})(),
    )

    snapshot = durability_health_service.get_lineage_storage_capacity()

    assert snapshot.total_bytes == 0
    assert snapshot.free_ratio == 0.0
    assert snapshot.used_ratio == 0.0
