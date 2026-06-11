use rand::prelude::*;
use std::cmp::Ordering;

use crate::*;

pub(crate) fn swap_players(
    sol: &mut Solution,
    ta: usize,
    ra: usize,
    sa: usize,
    tb: usize,
    rb: usize,
    sb: usize,
) {
    let pa = sol[ta].roster[ra][sa];
    let pb = sol[tb].roster[rb][sb];
    sol[ta].roster[ra][sa] = pb;
    sol[tb].roster[rb][sb] = pa;
}

pub(crate) fn strategy_robin_hood(sol: &mut Solution, ctx: &Context, rng: &mut MooRng) -> bool {
    if sol.len() < 2 || ctx.roles.is_empty() {
        return false;
    }
    let totals: Vec<f64> = sol
        .iter()
        .map(|t| calculate_team_stats(ctx, t).total_rating)
        .collect();
    let max_i = totals
        .iter()
        .enumerate()
        .max_by(|a, b| a.1.partial_cmp(b.1).unwrap_or(Ordering::Equal))
        .map(|(i, _)| i)
        .unwrap_or(0);
    let min_i = totals
        .iter()
        .enumerate()
        .min_by(|a, b| a.1.partial_cmp(b.1).unwrap_or(Ordering::Equal))
        .map(|(i, _)| i)
        .unwrap_or(0);
    if max_i == min_i {
        return false;
    }
    let orig_gap = totals[max_i] - totals[min_i];
    if orig_gap <= 0.0 {
        return false;
    }

    let mut roles = (0..ctx.roles.len()).collect::<Vec<_>>();
    roles.shuffle(rng);
    for r in roles {
        let rich = sol[max_i].roster[r].clone();
        let poor = sol[min_i].roster[r].clone();
        if rich.is_empty() || poor.is_empty() {
            continue;
        }
        let mut r_ord = (0..rich.len()).collect::<Vec<_>>();
        r_ord.sort_by(|&a, &b| {
            ctx.players[rich[b]].ratings[r].cmp(&ctx.players[rich[a]].ratings[r])
        });
        let mut p_ord = (0..poor.len()).collect::<Vec<_>>();
        p_ord.sort_by_key(|&i| ctx.players[poor[i]].ratings[r]);

        for &ri in &r_ord {
            let strong = rich[ri];
            if ctx.config.use_captains && ctx.players[strong].is_captain {
                continue;
            }
            for &pi in &p_ord {
                let weak = poor[pi];
                if ctx.config.use_captains && ctx.players[weak].is_captain {
                    continue;
                }
                let delta = ctx.players[strong].ratings[r] - ctx.players[weak].ratings[r];
                if delta <= 0 {
                    continue;
                }
                let nr = totals[max_i] - delta as f64;
                let np = totals[min_i] + delta as f64;
                let mut ng = (nr - np).abs();
                for (k, &v) in totals.iter().enumerate() {
                    if k == max_i || k == min_i {
                        continue;
                    }
                    ng = ng.max(v.max(nr).max(np) - v.min(nr).min(np));
                }
                if ng >= orig_gap {
                    continue;
                }
                swap_players(sol, max_i, r, ri, min_i, r, pi);
                return true;
            }
        }
    }
    false
}

