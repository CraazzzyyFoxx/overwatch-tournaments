"""Inference pipeline for v2 models.

- :mod:`runner` — ``run_for_tournament(tid)`` loads active artifacts and writes
  predictions into the ``analytics.*`` tables.
- :mod:`backfill` — historical sweep, idempotent upsert.
"""
