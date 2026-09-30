# Backups: Postgres dumps to S3

`ops/backup/backup.sh` dumps every database to an S3 bucket through rclone. It is meant to
run once a day from cron on the production host, for example:

```
30 4 * * * <path>/ops/backup/backup.sh >> /var/log/pg-backup.log 2>&1
```

Not PITR. Granularity is one day. Durability is whatever the bucket provides; the job does
not replicate to a second site.

---

## Layout

```
s3://$BUCKET/pg/<host>/<YYYY-MM-DD>/
  globals-<stamp>.sql.gz
  <db>-<stamp>.dump
```

`<host>` is `HOSTTAG`. Every non-template, connectable database except `postgres` is dumped
(`pg_dump -Fc -Z6`). Cluster roles go in `globals-*.sql.gz`.

Each dump is checked with `pg_restore -l` before upload. Objects older than 30 days
under `pg/<host>/` are deleted (`rclone delete --min-age 30d`).

---

## Config

```bash
cp ops/backup/s3.env.example ops/backup/s3.env
chmod 600 ops/backup/s3.env
```

Keys: `RCLONE_CONFIG_TW_*` (the rclone remote `tw`), `BUCKET`. `CONTAINER`, `PGSUPER` and
`HOSTTAG` override the Postgres container, superuser and S3 prefix; for the bundled Postgres
see [`production-host.md`](./production-host.md).

---

## Run

```bash
make backup-run          # now
make backup-ls           # what's in the bucket
tail -n 50 /var/log/pg-backup.log
```

Prometheus (`monitoring/prometheus/rules/backup.yml`) watches
`owt_backup_last_success_timestamp_seconds` written by the script into
`/var/lib/node_exporter/textfile/owt_backup.prom`.

---

## Restore

```bash
set -a; . ops/backup/s3.env; set +a
mkdir -p /srv/restore
docker run --rm --env-file ops/backup/s3.env -v /srv/restore:/data rclone/rclone \
  copy "tw:$BUCKET/pg/<host>/<YYYY-MM-DD>/" /data

gunzip -c /srv/restore/globals-*.sql.gz | docker exec -i <container> psql -U <superuser> -d postgres
docker exec <container> psql -U <superuser> -d postgres -c 'CREATE DATABASE <db>_restore'
docker exec -i <container> pg_restore -U <superuser> -d <db>_restore --no-owner \
  < /srv/restore/<db>-*.dump
```

---

## Failures

| Symptom | Where |
|---|---|
| `BackupMissing` | cron / `/var/log/pg-backup.log` |
| `BackupRunFailed` | same log; rclone credentials / Postgres container down |
| `pg_restore -l` failed | truncated dump (disk, interrupted `docker exec`) |
| `BackupDumpSuspiciouslySmall` | wrong database or empty dump |