pub(crate) fn strategy_fix_discomfort(sol: &mut Solution, ctx: &Context) -> bool {
    if sol.len() < 2 {
        return false;
    }
    let mut painful = Vec::new();
    for (ti, t) in sol.iter().enumerate() {
        for (ri, r) in t.roster.iter().enumerate() {
            for (si, &pi) in r.iter().enumerate() {
                if ctx.config.use_captains && ctx.players[pi].is_captain {
                    continue;
                }
                let d = ctx.players[pi].discomfort[ri];
                if d >= 1000 {
                    painful.push((ti, ri, si, d));
                }
            }
        }
    }
    painful.sort_by(|a, b| b.3.cmp(&a.3));
    for &(sti, sri, ssi, sd) in &painful {
        let sp = sol[sti].roster[sri][ssi];
        let sp_data = &ctx.players[sp];
        for dti in 0..sol.len() {
            if dti == sti {
                continue;
            }
            for dri in 0..ctx.roles.len() {
                for dsi in 0..sol[dti].roster[dri].len() {
                    let dp = sol[dti].roster[dri][dsi];
                    let dp_data = &ctx.players[dp];
                    if ctx.config.use_captains && dp_data.is_captain {
                        continue;
                    }
                    if dp_data.first_preference != Some(sri) {
                        continue;
                    }
                    if !sp_data.can_play[dri] {
                        continue;
                    }
                    let nd = sp_data.discomfort[dri] + dp_data.discomfort[sri];
                    let od = sd + dp_data.discomfort[dri];
                    if nd >= od {
                        continue;
                    }
                    swap_players(sol, sti, sri, ssi, dti, dri, dsi);
                    return true;
                }
            }
        }
    }
    false
}

pub(crate) fn strategy_role_rebalance(sol: &mut Solution, ctx: &Context) -> bool {
    if sol.len() < 2 || ctx.roles.is_empty() {
        return false;
    }
    let mut best_r = None;
    let mut best_sd = 0.0;
    let mut best_avgs = Vec::new();
    for r in 0..ctx.roles.len() {
        let mut avgs = Vec::new();
        for (ti, t) in sol.iter().enumerate() {
            if t.roster[r].is_empty() {
                continue;
            }
            let s: f64 = t.roster[r]
                .iter()
                .map(|&p| ctx.players[p].ratings[r] as f64)
                .sum();
            avgs.push((ti, s / t.roster[r].len() as f64));
        }
        if avgs.len() < 2 {
            continue;
        }
        let vals: Vec<f64> = avgs.iter().map(|&(_, v)| v).collect();
        let m = vals.iter().sum::<f64>() / vals.len() as f64;
        let v = vals.iter().map(|x| (x - m).powi(2)).sum::<f64>() / (vals.len() as f64 - 1.0);
        let sd = if v > 0.0 { v.sqrt() } else { 0.0 };
        if sd > best_sd {
            best_sd = sd;
            best_r = Some(r);
            best_avgs = avgs;
        }
    }
    let Some(br) = best_r else {
        return false;
    };
    if best_sd <= 0.0 {
        return false;
    }
    best_avgs.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(Ordering::Equal));
    let wi = best_avgs[0].0;
    let si = best_avgs[best_avgs.len() - 1].0;
    if wi == si {
        return false;
    }
    let sr = sol[si].roster[br].clone();
    let wr = sol[wi].roster[br].clone();
    if sr.is_empty() || wr.is_empty() {
        return false;
    }
    let mut s_ord = (0..sr.len()).collect::<Vec<_>>();
    s_ord.sort_by_key(|&i| ctx.players[sr[i]].ratings[br]);
    let mut w_ord = (0..wr.len()).collect::<Vec<_>>();
    w_ord.sort_by(|&a, &b| ctx.players[wr[b]].ratings[br].cmp(&ctx.players[wr[a]].ratings[br]));
    for &si_slot in &s_ord {
        let sp = sr[si_slot];
        if ctx.config.use_captains && ctx.players[sp].is_captain {
            continue;
        }
        for &wi_slot in &w_ord {
            let wp = wr[wi_slot];
            if ctx.config.use_captains && ctx.players[wp].is_captain {
                continue;
            }
            let d = ctx.players[wp].ratings[br] - ctx.players[sp].ratings[br];
            if d >= 0 {
                continue;
            }
            let mut navgs = Vec::new();
            for &(ti, avg) in &best_avgs {
                if ti == si {
                    navgs.push(avg + d as f64 / sol[ti].roster[br].len() as f64);
                } else if ti == wi {
                    navgs.push(avg - d as f64 / sol[ti].roster[br].len() as f64);
                } else {
                    navgs.push(avg);
                }
            }
            let m = navgs.iter().sum::<f64>() / navgs.len() as f64;
            let v = navgs.iter().map(|x| (x - m).powi(2)).sum::<f64>() / (navgs.len() as f64 - 1.0);
            let nsd = if v > 0.0 { v.sqrt() } else { 0.0 };
            if nsd >= best_sd {
                continue;
            }
            swap_players(sol, si, br, si_slot, wi, br, wi_slot);
            return true;
        }
    }
    false
}

