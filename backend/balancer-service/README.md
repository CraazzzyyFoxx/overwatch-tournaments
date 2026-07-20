# Balancer Service

Team balancing service that uses a genetic algorithm to produce optimal, fair team distributions for
tournaments. Balancing runs as an asynchronous job; live progress is broadcast over the realtime
WebSocket topic `tournament:{id}:balancer` (served by the Go gateway).

- **Transport:** headless FastStream worker behind the Go gateway (no HTTP server). External clients
  call `/api/balancer/*`; the gateway translates each route to its `rpc.balancer.*` queue.
- **Entry point:** `serve.py` (typed `rpc.balancer.*` RPC + async job queue + draft clock)
- **Balancing engine:** the heavy solve runs in a native Rust/PyO3 crate `moo_core`, an NSGA-style
  multi-objective genetic algorithm over two objectives — `balance` vs `comfort` — with a
  `rank_comfort_tilt` knob that ranks result variants between the two. It is offloaded from the event
  loop via `asyncio.to_thread`. Balancing is **Linux-only**: `moo_core` is built with maturin (see
  `native/moo_core`).

See [`../../docs/architecture.md`](../../docs/architecture.md) for the platform overview.

## Features

- **Genetic Algorithm**: evolutionary optimization to balance teams
- **Multi-criteria optimization**: balances MMR, role preferences, and team variance
- **Captain assignment**: optional captain selection based on highest ratings
- **Flexible configuration**: customizable weights and algorithm parameters

## Authorization

All balancer endpoints (except `/health`) require an access token and are restricted to users with one
of these roles:

- `admin`
- `tournament_organizer`

## API Endpoints

### POST `/api/balancer/jobs`

Create an async balancing job and return a `job_id` immediately.

**Request (multipart/form-data):**
- `file` (required): JSON file with player data
- `config` (optional): JSON string with balancing overrides

```bash
curl -X POST "http://localhost/api/balancer/jobs" \
  -H "Authorization: Bearer <access_token>" \
  -F "file=@players.json" \
  -F 'config={"MASK":{"Tank":1,"Damage":2,"Support":2},"POPULATION_SIZE":200,"GENERATIONS":750,"USE_CAPTAINS":true}'
```

### POST `/api/balancer/balance`

Backward-compatible alias for `POST /api/balancer/jobs`. Returns an async `job_id`.

### GET `/api/balancer/jobs/{job_id}`

Get job status (`queued`, `running`, `succeeded`, `failed`) with the current stage and progress.

### GET `/api/balancer/jobs/{job_id}/result`

Get the final balancing result when the job is complete.

### GET `/api/balancer/jobs/{job_id}/stream` — not available

Live status updates and worker logs are delivered over the realtime WebSocket topic
`tournament:{id}:balancer`, relayed by the Go gateway.

### GET `/api/balancer/config`

Returns runtime defaults, allowed limits, and available presets for frontend forms.

## Configuration

All balancing parameters can be customized by passing a `config` object in your API request. The service
supports:

- **Role configuration**: custom role masks and mappings
- **Genetic algorithm**: population size, generations, elitism, mutation parameters
- **Cost weights**: MMR difference, discomfort, variance, and max-discomfort weights
- **Strategy**: captain assignment and display settings

The authoritative list of runtime defaults, allowed limits, and presets is returned by the
`GET /api/balancer/config` endpoint, which the frontend uses to build its forms.

### Quick configuration examples

**Default configuration:**
```json
{
  "MASK": {"Tank": 1, "Damage": 2, "Support": 2},
  "POPULATION_SIZE": 200,
  "GENERATIONS": 750,
  "ELITISM_RATE": 0.2,
  "MUTATION_RATE": 0.4,
  "MUTATION_STRENGTH": 3,
  "MMR_DIFF_WEIGHT": 3.0,
  "DISCOMFORT_WEIGHT": 0.25,
  "INTRA_TEAM_VAR_WEIGHT": 0.8,
  "MAX_DISCOMFORT_WEIGHT": 1.0,
  "USE_CAPTAINS": true
}
```

**Competitive tournament (prioritize fair matches):**
```json
{
  "POPULATION_SIZE": 300,
  "GENERATIONS": 1000,
  "MMR_DIFF_WEIGHT": 5.0,
  "USE_CAPTAINS": true
}
```

**Quick balancing (faster, lower quality):**
```json
{
  "POPULATION_SIZE": 50,
  "GENERATIONS": 200,
  "USE_CAPTAINS": false
}
```

## Running

Balancer runs as a single headless FastStream worker behind the Go gateway. It serves the
typed `rpc.balancer.*` API (config / admin / draft / jobs), consumes the balancer job queue,
and runs the draft clock.

```bash
# Worker (typed RPC + async jobs + draft clock)
faststream run serve:app
```

External traffic reaches the worker as `/api/balancer/*` through the gateway, which
translates each route to its `rpc.balancer.*` queue.

## Configuration & environment

See `backend/env/balancer.env`, which inherits `backend/env/common.env`.
