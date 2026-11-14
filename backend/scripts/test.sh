#!/usr/bin/env bash
# Backend test suites with coverage, the same way CI runs them.
#
#   bash scripts/test.sh                 # every suite, then a coverage report + htmlcov/
#   bash scripts/test.sh stats-service   # just these suites
#
# A suite is a workspace member (shared, app-service, ...) or `tests`, the root cross-service suite.
# Each runs in its own pytest (every member has its own top-level `src`), against the ephemeral test
# Postgres from shared/testing/test.env, which is started on demand.
# COVERAGE_COMBINE=0 leaves the .coverage.* data files for a later `coverage combine` (CI's matrix).
set -euo pipefail
cd "$(dirname "$0")/.."

suites=("$@")
if [[ ${#suites[@]} -eq 0 ]]; then
  suites=(shared app-service stats-service balancer-service tournament-service analytics-service
    identity-service discord-service stream-service tests)
fi
combine="${COVERAGE_COMBINE:-1}"
if [[ "$combine" == 1 ]]; then rm -f .coverage .coverage.*; fi

for svc in "${suites[@]}"; do
  case "$svc" in
    shared) src=shared path=shared/tests ;;
    # The cross-service gates (module boundaries, literals, repository boundaries, migration/script tests).
    tests) src=scripts path=tests ;;
    *) src="$svc/src" path="$svc/tests" ;;
  esac
  if [[ -n "${GITHUB_ACTIONS:-}" ]]; then echo "::group::pytest $svc"; else echo "== pytest $svc"; fi
  # test.env in the process environment: it wins over a local backend/.env that may point elsewhere.
  uv run --env-file shared/testing/test.env coverage run --parallel-mode --source="$src" -m pytest "$path"
  if [[ -n "${GITHUB_ACTIONS:-}" ]]; then echo "::endgroup::"; fi
done

if [[ "$combine" == 1 ]]; then
  # The suites above already synced the environment: install and build nothing more.
  uv run --no-sync coverage combine -q
  uv run --no-sync coverage report
  uv run --no-sync coverage html -q --title "OWT"
fi
