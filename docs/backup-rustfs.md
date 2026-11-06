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

## Restore a dump locally

`make backup-restore-local DUMP=<object path>` copies one dump (`make backup-ls` lists them, e.g.
`pg/moscow/2026-11-05/owt-20261105-043000.dump`) and restores it into a throwaway `postgres:18` container
`owt-restore-pg` on `127.0.0.1:55433`, database `owt_restore` (dropped and re-created on every run; the dev
`postgres:16` cannot read pg_dump 18 files). It needs `ops/backup/s3.env` and prints the `POSTGRES_*` environment to use
against it.

League-merge rehearsal (spec 15.6; the merge itself is `backend/scripts/league_merge.py`, runbook in its docstring):

```bash
make backup-restore-local DUMP=<newest app-database dump>
cd backend
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55433 POSTGRES_DB=owt_restore POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres
uv run alembic upgrade flowP6_01_deferrable_fks
uv run python -m scripts.league_merge plan --output /tmp/league_merge.json
# fill every league's "aggregate" (placeholder for a rehearsal: {"unit":"players","score":{"preset":"stage_points"},"mode":"sum_all"})
uv run python -m scripts.league_merge apply --file /tmp/league_merge.json --dry-run
uv run python -m scripts.league_merge apply --file /tmp/league_merge.json
uv run alembic upgrade head      # flowP6_02 passes its guard once no league row remains
```

Stop on any `MergeError` or deferred-constraint `IntegrityError` and record the league and the message. Do not run
`grant` locally: no stats-service drains the outbox, so the queued evaluation runs never finish.

---

## Failures

| Symptom | Where |
|---|---|
| `BackupMissing` | cron / `/var/log/pg-backup.log` |
| `BackupRunFailed` | same log; rclone credentials / Postgres container down |
| `pg_restore -l` failed | truncated dump (disk, interrupted `docker exec`) |
| `BackupDumpSuspiciouslySmall` | wrong database or empty dump |