pub(crate) fn mutate_random(
    sol: &Solution,
    ctx: &Context,
    str: usize,
    rng: &mut MooRng,
) -> Solution {
    let mut nxt = sol.clone();
    if ctx.roles.is_empty() || nxt.len() < 2 {
        return nxt;
    }
    for _ in 0..str.max(1) {
        if rng.random::<f64>() < 0.8 {
            let r = rng.random_range(0..ctx.roles.len());
            let mut ts = (0..nxt.len()).collect::<Vec<_>>();
            ts.shuffle(rng);
            let a = ts[0];
            let b = ts[1];
            if nxt[a].roster[r].is_empty() || nxt[b].roster[r].is_empty() {
                continue;
            }
            let sa = rng.random_range(0..nxt[a].roster[r].len());
            let sb = rng.random_range(0..nxt[b].roster[r].len());
            if ctx.config.use_captains
                && (ctx.players[nxt[a].roster[r][sa]].is_captain
                    || ctx.players[nxt[b].roster[r][sb]].is_captain)
            {
                continue;
            }
            swap_players(&mut nxt, a, r, sa, b, r, sb);
        } else if ctx.roles.len() >= 2 {
            let t = rng.random_range(0..nxt.len());
            let mut rs = (0..ctx.roles.len()).collect::<Vec<_>>();
            rs.shuffle(rng);
            let r1 = rs[0];
            let r2 = rs[1];
            if nxt[t].roster[r1].is_empty() || nxt[t].roster[r2].is_empty() {
                continue;
            }
            let c1: Vec<usize> = nxt[t].roster[r1]
                .iter()
                .enumerate()
                .filter_map(|(i, &p)| {
                    if ctx.players[p].can_play[r2]
                        && (!ctx.config.use_captains || !ctx.players[p].is_captain)
                    {
                        Some(i)
                    } else {
                        None
                    }
                })
                .collect();
            let c2: Vec<usize> = nxt[t].roster[r2]
                .iter()
                .enumerate()
                .filter_map(|(i, &p)| {
                    if ctx.players[p].can_play[r1]
                        && (!ctx.config.use_captains || !ctx.players[p].is_captain)
                    {
                        Some(i)
                    } else {
                        None
                    }
                })
                .collect();
            if c1.is_empty() || c2.is_empty() {
                continue;
            }
            swap_players(
                &mut nxt,
                t,
                r1,
                c1[rng.random_range(0..c1.len())],
                t,
                r2,
                c2[rng.random_range(0..c2.len())],
            );
        }
    }
    nxt
}

/// Role-line uniform crossover. Для каждой роли независимо с вероятностью 0.5
/// берём её "линию" (игроков этой роли во всех командах) у родителя A, иначе у B.
/// Team.id наследуется от A для детерминизма сигнатуры. Возможные дубли игроков
/// (если игрок назначен на разные роли у A и B) и недостающие игроки (если он
/// был только в неотобранной линии) исправляются последующим `ensure_feasibility`.
///
/// Captain-инвариант сохраняется автоматически: каждая роль-линия у каждого
/// родителя уже feasible, значит капитан этой роли попадёт в ребёнка целиком
/// из выбранного источника (A или B). Конфликт капитана (один и тот же
/// капитан в двух ролях одновременно) невозможен, т.к. у родителей игрок
/// занимает ровно одну позицию.
pub(crate) fn crossover_role_lines(
    a: &Solution,
    b: &Solution,
    ctx: &Context,
    rng: &mut MooRng,
) -> Solution {
    let mut child = create_empty_solution(ctx);
    if ctx.roles.is_empty() || a.len() != b.len() || a.len() != child.len() {
        // Фолбэк: клонируем A, если структуры не совпадают
        return a.clone();
    }
    // Гарантируем, что хотя бы одна роль от каждого родителя — иначе ребёнок
    // идентичен одному из них и crossover вырождается в клон.
    let num_roles = ctx.roles.len();
    let mut from_a: Vec<bool> = (0..num_roles).map(|_| rng.random::<bool>()).collect();
    if num_roles >= 2 {
        if from_a.iter().all(|&v| v) {
            let flip = rng.random_range(0..num_roles);
            from_a[flip] = false;
        } else if from_a.iter().all(|&v| !v) {
            let flip = rng.random_range(0..num_roles);
            from_a[flip] = true;
        }
    }
    for r in 0..num_roles {
        let source = if from_a[r] { a } else { b };
        for t in 0..child.len() {
            child[t].roster[r] = source[t].roster[r].clone();
        }
    }
    child
}

