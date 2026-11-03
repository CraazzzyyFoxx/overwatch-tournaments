"""``GuildQueues``: one sequential worker per guild, highest priority first, FIFO within a priority."""

import asyncio
from unittest import IsolatedAsyncioTestCase

from src.services.guild_queue import GuildQueues, Priority


class GuildQueueTests(IsolatedAsyncioTestCase):
    async def test_runs_by_priority_then_in_submission_order(self) -> None:
        queues, ran, gate = GuildQueues(), [], asyncio.Event()

        def job(name: str):
            async def work() -> str:
                ran.append(name)
                return name

            return work

        async def blocker() -> None:
            await gate.wait()
            ran.append("blocker")

        futures = [queues.submit(1, Priority.DELETE, blocker)]  # occupies the worker while the rest queue up
        await asyncio.sleep(0)
        for name, priority in [
            ("delete", Priority.DELETE),
            ("structure-1", Priority.STRUCTURE),
            ("round-1", Priority.ROUND_MOVE),
            ("hub", Priority.HUB_MOVE),
            ("structure-2", Priority.STRUCTURE),
            ("round-2", Priority.ROUND_MOVE),
        ]:
            futures.append(queues.submit(1, priority, job(name)))
        gate.set()
        await asyncio.gather(*futures)

        self.assertEqual(ran, ["blocker", "hub", "round-1", "round-2", "structure-1", "structure-2", "delete"])

    async def test_the_result_and_the_error_go_to_the_submitter(self) -> None:
        queues = GuildQueues()

        async def boom() -> None:
            raise RuntimeError("nope")

        async def fine() -> int:
            return 7

        failing, working = queues.submit(1, Priority.STRUCTURE, boom), queues.submit(1, Priority.STRUCTURE, fine)

        with self.assertRaisesRegex(RuntimeError, "nope"):
            await failing
        self.assertEqual(await working, 7)  # one failed call does not stop the worker

    async def test_guilds_do_not_wait_for_each_other(self) -> None:
        queues, gate = GuildQueues(), asyncio.Event()

        async def stuck() -> None:
            await gate.wait()

        async def quick() -> str:
            return "done"

        blocked = queues.submit(1, Priority.STRUCTURE, stuck)
        self.assertEqual(await queues.submit(2, Priority.STRUCTURE, quick), "done")
        gate.set()
        await blocked
