"""Concurrent registration conflicts must re-read custody or refuse chronology."""

from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy.exc import IntegrityError

from app.adapters import composite_materialization_repository as repository
from core.errors import APIError
from tests.composite_materialization_helpers import command_for


@pytest.mark.parametrize("collision", [False, True])
def test_registration_insert_race_replays_only_exact_retained_winner(monkeypatch, collision):
    command, session, read_session = command_for(), MagicMock(), MagicMock()
    session.get.return_value = None
    session.flush.side_effect = IntegrityError("insert", {}, Exception("chronology collision"))
    retained = object() if collision else None
    read_session.get.return_value = retained
    store = object.__new__(repository.CompositeMaterializationStore)
    store._write_session = MagicMock()
    store._write_session.return_value.__enter__.return_value = session
    store._session_factory = MagicMock()
    store._session_factory.return_value.__enter__.return_value = read_session
    replay = Mock(return_value=object())
    monkeypatch.setattr(store, "_replay", replay)
    monkeypatch.setattr(repository, "_require_new_chronology", Mock())
    if collision:
        result = store.register(command, tenant_id="tenant-a", actor_id="maker")
        assert result is replay.return_value
        replay.assert_called_once_with(retained, command, session=read_session)
    else:
        with pytest.raises(APIError) as error:
            store.register(command, tenant_id="tenant-a", actor_id="maker")
        assert error.value.error_code == "COMPOSITE_MATERIALIZATION_SCOPE_CONFLICT"
        replay.assert_not_called()
    session.rollback.assert_called_once()
    read_session.get.assert_called_once_with(
        repository.CompositeMaterializationModel, ("tenant-a", str(command.materialization_id))
    )
