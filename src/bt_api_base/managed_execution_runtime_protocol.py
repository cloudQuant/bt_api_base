"""Neutral owner-thread call contract for existing managed runtimes.

This protocol describes a scheduling boundary, not an execution capability.
Only trusted SDK composition should inject an implementation bound to the
selected runtime and its exact owner thread. Provider packages must not create
a replacement thread or call native owner objects directly from caller
threads.

Calls are synchronous and at-most-once. For a queued call, start is the
runtime's atomic ``queued`` to ``running`` transition; after that transition,
the callback is no longer cancellable. If a call times out before it starts,
the implementation must cancel it so the callback cannot run later. If the
callback has started, a timeout is uncertain: the callback may still finish,
and the caller must preserve UNKNOWN and must not retry. Calls made from the
owner thread execute inline; ``timeout_seconds`` only bounds cross-thread
waiting and never interrupts or limits a running callback. Runtime lifecycle
and shutdown remain owned by the runtime that provides this port.
"""

from __future__ import annotations

from typing import Callable, Protocol, TypeVar, runtime_checkable

__all__ = ("OwnerThreadCallError", "OwnerThreadCallPort")

_OWNER_THREAD_CALL_CODES = frozenset(
    {
        "OWNER_THREAD_CALL_QUEUE_FULL",
        "OWNER_THREAD_CALL_NOT_READY",
        "OWNER_THREAD_CALL_TIMEOUT_BEFORE_START",
        "OWNER_THREAD_CALL_TIMEOUT_AFTER_START",
        "OWNER_THREAD_CALL_CLOSED",
        "OWNER_THREAD_CALL_UNAVAILABLE",
        "OWNER_THREAD_RUNTIME_CLOSING",
    }
)

T = TypeVar("T")


class OwnerThreadCallError(RuntimeError):
    """Finite, non-sensitive owner-mailbox status.

    Exceptions raised by the callback itself are not wrapped in this type.
    Such an exception occurs after callback entry and its native-dispatch
    outcome may be unknown.
    """

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in _OWNER_THREAD_CALL_CODES:
            raise ValueError("owner_thread_call_code_invalid")
        self.code = code
        super().__init__(code)


@runtime_checkable
class OwnerThreadCallPort(Protocol):
    """Synchronous single-call handoff to an already running owner thread.

    The concrete runtime owns thread creation, readiness, bounded queuing,
    maintenance-loop draining, cancellation before start, and shutdown. The
    queued-to-running transition is the atomic cancellation boundary. Calls
    from the owner thread execute inline, without timeout preemption. This
    interface does not grant permission to submit an order or perform any
    other protected operation; the managed execution owner still verifies
    the request, authorization, claim, session, and one-shot dispatch.
    """

    def call_on_owner_thread(
        self,
        callback: Callable[[], T],
        *,
        timeout_seconds: float = 5.0,
    ) -> T: ...
