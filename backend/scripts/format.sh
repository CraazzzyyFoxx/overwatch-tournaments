#!/bin/sh -e

set -x

# Auto-fix + format the entire uv workspace. Run from the backend/ directory.
ruff check . --fix
ruff format .
