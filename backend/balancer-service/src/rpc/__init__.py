"""Typed-RPC handlers for balancer-service (balancer-svc).

Hosts the ``rpc.balancer.*`` subscribers that replace the HTTP balancer-service
(``main.py``) behind the Go gateway. The headless ``balancer-worker`` (serve.py)
registers these alongside the existing job-queue consumer and draft-clock
supervisor.
"""
