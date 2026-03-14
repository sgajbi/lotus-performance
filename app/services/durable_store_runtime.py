from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from app.core.config import get_settings

T = TypeVar("T")


def resolve_runtime_store(
    *,
    cache: dict[str, T],
    factory: Callable[[str], T],
    database_url: str | None = None,
) -> T:
    active_database_url = database_url or get_settings().LINEAGE_METADATA_DATABASE_URL
    store = cache.get(active_database_url)
    if store is None:
        store = factory(active_database_url)
        cache[active_database_url] = store
    return store


class RuntimeStoreProxy(Generic[T]):
    def __init__(self, resolver: Callable[[], T]):
        self._resolver = resolver

    def __getattr__(self, name: str):
        return getattr(self._resolver(), name)
