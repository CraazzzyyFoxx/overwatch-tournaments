from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from faststream.rabbit.fastapi import RabbitRouter
from loguru import logger

from src import models
from src.core.auth import get_current_active_user
from src.core.config import config
from src.schemas import BalanceJobResult, BalancerConfigResponse, CreateJobResponse, JobStatusResponse
from src.services.balancer import jobs

router = APIRouter(
    prefix="",
    tags=["Balancer"],
)
task_router = RabbitRouter(config.rabbitmq_url, logger=logger)

PLAYER_DATA_FILE_DESCRIPTION = """
JSON file with a top-level `players` object. Object keys are stable player IDs
used only for this balance request.

Supported default team roles are `Tank`, `Damage`, and `Support` from the
default `role_mask` `{ "Tank": 1, "Damage": 2, "Support": 2 }`.

Input role keys may use:

- `tank`
- `damage` or `dps`
- `support`
- any role name that exactly matches `config_overrides.role_mask`
- any role name that case-insensitively matches a `role_mask` key

Each player object must include:

- `identity.name`: display name.
- `identity.isFullFlex`: `true` when all active playable roles should have no
  role discomfort penalty for this player.
- `stats.classes`: role map keyed by supported role aliases or custom
  `role_mask` names.

Each active role entry supports:

- `isActive`: include this role for the player.
- `rank`: numeric role rating. Roles with `rank <= 0` are ignored.
- `priority`: lower values are preferred first. `0` is the highest preference.
  Ties are sorted by role name to keep results deterministic.
- `subtype`: optional role subtype used by subtype-collision balancing.

Players with no active role that matches the current `role_mask` are ignored.
Unknown role keys are ignored. `role_mask` entries with a count of `0` or lower
are ignored.

Example:

```json
{
  "players": {
    "player-1": {
      "identity": {
        "name": "Ana Main",
        "isFullFlex": false
      },
      "stats": {
        "classes": {
          "tank": { "isActive": true, "rank": 2600, "priority": 2 },
          "damage": { "isActive": true, "rank": 2750, "priority": 1, "subtype": "hitscan" },
          "support": { "isActive": true, "rank": 2900, "priority": 0 }
        }
      }
    }
  }
}
```
"""

CONFIG_OVERRIDES_DESCRIPTION = """
Optional JSON object with balancing options. For API-key requests the default
policy allows only `algorithm`, `role_mask`, `population_size`,
`generation_count`, `use_captains`, and `max_result_variants`; `algorithm` is
limited to `moo`.
"""

BALANCER_BEHAVIOR_DESCRIPTION = """
Balancer behavior summary for API consumers:

1. Role mask defines the team format. The default is 5v5 Overwatch:
   1 Tank, 2 Damage, 2 Support. Team size is the sum of positive values in
   `role_mask`.
2. The service loads only valid players: each valid player must have at least
   one active role matching the role mask and a positive `rank`.
3. Valid player count must divide evenly by team size. The quotient is the
   number of teams. Example: 20 valid players with the default 5-player mask
   creates 4 teams.
4. For every role, the pool must contain enough role-capable players:
   `role_mask[role] * number_of_teams`.
5. Before optimization, a feasible player-to-role assignment is found. It
   respects role capacities and player preferences. Captains are pinned first
   when `use_captains` is enabled.
6. `priority` controls role preference. Lower numbers are better: `0` is the
   player's preferred role, `1` is next, then `2`, and so on.
7. Role discomfort is derived from preference order. For non-flex players,
   first preference costs `0`, second costs `100`, third costs `200`, etc.
   Roles a player can play but did not prefer cost `1000`; unavailable roles
   cost `5000`. With `isFullFlex: true`, all playable roles cost `0`.
8. When `use_captains` is enabled, the service marks one captain per team.
   Captains are the highest-rated players by their first preferred role, with
   player ID as a deterministic tie breaker. Each captain is pinned to the
   first playable active role in their preference list.
9. Ratings are linearly normalized to the internal ceiling `3500` before the
   optimizer runs and restored in the response. This keeps gap penalties stable
   across datasets with different rating scales.
10. The `moo` solver returns up to `max_result_variants` Pareto variants. The
    score balances team total rating spread, strongest-vs-weakest team gap,
    average MMR spread, role discomfort, in-team spread, role-line strength,
    internal role spread, and subtype collisions.
11. `subtype` is optional. If two or more players on the same team and same
    role share the same non-empty subtype, each pair adds a collision penalty
    controlled by `sub_role_collision_weight`.
12. Jobs are asynchronous. Create a job, poll `/jobs/{job_id}`, then read
    `/jobs/{job_id}/result` after status becomes `succeeded`.
13. API keys are workspace-scoped. They can create and read only jobs created
    by the same key in the same workspace.
"""

CREATE_JOB_DESCRIPTION = f"""
Create an asynchronous balancer job from an uploaded players JSON file.

{PLAYER_DATA_FILE_DESCRIPTION}

{BALANCER_BEHAVIOR_DESCRIPTION}

The request must be `multipart/form-data`:

- `player_data_file`: players JSON file.
- `config_overrides`: optional JSON object string.
- query parameter `workspace_id`: workspace that owns the API key.
"""


@router.post(
    "/jobs",
    response_model=CreateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create balancer job",
    description=CREATE_JOB_DESCRIPTION,
)
async def create_balancer_job(
    player_data_file: UploadFile = File(..., description=PLAYER_DATA_FILE_DESCRIPTION),
    config_overrides: str | None = Form(None, description=CONFIG_OVERRIDES_DESCRIPTION),
    workspace_id: int = Query(..., description="Workspace context for authorization"),
    user: models.AuthUser = Depends(get_current_active_user),
) -> CreateJobResponse:
    try:
        return await jobs.create_job(
            uploaded_file=player_data_file,
            raw_config=config_overrides,
            workspace_id=workspace_id,
            user=user,
            broker=task_router.broker,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/jobs/{job_id}", response_model=JobStatusResponse, status_code=status.HTTP_200_OK)
async def get_balancer_job_status(
    job_id: str,
    user: models.AuthUser = Depends(get_current_active_user),
) -> JobStatusResponse:
    return await jobs.get_job_status(job_id=job_id, user=user)


@router.get("/jobs/{job_id}/result", response_model=BalanceJobResult, status_code=status.HTTP_200_OK)
async def get_balancer_job_result(
    job_id: str,
    user: models.AuthUser = Depends(get_current_active_user),
) -> BalanceJobResult:
    return await jobs.get_job_result(job_id=job_id, user=user)


@router.get("/jobs/{job_id}/stream", status_code=status.HTTP_200_OK)
async def stream_balancer_job_events(
    request: Request,
    job_id: str,
    after_event_id: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    user: models.AuthUser = Depends(get_current_active_user),
) -> StreamingResponse:
    event_generator = await jobs.stream_job_events(
        request=request,
        job_id=job_id,
        after_event_id=after_event_id,
        last_event_id=last_event_id,
        user=user,
    )
    return StreamingResponse(
        event_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/config", response_model=BalancerConfigResponse, status_code=status.HTTP_200_OK)
async def get_balancer_config() -> dict:
    return jobs.get_config()
