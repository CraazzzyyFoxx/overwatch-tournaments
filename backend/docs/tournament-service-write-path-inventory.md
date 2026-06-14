# Tournament Service Write-Path Inventory

Date: 2026-04-26

Source commands:

```bash
rg -n "models\.(Tournament|Stage|StageItem|Encounter|EncounterLink|Team|TeamPlayer|Standing|BalancerRegistration|BalancerRegistrationForm|BalancerRegistrationRole|BalancerRegistrationStatus|BalancerRegistrationGoogleSheet)" backend
rg -n "insert|update|delete|commit\(|session\.add|session\.delete|bulk_create_from_balancer|has_logs\s*=" backend/parser-service backend/app-service backend/balancer-service
```

## Target ownership

| Table / model | Current writer(s) | Target owner | Action |
| --- | --- | --- | --- |
| `tournament.tournament` / `Tournament` | `parser-service/src/services/admin/tournament.py`, `parser-service/src/services/tournament/service.py`; registration flows in `app-service` read it for validation; balancer reads it for auth/config | `tournament-service` | Move parser admin writes; keep app/balancer reads until route cutover |
| `tournament.group` / `TournamentGroup` | `parser-service/src/services/tournament/service.py`, `parser-service/src/services/challonge/sync.py` | `tournament-service` | Move legacy compatibility writes; delete later with Phase G |
| `tournament.stage`, `tournament.stage_item`, `tournament.stage_item_input` | `parser-service/src/services/admin/stage.py`, `parser-service/src/services/tournament/service.py`, `parser-service/src/services/challonge/sync.py` | `tournament-service` | Move admin/stage and Challonge writers |
| `tournament.encounter` / `Encounter` | `parser-service/src/services/admin/encounter.py`, `parser-service/src/services/encounter/captain.py`, `parser-service/src/services/challonge/sync.py`, `parser-service/src/services/encounter/service.py`, `parser-service/src/services/match_logs/flows.py` (`has_logs`) | `tournament-service` | Move result/admin/Challonge writes; keep parser match-log linkage only as event/setter until PR-11 |
| `tournament.encounter_link` / `EncounterLink` | `parser-service/src/services/admin/stage.py`, `parser-service/src/services/challonge/sync.py`, `shared/services/bracket/advancement.py` | `tournament-service` plus shared bracket engine | Move callers; keep shared code as low-level engine only |
| `tournament.standing` / `Standing` | `parser-service/src/services/standings/service.py`, `parser-service/src/services/admin/standing.py`; `balancer-service/src/services/admin/balancer.py` deletes standings during temporary team export | `tournament-service` | Move recalculation/admin writes; document balancer delete as temporary team-export exception |
| `tournament.team`, `tournament.player`, player sub-role models | `parser-service/src/services/admin/team.py`, `parser-service/src/services/team/service.py`, `parser-service/src/services/team/flows.py`, `parser-service/src/services/challonge/sync.py`; `balancer-service/src/services/team.py` and `balancer-service/src/services/admin/balancer.py` write exported teams | `tournament-service` | Move parser writers; document balancer team-export write exception until `TeamsBalancedEvent` flow exists |
| `balancer.registration` / `BalancerRegistration` | `app-service/src/services/registration/service.py`, `app-service/src/routes/registration.py`, `balancer-service/src/services/admin/balancer_registration.py` | `tournament-service` | Move public submit and admin registration facet together |
| `balancer.registration_role` / `BalancerRegistrationRole` | `app-service/src/routes/registration.py`, `balancer-service/src/services/admin/balancer_registration.py` | `tournament-service` | Move with registration service |
| `balancer.registration_form` / `BalancerRegistrationForm` | `balancer-service/src/application/admin/registration_use_cases.py`; app-service reads form for public submit | `tournament-service` | Move admin form writes; keep public reads through tournament route after cutover |
| `balancer.registration_status` / `BalancerRegistrationStatus` | `balancer-service/src/services/admin/registration_status.py`, status reads from `balancer-service/src/services/admin/balancer_registration.py` | `tournament-service` | Move status catalog and helpers with registration facet |
| `balancer.registration_google_sheet_feed`, `balancer.registration_google_sheet_binding` | `balancer-service/src/services/admin/balancer_registration.py`, scheduler in `balancer-service/serve.py` | `tournament-service` / `tournament-worker` | Move sheet config/sync/export; disable balancer scheduler before route switch |

## Known exceptions to carry forward

- `balancer-service/src/services/team.py::bulk_create_from_balancer` and `balancer-service/src/services/admin/balancer.py::export_balance` currently write `Team`, `Player`, and delete linked `Standing` rows. This is the documented temporary team-export exception.
- `parser-service/src/services/match_logs/flows.py` still marks `Encounter.has_logs`. D2 narrows this to a locked setter; PR-11 should replace it with an event into `tournament-service`.
- `shared/services/bracket/advancement.py` writes through ORM objects passed by callers. It remains a low-level bracket engine; request handlers must move to a service-local domain wrapper before extraction.
