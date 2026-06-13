"""Rendezvous between a match-log upload and its processing result.

The bot uploads a log, then blocks on :meth:`ResultWaiter.wait` until the parser
publishes the result (delivered over RabbitMQ and routed in via
:meth:`ResultWaiter.resolve`) or the timeout elapses.

This replaces the former pg ``LISTEN/NOTIFY`` waiter: pgBouncer transaction
pooling silently drops ``LISTEN`` registrations, so notifications never arrived
and every upload timed out. Kept dependency-free (pure asyncio) so it is trivial
to unit test.
"""

import asyncio


class ResultWaiter:
    def __init__(self, timeout: float) -> None:
        self._timeout = timeout
        self._pending: dict[tuple[int, str], asyncio.Future[bool]] = {}

    async def wait(self, tournament_id: int, filename: str) -> bool | None:
        """Block until the result for ``(tournament_id, filename)`` arrives.

        Returns ``True`` (done), ``False`` (failed), or ``None`` (timed out).
        """
        key = (tournament_id, filename)
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[key] = fut
        try:
            return await asyncio.wait_for(fut, timeout=self._timeout)
        except TimeoutError:
            return None
        finally:
            # Drop our own entry only — resolve() may have already replaced/removed it.
            if self._pending.get(key) is fut:
                del self._pending[key]

    def resolve(self, tournament_id: int, filename: str, success: bool) -> None:
        """Resolve a pending waiter; a no-op when none is registered."""
        fut = self._pending.pop((tournament_id, filename), None)
        if fut is not None and not fut.done():
            fut.set_result(success)
