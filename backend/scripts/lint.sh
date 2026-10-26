#!/usr/bin/env bash

set -e
set -x

# Lint + format-check the entire uv workspace against the single root ruff
# config (backend/pyproject.toml). Run from the backend/ directory.
# Type checking is its own CI step: scripts/typecheck.sh.
ruff check .
ruff format --check .
