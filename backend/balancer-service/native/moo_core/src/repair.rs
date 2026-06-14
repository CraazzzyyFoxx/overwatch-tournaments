use rand::prelude::*;

use crate::*;

/// Приоритет размещения игрока в роли. Выше — лучше.
/// Капитан в seed_role при use_captains имеет абсолютный приоритет.
#[inline]
pub(crate) fn placement_score(ctx: &Context, p: usize, r: usize) -> i32 {
    let pl = &ctx.players[p];
    let mut s = 0;
    if ctx.config.use_captains && pl.is_captain && pl.seed_role == r {
        s += 1000;
    }
    if pl.can_play[r] {
        s += 100;
    }
    if pl.seed_role == r {
        s += 20;
    }
    // Штраф за явно неигровую роль — чтобы попасть туда только в крайнем случае
    if !pl.can_play[r] && pl.seed_role != r {
        s -= 50;
    }
    s
}

pub(crate) fn analyze_repair_need(sol: &Solution, ctx: &Context) -> RepairNeed {
    let p_count = ctx.players.len();
    let num_roles = ctx.roles.len();
    if p_count == 0 || num_roles == 0 || ctx.num_teams == 0 {
        return RepairNeed::default();
    }

    let mut need = RepairNeed::default();
    let mut seen = vec![0usize; p_count];

    for team in sol {
        for (r, roster) in team.roster.iter().enumerate() {
            let cap = ctx.capacities.get(r).copied().unwrap_or(0);
            if roster.len() > cap {
                need.over_capacity_assignments += roster.len() - cap;
            }
            for &p in roster {
                if p < p_count {
                    seen[p] += 1;
                } else {
                    need.invalid_player_refs += 1;
                }
            }
        }
    }

    need.duplicate_assignments = seen.iter().map(|&count| count.saturating_sub(1)).sum();
    need.missing_players = seen.iter().filter(|&&count| count == 0).count();

    if ctx.config.use_captains {
        for (p, player) in ctx.players.iter().enumerate() {
            let Some(team_idx) = player.captain_team else {
                continue;
            };
            let role_idx = player.seed_role;
            let locked_present = sol
                .get(team_idx)
                .and_then(|team| team.roster.get(role_idx))
                .is_some_and(|roster| roster.contains(&p));
            if !locked_present {
                need.captain_lock_conflicts += 1;
            }
        }
    }

    need
}

/// Гарантирует инвариант "один капитан на команду, зафиксированная роль":
/// для каждого капитана с `captain_team = Some(t0)` и `seed_role = r0` —
/// капитан сидит именно в `sol[t0].roster[r0]`. Если он найден где-то ещё,
/// он перемещается на нужное место; если на целевом слоте нет места,
/// вытесняется один не-капитан (он попадает туда, откуда пришёл капитан).
/// Вызывается перед `ensure_feasibility` после crossover/мутаций.
pub(crate) fn enforce_captain_locks(sol: &mut Solution, ctx: &Context) {
    if !ctx.config.use_captains {
        return;
    }
    let num_roles = ctx.roles.len();
    if num_roles == 0 || ctx.num_teams == 0 {
        return;
    }

    for p in 0..ctx.players.len() {
        let pl = &ctx.players[p];
        let Some(t0) = pl.captain_team else {
            continue;
        };
        let r0 = pl.seed_role;
        if t0 >= sol.len() || r0 >= num_roles {
            continue;
        }

        // Уже на своём месте?
        if sol[t0].roster[r0].contains(&p) {
            // Заодно убираем возможные дубликаты капитана из чужих слотов
            for t in 0..sol.len() {
                for r in 0..num_roles {
                    if t == t0 && r == r0 {
                        continue;
                    }
                    sol[t].roster[r].retain(|&x| x != p);
                }
            }
            continue;
        }

        // Находим текущее положение капитана (если он вообще в solution).
        let mut current: Option<(usize, usize, usize)> = None;
        'outer: for t in 0..sol.len() {
            for r in 0..num_roles {
                if let Some(pos) = sol[t].roster[r].iter().position(|&x| x == p) {
                    current = Some((t, r, pos));
                    break 'outer;
                }
            }
        }
        // Удаляем все вхождения капитана из ростеров (на случай дубликатов)
        for t in 0..sol.len() {
            for r in 0..num_roles {
                sol[t].roster[r].retain(|&x| x != p);
            }
        }

        // Помещаем капитана на целевой слот. Если слот переполнен, вытесняем
        // одного не-капитана (предпочтительно последнего) в позицию, откуда пришёл капитан.
        let cap = ctx.capacities[r0];
        if sol[t0].roster[r0].len() < cap {
            sol[t0].roster[r0].push(p);
        } else {
            // Ищем не-капитана в целевом слоте для вытеснения
            let evict_idx = sol[t0].roster[r0].iter().rposition(|&x| {
                !ctx.players[x].is_captain || ctx.players[x].captain_team != Some(t0)
            });
            if let Some(idx) = evict_idx {
                let evicted = sol[t0].roster[r0].remove(idx);
                sol[t0].roster[r0].push(p);
                // Пытаемся пристроить вытесненного обратно в исходное место капитана
                if let Some((ct, cr, _)) = current {
                    if (ct != t0 || cr != r0) && sol[ct].roster[cr].len() < ctx.capacities[cr] {
                        sol[ct].roster[cr].push(evicted);
                        continue;
                    }
                }
                // Иначе ensure_feasibility подберёт ему новое место
                let _ = evicted;
            } else {
                // Все в слоте — локированные капитаны (конфликт конфигурации);
                // форсим капитана, капасити восстановит ensure_feasibility
                sol[t0].roster[r0].push(p);
            }
        }
    }
}

