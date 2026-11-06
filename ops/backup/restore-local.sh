#!/bin/bash
# Restore ONE backup dump into a throwaway local postgres:18 for rehearsals (e.g. the league merge, docs/backup-rustfs.md).
#   make backup-restore-local DUMP=pg/moscow/2026-11-05/owt-20261105-043000.dump
# DUMP is a path under the bucket's pg/ layout (see `make backup-ls`). Prod dumps are pg_dump 18 (backup.sh), so the
# dev postgres:16 cannot read them: the target is its own container, owt-restore-pg on 127.0.0.1:55433, db owt_restore.
set -euo pipefail
: "${DUMP:?set DUMP=<object path from make backup-ls>}"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ENVFILE="${ENVFILE:-$SCRIPT_DIR/s3.env}"
TMP="${TMP:-$SCRIPT_DIR/tmp}"
CONTAINER=owt-restore-pg
DB=owt_restore
# shellcheck disable=SC1090
set -a; . "$ENVFILE"; set +a
mkdir -p "$TMP"
trap 'rm -rf "${TMP:?}"/*' EXIT

docker run --rm --env-file "$ENVFILE" -v "$TMP:/data" rclone/rclone \
  copyto "tw:$BUCKET/$DUMP" "/data/restore.dump" --s3-no-check-bucket --stats-one-line

if ! docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  docker run -d --name "$CONTAINER" -e POSTGRES_PASSWORD=postgres -p 127.0.0.1:55433:5432 postgres:18
fi
docker start "$CONTAINER" > /dev/null
until docker exec "$CONTAINER" pg_isready -U postgres > /dev/null 2>&1; do sleep 1; done

docker exec "$CONTAINER" dropdb -U postgres --if-exists "$DB"
docker exec "$CONTAINER" createdb -U postgres "$DB"
docker exec -i "$CONTAINER" pg_restore -U postgres -d "$DB" --no-owner --no-privileges --exit-on-error < "$TMP/restore.dump"

echo "restored $DUMP into $CONTAINER/$DB. Use:"
echo "  POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55433 POSTGRES_DB=$DB POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres"