/// Team-preserving crossover (в духе grouping GA, Falkenauer): половина команд
/// копируется из родителя A ЦЕЛИКОМ, остальные слоты заполняются назначениями
/// из B (пропуская уже занятых игроков), хвост достраивает ensure_feasibility.
/// Сохраняет командные «строительные блоки» — именно команды, а не роль-линии,
/// оценивает objective; role-line crossover их систематически разрушает.
///
/// Captain-инвариант: команды из A несут своих капитанов как есть; капитан
/// B-стороны сидит у B на своём (captain_team, seed_role) и копируется, если
/// не занят A-командой — иначе его вернёт enforce_captain_locks при repair.
pub(crate) fn crossover_team_preserving(
    a: &Solution,
    b: &Solution,
    ctx: &Context,
    rng: &mut MooRng,
) -> Solution {
    let mut child = create_empty_solution(ctx);
    if ctx.roles.is_empty() || a.len() != b.len() || a.len() != child.len() || a.len() < 2 {
        return a.clone();
    }
    let num_teams = a.len();
    let mut team_order: Vec<usize> = (0..num_teams).collect();
    team_order.shuffle(rng);
    let keep_count = (num_teams / 2).max(1);

    let mut used = vec![false; ctx.players.len()];
    for &t in &team_order[..keep_count] {
        for (r, roster) in a[t].roster.iter().enumerate() {
            for &p in roster {
                if p < used.len() {
                    used[p] = true;
                }
            }
            child[t].roster[r] = roster.clone();
        }
    }
    for &t in &team_order[keep_count..] {
        for (r, roster) in b[t].roster.iter().enumerate() {
            for &p in roster {
                if p < used.len() && !used[p] {
                    used[p] = true;
                    child[t].roster[r].push(p);
                }
            }
        }
    }
    child
}

pub(crate) fn mutate_targeted(
    sol: &Solution,
    ctx: &Context,
    rng: &mut MooRng,
    strength: usize,
) -> Solution {
    let mut nxt = sol.clone();
    for _ in 0..strength.max(1) {
        let roll = rng.random::<f64>();
        let applied = if roll < 0.35 {
            strategy_robin_hood(&mut nxt, ctx, rng)
        } else if roll < 0.70 {
            strategy_fix_discomfort(&mut nxt, ctx)
        } else if roll < 0.90 {
            strategy_role_rebalance(&mut nxt, ctx)
        } else {
            false
        };
        if applied {
            continue;
        }
        nxt = mutate_random(&nxt, ctx, 1, rng);
    }
    nxt
}

/// Бинарный турнир без аллокации: два случайных индекса (без повтора при n>1),
/// победитель по rank, tie-break по crowding distance. Поведение 1:1 с прежней версией.
pub(crate) fn tournament_pick(ranks: &[usize], dists: &[f64], rng: &mut MooRng) -> usize {
    let n = ranks.len();
    debug_assert!(n > 0);
    let a = rng.random_range(0..n);
    let mut b = rng.random_range(0..n);
    while n > 1 && b == a {
        b = rng.random_range(0..n);
    }
    if ranks[a] < ranks[b] {
        return a;
    }
    if ranks[b] < ranks[a] {
        return b;
    }
    if dists[a] > dists[b] {
        return a;
    }
    if dists[b] > dists[a] {
        return b;
    }
    a
}
