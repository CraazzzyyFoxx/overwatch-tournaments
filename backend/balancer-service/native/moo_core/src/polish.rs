use crate::*;

/// Принять ход, если он не ухудшает ни одну цель (с допуском EPS) и строго
/// улучшает хотя бы одну — чистый ε-Парето спуск. Прежняя "латеральная"
/// скалярная ветка была достижима только в полосе суммарного улучшения
/// (EPS, 2·EPS) — численный шум, а не заявленные ходы вдоль фронта.
#[inline]
pub(crate) fn accept_move(old: &Objectives, new: &Objectives) -> bool {
    const EPS: f64 = 1e-6;
    let pareto_ok = new.balance <= old.balance + EPS && new.comfort <= old.comfort + EPS;
    pareto_ok && (new.balance < old.balance - EPS || new.comfort < old.comfort - EPS)
}

/// Все допустимые раскладки набора игроков по ролям одной команды:
/// соблюдаются capacity, can_play и лок капитана (captain_team == team_idx
/// сидит строго в seed_role). Для маски 1/2/2 и 5 игроков — не более 30
/// вариантов; порядок игроков внутри роли следует порядку members
/// (детерминизм).
pub(crate) fn enumerate_role_assignments(
    ctx: &Context,
    team_idx: usize,
    members: &[usize],
) -> Vec<Vec<Vec<usize>>> {
    fn backtrack(
        ctx: &Context,
        team_idx: usize,
        members: &[usize],
        pos: usize,
        roster: &mut Vec<Vec<usize>>,
        results: &mut Vec<Vec<Vec<usize>>>,
    ) {
        if pos == members.len() {
            results.push(roster.clone());
            return;
        }
        let p = members[pos];
        let pl = &ctx.players[p];
        let locked_role = if ctx.config.use_captains && pl.captain_team == Some(team_idx) {
            Some(pl.seed_role)
        } else {
            None
        };
        for r in 0..ctx.roles.len() {
            if roster[r].len() >= ctx.capacities[r] {
                continue;
            }
            if !pl.can_play[r] {
                continue;
            }
            if let Some(locked) = locked_role {
                if r != locked {
                    continue;
                }
            }
            roster[r].push(p);
            backtrack(ctx, team_idx, members, pos + 1, roster, results);
            roster[r].pop();
        }
    }

    let mut results = Vec::new();
    let mut roster: Vec<Vec<usize>> = vec![Vec::new(); ctx.roles.len()];
    backtrack(ctx, team_idx, members, 0, &mut roster, &mut results);
    results
}

