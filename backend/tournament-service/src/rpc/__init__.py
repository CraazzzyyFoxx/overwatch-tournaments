"""Typed RPC handlers for tournament-service (called by the Go gateway).

The gateway translates HTTP into ``rpc.tournament.<method>`` calls; handlers here
reuse the existing service ``*_flows`` and return the shared ``{ok,data,error}``
envelope. Registration is wired in ``serve.py`` (the tournament-worker process).
"""