/// Восстанавливает решение после мутаций/crossover:
/// 1) очищает out-of-range и выходы за capacity;
/// 2) из дубликатов оставляет копию в лучшей позиции по `placement_score`
///    (т.е. в играбельной роли / seed_role, сохраняя капитанство);
/// 3) каждый пропущенный игрок добавляется в пул РОВНО ОДИН РАЗ;
/// 4) пул матчится к вакансиям жадно с предпочтением `can_play` → `seed_role` →
///    форс-назначение только если подходящих не осталось.
pub(crate) fn ensure_feasibility(sol: &mut Solution, ctx: &Context, rng: &mut MooRng) {
    let p_count = ctx.players.len();
    let num_roles = ctx.roles.len();
    if p_count == 0 || num_roles == 0 || ctx.num_teams == 0 {
        return;
    }

    // --- Шаг 0: отбрасываем невалидные индексы ДО captain-локов ---
    // enforce_captain_locks обращается к ctx.players[x] и паниковал бы на
    // out-of-range индексе; для валидных решений это no-op.
    for team in sol.iter_mut() {
        for roster in team.roster.iter_mut() {
            roster.retain(|&p| p < p_count);
        }
    }

    // Затем вкорачиваем капитанов на их зафиксированные места —
    // это гарантирует инвариант "один капитан на команду, фиксированная роль".
    enforce_captain_locks(sol, ctx);

    // --- Шаг 1: обрезка превышений capacity ---
    for t in 0..ctx.num_teams {
        for r in 0..num_roles {
            let cap = ctx.capacities[r];
            let roster = &mut sol[t].roster[r];
            if cap == 0 {
                roster.clear();
                continue;
            }
            if roster.len() > cap {
                if ctx.config.use_captains {
                    // Приоритет: залоченный капитан этого (t,r) → любой капитан → остальные
                    roster.sort_by(|&a, &b| {
                        let la =
                            ctx.players[a].captain_team == Some(t) && ctx.players[a].seed_role == r;
                        let lb =
                            ctx.players[b].captain_team == Some(t) && ctx.players[b].seed_role == r;
                        let ca = ctx.players[a].is_captain;
                        let cb = ctx.players[b].is_captain;
                        lb.cmp(&la).then(cb.cmp(&ca))
                    });
                }
                roster.truncate(cap);
            }
        }
    }

    // --- Шаг 2: собрать все позиции по каждому игроку ---
    let mut positions: Vec<Vec<(usize, usize)>> = vec![Vec::new(); p_count];
    for t in 0..ctx.num_teams {
        for r in 0..num_roles {
            for &p in &sol[t].roster[r] {
                positions[p].push((t, r));
            }
        }
    }

    // --- Шаг 3: выбрать лучшую "keep"-позицию для каждого игрока; остальные очищаем ---
    // Сначала очищаем весь roster, затем кладём только keep-позиции.
    for t in 0..ctx.num_teams {
        for r in 0..num_roles {
            sol[t].roster[r].clear();
        }
    }

    let mut missing: Vec<usize> = Vec::new();
    for p in 0..p_count {
        let locs = &positions[p];
        if locs.is_empty() {
            missing.push(p);
            continue;
        }
        // Выбираем позицию с максимальным placement_score; при равенстве —
        // предпочитаем меньший team_id, затем меньший role_idx (детерминизм).
        // Для залоченного капитана приоритетна его зафиксированная (captain_team, seed_role).
        let pl = &ctx.players[p];
        let locked = if ctx.config.use_captains && pl.is_captain {
            pl.captain_team.map(|t| (t, pl.seed_role))
        } else {
            None
        };
        let best = if let Some((lt, lr)) = locked {
            locs.iter()
                .copied()
                .find(|&(t, r)| t == lt && r == lr)
                .or_else(|| {
                    locs.iter().copied().max_by(|&(ta, ra), &(tb, rb)| {
                        let sa = placement_score(ctx, p, ra);
                        let sb = placement_score(ctx, p, rb);
                        sa.cmp(&sb)
                            .then_with(|| tb.cmp(&ta))
                            .then_with(|| rb.cmp(&ra))
                    })
                })
        } else {
            locs.iter().copied().max_by(|&(ta, ra), &(tb, rb)| {
                let sa = placement_score(ctx, p, ra);
                let sb = placement_score(ctx, p, rb);
                sa.cmp(&sb)
                    .then_with(|| tb.cmp(&ta))
                    .then_with(|| rb.cmp(&ra))
            })
        };
        if let Some((t, r)) = best {
            // Capacity уже была обрезана в шаге 1, но из-за клиринга ростеров
            // сейчас capacity гарантированно доступна (игрок попадает первым в пустой слот).
            if sol[t].roster[r].len() < ctx.capacities[r] {
                sol[t].roster[r].push(p);
            } else {
                // Теоретически недостижимо после шага 1, но подстрахуемся
                missing.push(p);
            }
        }
    }

    // --- Шаг 4: собрать вакансии ---
    let mut vacancies: Vec<(usize, usize)> = Vec::new();
    for t in 0..ctx.num_teams {
        for r in 0..num_roles {
            let cap = ctx.capacities[r];
            let have = sol[t].roster[r].len();
            for _ in have..cap {
                vacancies.push((t, r));
            }
        }
    }

    // --- Шаг 5: жадный матчинг pool → vacancies ---
    // Стратегия: перебираем вакансии в случайном порядке (для разнообразия),
    // но для каждой ищем кандидата с лучшим placement_score по всему пулу.
    missing.shuffle(rng);
    vacancies.shuffle(rng);

    let mut pool_alive: Vec<bool> = vec![true; missing.len()];

    // Пред-матчинг залоченных капитанов: если капитан оказался в пуле,
    // обязательно закрываем им его зафиксированный (captain_team, seed_role).
    if ctx.config.use_captains {
        for i in 0..missing.len() {
            if !pool_alive[i] {
                continue;
            }
            let p = missing[i];
            let pl = &ctx.players[p];
            if !pl.is_captain {
                continue;
            }
            let Some(lt) = pl.captain_team else {
                continue;
            };
            let lr = pl.seed_role;
            if let Some(vi) = vacancies.iter().position(|&(t, r)| t == lt && r == lr) {
                let (t, r) = vacancies.remove(vi);
                sol[t].roster[r].push(p);
                pool_alive[i] = false;
            } else if sol[lt].roster[lr].len() < ctx.capacities[lr] {
                // Форс: целевая вакансия не была собрана (редкий случай), но место есть
                sol[lt].roster[lr].push(p);
                pool_alive[i] = false;
            }
        }
    }

    for (t, r) in vacancies.iter().copied() {
        let mut best_idx: Option<usize> = None;
        let mut best_score = i32::MIN;
        for (i, &p) in missing.iter().enumerate() {
            if !pool_alive[i] {
                continue;
            }
            let s = placement_score(ctx, p, r);
            if s > best_score {
                best_score = s;
                best_idx = Some(i);
            }
        }
        if let Some(i) = best_idx {
            pool_alive[i] = false;
            sol[t].roster[r].push(missing[i]);
        }
        // Если пул пуст — вакансия остаётся (не должно происходить при
        // валидных входных данных, т.к. sum(capacities) == num_players).
    }
}
