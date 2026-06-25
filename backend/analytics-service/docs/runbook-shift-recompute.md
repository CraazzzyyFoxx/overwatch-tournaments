# Runbook: пересчёт сигнала сдвига дивизиона (team-result + гибрид)

Финальная методика (после разворота merit-рерайта):
- **Points** — накопленный team W/L (не менялся; по данным — самый сильный предиктор реального перехода).
- **Linear** — чисто team-result (`map_diff` + `placement_score`).
- **OpenSkill + ML** — team-доминантный костяк (`shift_w_team`·Linear-team + `shift_w_os`·OpenSkill-mu) **плюс аддитивный, зажатый индивидуальный скилл** (Performance v2 `local_zscore` vs та же роль + соседний дивизион). Сила/потолок инд-члена **рангозависимы**: линейно затухают по канонич. номеру дивизиона (1=верх … 40=низ) — мало у потолка (тот же +N там — редкий, шумный, упёртый в кэп claim), полно внизу. NNLS-фита нет.
- **smurf-флаг** дополнительно ловит сильного аутлайера по когорте (`local_zscore ≥ SMURF_STRONG_LOCAL_Z`) при любом ранге.
- **Сетка дивизионов = сигнал, округлённый к ближайшему дивизиону** (без мёртвой зоны (−1,1)) → отображение согласовано с сигналом.

## env-кнобы (`backend/env/analytics.env`)
| env | что | когда применяется |
|---|---|---|
| `LINEAR_SHIFT_SCALE` (6.25) | масштаб team-result Linear | read-time → пересчитать v1 |
| `SHIFT_W_TEAM` (0.7), `SHIFT_W_OS` (0.3) | веса костяка v2 | снапшот при train → retrain shift |
| `SHIFT_INDIV_SCALE_TOP` (0.2), `SHIFT_INDIV_SCALE_BOTTOM` (0.8) | сила инд-скилла у потолка / у низа (ramp по дивизиону) | снапшот при train → retrain shift |
| `SHIFT_INDIV_CLAMP_TOP` (0.75), `SHIFT_INDIV_CLAMP_BOTTOM` (2.0) | потолок инд-члена у верха / у низа | снапшот при train → retrain shift |
| `SMURF_STRONG_LOCAL_Z` (1.5) | порог сильного аутлайера для флага | read при infer → backfill anomalies |
| `STANDINGS_PROB_SHARPENING` (1.5) | разброс предсказанных мест | снапшот при train standings |

## Пересчёт на prod-хосте (в tmux)
```bash
COMPOSE="docker compose -f docker-compose.production.yml"
LATEST=73   # max tournament id

# 0) доставить код и пересобрать образ (exec гоняет то, что в образе!)
$COMPOSE build analytics analytics-worker && $COMPOSE up -d analytics analytics-worker
$COMPOSE exec analytics-worker python -c \
 "import src.services.ml.models.shift_v2 as m; print('OK' if hasattr(m,'INDIV_MOD_SCALE_TOP') else 'OLD IMAGE')"

# 1a) (нужно для инд-скилла и smurf-флага) материализовать Performance v2 по истории
$COMPOSE exec analytics-worker python -m src.services.ml.cli backfill --from 1 --to $LATEST --models performance

# 1b) переобучить shift v2 (снапшот весов из env) и пересчитать
$COMPOSE exec analytics-worker python -m src.services.ml.cli train --cutoff $LATEST --models shift
$COMPOSE exec analytics-worker python -m src.services.ml.cli backfill --from 1 --to $LATEST
#   ^ backfill (без --models) обновит shift + player_anomalies (smurf) + match_quality + standings + performance

# 2) v1 Linear/Points + сетка дивизионов — compute-джоб по турнирам (v1 recalc + v2 infer вместе)
#    через API (право analytics.update), на каждый нужный tournament_id:
curl -X POST https://<api-host>/v2/jobs -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" -d "{\"kind\":\"compute\",\"tournament_id\":$LATEST}"
#    (или штатной кнопкой пересчёта в админке; джобы сериализуются — по одному на воркспейс)
```

## Тюнинг
Сила/потолок инд-скилла (рангозависимо) / порог флага — через env (`SHIFT_INDIV_SCALE_TOP|BOTTOM`/`SHIFT_INDIV_CLAMP_TOP|BOTTOM`/`SMURF_STRONG_LOCAL_Z`), затем `train --models shift` (для весов) + backfill. `LINEAR_SHIFT_SCALE` — только пересчёт v1 (compute-джоб), без retrain.

## Верификация (read-only, с лаптопа)
```bash
cd backend/analytics-service && uv run python scripts/diagnose_performance_coverage.py
```
- ad-hoc SQL Spearman(shift@T, realised@T+1): **Linear ≈ 0.37** (как Points), OpenSkill+ML — team-доминантный с инд-вариацией, без схлопывания;
- спот-чек UI: 1 место → вверх; сильный аутлайер по скиллу **двигается и помечается** (smurf) при любом ранге; **сетка дивизионов совпадает со знаком/величиной сигнала**; ручные сдвиги админов на месте.

## Безопасность / откат
- Ручной сдвиг (`AnalyticsPlayer.shift`, поле админки) пересчёт **не трогает** — только `change_shift`.
- Откат модели: прежний активный артефакт пометить `is_active=true` (новый деактивировать) + повторить backfill.
- Откат кода — git-revert ветки + пересборка образа.
```
