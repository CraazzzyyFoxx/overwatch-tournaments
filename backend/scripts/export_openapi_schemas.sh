#!/usr/bin/env bash
# Regenerate gateway/internal/openapi/schemas.json from each service's
# src/openapi_schemas.py. Run from anywhere:  bash backend/scripts/export_openapi_schemas.sh
#
# Importing the schema modules instantiates each service's Settings(), so we feed
# dummy connection env — the export only builds Pydantic JSON Schemas and never
# connects to anything.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # backend/scripts
backend="$(dirname "$here")"                            # backend
out="$backend/../gateway/internal/openapi/schemas.json"

export POSTGRES_USER=x POSTGRES_PASSWORD=x POSTGRES_DB=x POSTGRES_HOST=x POSTGRES_PORT=5432
export REDIS_URL="redis://x:6379" RABBITMQ_URL="amqp://x" JWT_SECRET_KEY=x SECRET_KEY=x

# Services that declare src/openapi_schemas.py. Extend as coverage grows.
services=(tournament-service app-service)

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

frags=()
for svc in "${services[@]}"; do
  if [ -f "$backend/$svc/src/openapi_schemas.py" ]; then
    echo "exporting $svc ..." >&2
    (cd "$backend/$svc" && uv run python "$here/export_openapi_schemas.py") > "$tmp/$svc.json"
    frags+=("$tmp/$svc.json")
  fi
done

uv --project "$backend" run python "$here/merge_openapi_schemas.py" "${frags[@]}" > "$out"
echo "wrote $out ($(wc -c < "$out") bytes)" >&2
