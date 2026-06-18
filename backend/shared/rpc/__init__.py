"""Reusable RPC infrastructure for headless services behind the Go gateway.

- ``identity``: rehydrate an AuthUser from the gateway-injected RBAC payload and
  check permissions imperatively (no FastAPI Depends, no DB lookup).
- ``crud``: a config-driven generic CRUD-over-RPC engine. Each service declares
  ``EntityConfig`` rows and wires the generic subscribers under its own queue
  prefix; uniform CRUD collapses to config instead of hand-written handlers.
"""
