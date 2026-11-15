# faststream 0.7: RPC queues become durable: release note

**What changed.** b35214469 moved the backend from faststream 0.6.7 to 0.7.8. In 0.7 a `RabbitQueue` declared without
`durable=` (every `@broker.subscriber("rpc.…")` given a bare name) defaults to `durable=True`; 0.6 declared it
non-durable. RabbitMQ refuses to redeclare an existing queue with different arguments, so on a broker that still
holds the 0.6 queues every service dies at startup:

```
ChannelPreconditionFailed: PRECONDITION_FAILED - inequivalent arg 'durable' for queue 'rpc.balancer.draft.chat_settings'
in vhost '/': received 'true' but current is 'false'
```

Affected: every service with RPC subscribers (`app`, `stats`, `identity`, `balancer`, `analytics`, `stream`,
`tournament`, `discord`). The container healthcheck only runs `python -c "sys.exit(0)"`, so between restarts compose
can report a crash-looping service as healthy; `docker compose up --wait` still fails on the first one it catches
unhealthy.

**Deploy.** Before (or right after) `make prod-up` with the new images, delete the non-durable `rpc.*` queues; the
services recreate them durable on the next start. `ops/deploy/remote-deploy.sh` does this right before `prod-up`, so a
tag deploy needs nothing by hand; the commands below are for a manual `make prod-up`. On home dev (2026-11-14) all 747
such queues were `rpc.*` and held 0 messages; on production (Moscow, v2.10.9, 2026-11-15) 644 `rpc.*` with 0 messages,
plus two exclusive `amq.*` reply queues that stay. Requests in flight during the swap fail on the gateway's RPC
deadline.

```sh
C="docker compose -f docker-compose.production.yml"
# check: every non-durable queue is rpc.* and empty
$C exec rabbitmq rabbitmqctl list_queues -q name durable messages | awk '$2=="false"'
$C exec rabbitmq sh -c '
A="rabbitmqadmin -u $RABBITMQ_DEFAULT_USER -p $RABBITMQ_DEFAULT_PASS"
$A -f tsv -q list queues name durable | awk -F"\t" "\$2==\"False\" && \$1 ~ /^rpc\\./ {print \$1}" |
  while read -r q; do $A -q delete queue name="$q" >/dev/null; done'
```

Crash-looping services pick the new queues up on their next restart (`restart: always`); rerun `make prod-up` if
compose already gave up waiting.
