#!/usr/bin/env bash

set -e
set -x

# Lint + format-check the entire uv workspace against the single root ruff
# config (backend/pyproject.toml). Run from the backend/ directory.
# Type checking (mypy/ty) is intentionally not part of the CI lint gate.
ruff check .
ruff format --check .
