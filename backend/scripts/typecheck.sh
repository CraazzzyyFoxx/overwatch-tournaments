#!/usr/bin/env bash

set -u

# ty type-check gate over the whole uv workspace, against ty-gate.toml.
# Run from the backend/ directory: uv run bash scripts/typecheck.sh
#
# One ty run per package: every service has its own top-level `src` (and
# `tests`), so a single run resolves all of them to whichever root comes first.
# A package's own root goes first; `.` resolves `shared`.
status=0
check() {
    roots=$1
    shift
    echo "ty check $*"
    ty check --config-file ty-gate.toml -c "environment.root = $roots" "$@" || status=1
}

check '["."]' shared tests scripts migrations
for svc in *-service; do
    check "[\"$svc\", \".\"]" "$svc"
done
exit $status
