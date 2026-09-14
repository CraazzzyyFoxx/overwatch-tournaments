#!/bin/bash
# Nightly logical backup of every database in db_postgres -> Timeweb S3.
# Layout: s3://$BUCKET/pg/<host>/<YYYY-MM-DD>/<db>-<stamp>.dump
#
# Prod (Moscow): crontab  30 4 * * * /root/pg-backup/backup.sh >> /var/log/pg-backup.log 2>&1
set -euo pipefail
HOSTTAG=${HOSTTAG:-moscow}
CONTAINER=db_postgres
PGSUPER=system
RETENTION=30d
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ENVFILE="${ENVFILE:-$SCRIPT_DIR/s3.env}"
TMP="${TMP:-$SCRIPT_DIR/tmp}"
TEXTFILE_DIR="${TEXTFILE_DIR:-/var/lib/node_exporter/textfile}"
# shellcheck disable=SC1090
set -a; . "$ENVFILE"; set +a
STAMP=$(date -u +%Y%m%d-%H%M%S)
DAY=$(date -u +%Y-%m-%d)
mkdir -p "$TMP"

# textfile for monitoring/prometheus/rules/backup.yml (node-exporter already scrapes this dir)
PROM_FILE="$TEXTFILE_DIR/owt_backup.prom"
prev_metric() {
	[[ -r "$PROM_FILE" ]] || { echo 0; return; }
	awk -v k="$1" '$1 == k { print $2 }' "$PROM_FILE" | tail -1 | grep -E '^[0-9.]+$' || echo 0
}
LAST_SUCCESS="$(prev_metric owt_backup_last_success_timestamp_seconds)"
STARTED_AT="$(date +%s)"
STATUS=0
BYTES_TOTAL=0
write_metrics() {
	local now; now="$(date +%s)"
	mkdir -p "$TEXTFILE_DIR" || return 0
	cat > "$PROM_FILE.tmp" <<EOF
# HELP owt_backup_last_status 1 if the last run finished, 0 if it failed.
# TYPE owt_backup_last_status gauge
owt_backup_last_status $STATUS
# HELP owt_backup_last_attempt_timestamp_seconds Time of the last start.
# TYPE owt_backup_last_attempt_timestamp_seconds gauge
owt_backup_last_attempt_timestamp_seconds $STARTED_AT
# HELP owt_backup_last_success_timestamp_seconds Time of the last successful S3 upload.
# TYPE owt_backup_last_success_timestamp_seconds gauge
owt_backup_last_success_timestamp_seconds $LAST_SUCCESS
# HELP owt_backup_last_duration_seconds Duration of the last run.
# TYPE owt_backup_last_duration_seconds gauge
owt_backup_last_duration_seconds $(( now - STARTED_AT ))
# HELP owt_backup_last_bytes Total size of objects uploaded in the last run.
# TYPE owt_backup_last_bytes gauge
owt_backup_last_bytes $BYTES_TOTAL
EOF
	mv "$PROM_FILE.tmp" "$PROM_FILE"
}

cleanup() {
	local rc=$?
	write_metrics
	rm -rf "${TMP:?}"/*
	return $rc
}
trap cleanup EXIT

echo "=== $(date -u +%FT%TZ) backup start ($HOSTTAG)"
docker exec "$CONTAINER" pg_dumpall -U "$PGSUPER" --globals-only | gzip -6 > "$TMP/globals-$STAMP.sql.gz"
for db in $(docker exec "$CONTAINER" psql -U "$PGSUPER" -d postgres -Atc \
    "select datname from pg_database where not datistemplate and datallowconn and datname <> 'postgres' order by 1"); do
  docker exec "$CONTAINER" pg_dump -U "$PGSUPER" -Fc -Z6 -d "$db" > "$TMP/$db-$STAMP.dump"
  # a truncated dump is worse than no dump: refuse to upload one pg_restore cannot read
  docker run --rm -v "$TMP:/b" postgres:18.1 pg_restore -l "/b/$db-$STAMP.dump" > /dev/null
  echo "dumped $db -> $(du -h "$TMP/$db-$STAMP.dump" | cut -f1)"
done
BYTES_TOTAL="$(du -sb "$TMP" | cut -f1)"
docker run --rm --env-file "$ENVFILE" -v "$TMP:/data" rclone/rclone \
  copy /data "tw:$BUCKET/pg/$HOSTTAG/$DAY/" --s3-no-check-bucket --stats-one-line
docker run --rm --env-file "$ENVFILE" rclone/rclone \
  delete "tw:$BUCKET/pg/$HOSTTAG/" --min-age "$RETENTION" --rmdirs --stats-one-line
LAST_SUCCESS="$(date +%s)"
STATUS=1
echo "=== $(date -u +%FT%TZ) backup ok ($HOSTTAG)"
