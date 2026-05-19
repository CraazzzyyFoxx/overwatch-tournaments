"""Training pipeline for v2 models.

- :mod:`splits` — rolling-origin time-series splits over tournaments.
- :mod:`registry` — :class:`MLModelArtifact` CRUD + filesystem storage.
- :mod:`orchestrator` — high-level ``train_all_models(cutoff_id)`` entry point.
- :mod:`backtest` — rolling backtest harness (Phase 6).
"""
