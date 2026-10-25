"""Typed RPC handlers served by the gateway (``rpc.stream.*``).

Each module exposes ``register(broker, logger)``, wired from ``serve.py``.

| subject | auth | HTTP route |
|---|---|---|
| ``rpc.stream.tournament_streams`` | none | ``GET /api/v1/streams/tournament/{tournament_id}`` |
| ``rpc.stream.tournament_vods`` | none | ``GET /api/v1/streams/tournament/{tournament_id}/vods`` |
| ``rpc.stream.encounter_vods`` | none | ``GET /api/v1/streams/encounter/{encounter_id}/vods`` |
| ``rpc.stream.repoll`` | ``stream.update`` | ``POST /api/v1/streams/tournament/{tournament_id}/repoll`` |

Queue ownership rule: every ``rpc.stream.*`` queue has exactly one owning
process (``stream-svc``).
"""
