"""Typed-RPC handlers for parser-service.

Each module exposes ``register(broker, logger)`` and is wired in ``serve.py``.
Handlers decode the gateway request and emit the ``{ok,data,error}`` envelope via
``src.rpc._common``. Only parser-unique domains live here (match-log, OverFast
rank, achievement engine + rules admin, OverFast metadata sync, settings,
discord-channel); everything else is owned by app-service / tournament-service.
"""
