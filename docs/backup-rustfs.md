# Backups: Postgres dumps to Timeweb S3

What actually runs on production (Moscow, `msk-1-vm-15za`):

```
30 4 * * * /root/pg-backup/backup.sh >> /var/log/pg-backup.log 2>&1
```

The same script lives in the repo as `ops/backup/backup.sh`. Nothing deploys it:
the host copy is updated by hand (`scp ops/backup/backup.sh Moscow:/root/pg-backup/`),
so after editing it here, copy it there — a stale host copy is invisible until an
alert it was supposed to feed never fires. Durability is Timeweb's own S3
replication — the job does not wait on a second site.

Not PITR. Granularity is one day.

---

## Layout

```
s3://$BUCKET/pg/<host>/<YYYY-MM-DD>/
  globals-<stamp>.sql.gz
  <db>-<stamp>.dump
```

`<host>` defaults to `moscow` (`HOSTTAG`). Every non-template, connectable database
except `postgres` is dumped (`pg_dump -Fc -Z6`). Cluster roles go in `globals-*.sql.gz`.

Each dump is checked with `pg_restore -l` before upload. Objects older than 30 days
under `pg/<host>/` are deleted (`rclone delete --min-age 30d`).

---

## Config

```bash
cp ops/backup/s3.env.example ops/backup/s3.env
chmod 600 ops/backup/s3.env
```

Keys match `/root/pg-backup/s3.env` on Moscow: `RCLONE_CONFIG_TW_*`, `BUCKET`.
Endpoint: `https://s3.twcstorage.ru`, region `ru-1`.

---

## Run

```bash
make backup-run          # now
make backup-ls           # what's in the bucket
tail -n 50 /var/log/pg-backup.log
```

Prometheus (`monitoring/prometheus/rules/backup.yml`) watches
`owt_backup_last_success_timestamp_seconds` written by the script into
`/var/lib/node_exporter/textfile/owt_backup.prom`. No replica alert — S3 is
already replicated.

---

## Restore

```bash
set -a; . ops/backup/s3.env; set +a
mkdir -p /srv/restore
docker run --rm --env-file ops/backup/s3.env -v /srv/restore:/data rclone/rclone \
  copy "tw:$BUCKET/pg/moscow/<YYYY-MM-DD>/" /data

gunzip -c /srv/restore/globals-*.sql.gz | docker exec -i db_postgres psql -U system -d postgres
docker exec -e PGPASSWORD="$PGPASSWORD" db_postgres psql -U system -d postgres \
  -c 'CREATE DATABASE anak_restore'
docker exec -i db_postgres pg_restore -U system -d anak_restore --no-owner \
  < /srv/restore/anak_v5-*.dump
```

`anak_v5` is production. Do not restore the stale `anak_dev` dump.

---

## Failures

| Symptom | Where |
|---|---|
| `BackupMissing` | cron / `/var/log/pg-backup.log` |
| `BackupRunFailed` | same log; rclone credentials / `db_postgres` down |
| `pg_restore -l` failed | truncated dump (disk, interrupted `docker exec`) |
| `BackupDumpSuspiciouslySmall` | wrong database or empty dump |
