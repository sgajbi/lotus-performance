"""Process signals bridge to the existing worker stop-event lifecycle."""

from collections.abc import Iterator
from contextlib import contextmanager
from signal import SIGINT, SIGTERM, signal
from threading import Event
from types import FrameType


@contextmanager
def shutdown_signals() -> Iterator[Event]:
    """Stop batch admission on termination; leave admitted work to its owner."""
    stop_event = Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        stop_event.set()

    previous_handlers = {}
    try:
        for signum in (SIGTERM, SIGINT):
            previous_handlers[signum] = signal(signum, request_stop)
        yield stop_event
    finally:
        for signum, previous in reversed(previous_handlers.items()):
            signal(signum, previous)
