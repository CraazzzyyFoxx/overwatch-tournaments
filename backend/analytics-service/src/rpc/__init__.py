"""Typed RPC handlers served by the gateway (``rpc.analytics.*``).

These subscribers run in the lightweight ``analytics-svc`` worker
(``serve_rpc.py``), NOT in the heavy ``analytics-worker`` (``serve.py``).
Each module exposes ``register(broker, logger)`` wired from the entrypoint.

Queue ownership rule: every ``rpc.analytics.*`` queue has exactly one owning
process (this svc). The heavy ML job queues (``ANALYTICS_JOB_QUEUE`` /
``ANALYTICS_TRAIN_QUEUE`` / ``ANALYTICS_INFER_QUEUE``) stay owned by
``analytics-worker`` — do not subscribe to them here.
"""
