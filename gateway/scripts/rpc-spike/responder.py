"""Minimal FastStream RPC responder for the Go<->FastStream interop spike.

Run (from repo root):
    uv run --directory backend python ../gateway/scripts/rpc-spike/responder.py

A FastStream subscriber that *returns* a value auto-publishes that value to the
incoming message's reply_to with the same correlation_id — which is exactly the
AMQP request-reply contract a non-Python (Go) client speaks. This proves the
gateway can RPC into FastStream services without FastStream on the client side.
"""

import asyncio

from faststream import FastStream
from faststream.rabbit import RabbitBroker

broker = RabbitBroker("amqp://guest:guest@localhost:5672")
app = FastStream(broker)


@broker.subscriber("rpc.spike.echo")
async def echo(data: dict) -> dict:
    # The return value becomes the RPC reply.
    return {"echo": data, "pong": True, "service": "faststream"}


if __name__ == "__main__":
    asyncio.run(app.run())