/// Расширенный локальный поиск:
/// 1) same-role swap между командами;
/// 2) точный перебор ролевых раскладок внутри команды (≤30 вариантов на
///    маске 1/2/2 — внутрикомандная раскладка ролей становится точно
///    оптимальной при фиксированном составе);
/// 3) cross-role swap между разными командами.
/// Идёт до фиксированной точки (с лимитом `max_passes` как safety-net).
///
/// Горячий путь: на reject статы затронутых команд ВОССТАНАВЛИВАЮТСЯ из
/// сохранённых копий (а не пересчитываются), objectives считаются через
/// переиспользуемый scratch.
pub(crate) fn polish_pareto(sol: &Solution, ctx: &Context, max_passes: usize) -> Solution {
    let mut cur = sol.clone();
    if ctx.roles.is_empty() || cur.len() < 2 {
        return cur;
    }
    let mut stats: Vec<TeamStats> = cur.iter().map(|t| calculate_team_stats(ctx, t)).collect();
    let mut scratch = ObjectiveScratch::default();
    let mut best_obj = calculate_objectives_with_scratch(&stats, ctx, &mut scratch);

    let is_captain = |p: usize| ctx.config.use_captains && ctx.players[p].is_captain;

    for _ in 0..max_passes {
        let mut improved = false;

        // (1) same-role swap между парами команд
        'same_role: for i in 0..cur.len() {
            for j in (i + 1)..cur.len() {
                for r in 0..ctx.roles.len() {
                    let li = cur[i].roster[r].len();
                    let lj = cur[j].roster[r].len();
                    if li == 0 || lj == 0 {
                        continue;
                    }
                    for a in 0..li {
                        let pa = cur[i].roster[r][a];
                        if is_captain(pa) || !ctx.players[pa].can_play[r] {
                            continue;
                        }
                        for b in 0..lj {
                            let pb = cur[j].roster[r][b];
                            if is_captain(pb) || !ctx.players[pb].can_play[r] {
                                continue;
                            }
                            if ctx.players[pa].ratings[r] == ctx.players[pb].ratings[r]
                                && ctx.players[pa].discomfort[r] == ctx.players[pb].discomfort[r]
                                && ctx.players[pa].subclasses[r] == ctx.players[pb].subclasses[r]
                            {
                                continue;
                            }

                            let saved_i = stats[i].clone();
                            let saved_j = stats[j].clone();
                            swap_players(&mut cur, i, r, a, j, r, b);
                            stats[i] = calculate_team_stats(ctx, &cur[i]);
                            stats[j] = calculate_team_stats(ctx, &cur[j]);
                            let nw = calculate_objectives_with_scratch(&stats, ctx, &mut scratch);
                            if accept_move(&best_obj, &nw) {
                                best_obj = nw;
                                improved = true;
                                break 'same_role;
                            }
                            swap_players(&mut cur, i, r, a, j, r, b);
                            stats[i] = saved_i;
                            stats[j] = saved_j;
                        }
                    }
                }
            }
        }
        if improved {
            continue;
        }

        // (2) точный перебор ролевых раскладок внутри команды: для маски
        // 1/2/2 это ≤30 вариантов на команду — строго поглощает одиночные
        // intra-team свопы, включая 3-циклы, недостижимые попарными обменами.
        'exact_roles: for t in 0..cur.len() {
            let mut members: Vec<usize> = Vec::new();
            for roster in &cur[t].roster {
                members.extend_from_slice(roster);
            }
            // Комбинаторная защита от экзотических масок: 8 игроков × 3 роли
            // ещё дёшево, дальше перебор растёт факториально.
            if members.len() > 8 {
                continue;
            }
            for assignment in enumerate_role_assignments(ctx, t, &members) {
                if assignment == cur[t].roster {
                    continue;
                }
                let saved_roster = std::mem::replace(&mut cur[t].roster, assignment);
                let saved_t = stats[t].clone();
                stats[t] = calculate_team_stats(ctx, &cur[t]);
                let nw = calculate_objectives_with_scratch(&stats, ctx, &mut scratch);
                if accept_move(&best_obj, &nw) {
                    best_obj = nw;
                    improved = true;
                    break 'exact_roles;
                }
                cur[t].roster = saved_roster;
                stats[t] = saved_t;
            }
        }
        if improved {
            continue;
        }

        // (3) cross-role swap между разными командами
        'cross_team: for i in 0..cur.len() {
            for j in 0..cur.len() {
                if i == j {
                    continue;
                }
                for r1 in 0..ctx.roles.len() {
                    for r2 in 0..ctx.roles.len() {
                        if r1 == r2 {
                            continue;
                        }
                        let l1 = cur[i].roster[r1].len();
                        let l2 = cur[j].roster[r2].len();
                        if l1 == 0 || l2 == 0 {
                            continue;
                        }
                        for a in 0..l1 {
                            let pa = cur[i].roster[r1][a];
                            if is_captain(pa) || !ctx.players[pa].can_play[r2] {
                                continue;
                            }
                            for b in 0..l2 {
                                let pb = cur[j].roster[r2][b];
                                if is_captain(pb) || !ctx.players[pb].can_play[r1] {
                                    continue;
                                }
                                let saved_i = stats[i].clone();
                                let saved_j = stats[j].clone();
                                swap_players(&mut cur, i, r1, a, j, r2, b);
                                stats[i] = calculate_team_stats(ctx, &cur[i]);
                                stats[j] = calculate_team_stats(ctx, &cur[j]);
                                let nw =
                                    calculate_objectives_with_scratch(&stats, ctx, &mut scratch);
                                if accept_move(&best_obj, &nw) {
                                    best_obj = nw;
                                    improved = true;
                                    break 'cross_team;
                                }
                                swap_players(&mut cur, i, r1, a, j, r2, b);
                                stats[i] = saved_i;
                                stats[j] = saved_j;
                            }
                        }
                    }
                }
            }
        }
        if !improved {
            break;
        }
    }
    cur
}
