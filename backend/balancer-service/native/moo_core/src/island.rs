use rand::prelude::*;
use std::cmp::Ordering;
use std::collections::HashSet;

use crate::*;

pub(crate) struct IslandState {
    pub(crate) ctx: Context,
    pub(crate) rng: MooRng,
    pub(crate) pop: Vec<ArchiveEntry>,
    pub(crate) archive: Vec<ArchiveEntry>,
    pub(crate) archive_sigs: HashSet<u64>,
    pub(crate) cur_mut_rate: f64,
    pub(crate) hist_bal: Vec<f64>,
    pub(crate) hist_com: Vec<f64>,
    pub(crate) gens_without_archive_improvement: usize,
    pub(crate) completed_generations: usize,
    pub(crate) repair_diagnostics: RepairDiagnostics,
    pub(crate) stopped: bool,
}

pub(crate) fn environmental_select(
    comb: Vec<ArchiveEntry>,
    population_size: usize,
    parent_count: usize,
) -> (Vec<ArchiveEntry>, usize) {
    let c_objs: Vec<Objectives> = comb.iter().map(|entry| entry.obj).collect();
    let c_norm = normalize_objectives(&c_objs);
    let c_fronts = fast_non_dominated_sort(&c_norm);
    let mut nxt = Vec::with_capacity(population_size);
    let mut offspring_survived = 0usize;
    let track_survival = parent_count <= comb.len();

    for f in c_fronts {
        if nxt.len() + f.len() <= population_size {
            for &i in &f {
                if track_survival && i >= parent_count {
                    offspring_survived += 1;
                }
                nxt.push(comb[i].clone());
            }
        } else {
            let cd = crowding_distance(&f, &c_norm);
            let mut pairs: Vec<(usize, f64)> = f.iter().copied().zip(cd.into_iter()).collect();
            pairs.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(Ordering::Equal));
            let rem = population_size - nxt.len();
            for (i, _) in pairs.into_iter().take(rem) {
                if track_survival && i >= parent_count {
                    offspring_survived += 1;
                }
                nxt.push(comb[i].clone());
            }
            break;
        }
    }

    (nxt, offspring_survived)
}

pub(crate) fn best_front_progress(pop: &[ArchiveEntry]) -> (f64, f64) {
    let objs: Vec<Objectives> = pop.iter().map(|entry| entry.obj).collect();
    let norm = normalize_objectives(&objs);
    let fronts = fast_non_dominated_sort(&norm);
    let cur_b = fronts[0]
        .iter()
        .map(|&i| pop[i].obj.balance)
        .fold(f64::INFINITY, f64::min);
    let cur_c = fronts[0]
        .iter()
        .map(|&i| pop[i].obj.comfort)
        .fold(f64::INFINITY, f64::min);
    (cur_b, cur_c)
}

pub(crate) fn init_island_state(
    ctx: Context,
    island_seed: u64,
    island_index: usize,
) -> Result<IslandState, String> {
    let mut rng = MooRng::seed_from_u64(island_seed);
    let mut pop: Vec<ArchiveEntry> = Vec::new();
    let mut archive: Vec<ArchiveEntry> = Vec::new();
    let mut archive_sigs: HashSet<u64> = HashSet::new();
    let initial_mut_rate = ctx.config.mutation_rate;
    let start_stopped = ctx.config.generation_count == 0;

    // Жадные конструкции детерминированы и без диверсификации были бы
    // идентичны на всех островах. Остров 0 хранит «чистые» сиды; остальные
    // возмущают их своим RNG — стартовое разнообразие вместо четырёх копий.
    let greedy_count = ctx.config.greedy_seed_count.min(ctx.config.population_size);
    if greedy_count >= 1 {
        let mut sol = create_snake_draft_solution(&ctx);
        ensure_feasibility(&mut sol, &ctx, &mut rng);
        if solution_is_complete(&sol, &ctx) {
            let entry = ArchiveEntry::new(calculate_objectives(&sol, &ctx), sol);
            archive_update(&mut archive, &mut archive_sigs, entry.clone(), &ctx);
            pop.push(entry);
        }
    }
    if greedy_count >= 2 {
        let mut sol = create_comfort_greedy_solution(&ctx);
        if island_index > 0 {
            sol = mutate_random(&sol, &ctx, 1 + island_index % 3, &mut rng);
        }
        ensure_feasibility(&mut sol, &ctx, &mut rng);
        if solution_is_complete(&sol, &ctx) {
            let entry = ArchiveEntry::new(calculate_objectives(&sol, &ctx), sol);
            archive_update(&mut archive, &mut archive_sigs, entry.clone(), &ctx);
            pop.push(entry);
        }
    }
    if greedy_count >= 3 {
        let mut sol = create_snake_draft_solution(&ctx);
        strategy_fix_discomfort(&mut sol, &ctx);
        if island_index > 0 {
            sol = mutate_targeted(&sol, &ctx, &mut rng, 2);
        }
        ensure_feasibility(&mut sol, &ctx, &mut rng);
        if solution_is_complete(&sol, &ctx) {
            let entry = ArchiveEntry::new(calculate_objectives(&sol, &ctx), sol);
            archive_update(&mut archive, &mut archive_sigs, entry.clone(), &ctx);
            pop.push(entry);
        }
    }

    let mut attempts = 0;
    while pop.len() < ctx.config.population_size && attempts < ctx.config.population_size * 4 {
        let mut sol = create_random_solution(&ctx, &mut rng);
        ensure_feasibility(&mut sol, &ctx, &mut rng);
        attempts += 1;
        if !solution_is_complete(&sol, &ctx) {
            return Err("Incomplete initial solution".into());
        }
        let entry = ArchiveEntry::new(calculate_objectives(&sol, &ctx), sol);
        archive_update(&mut archive, &mut archive_sigs, entry.clone(), &ctx);
        pop.push(entry);
    }
    if pop.is_empty() {
        return Err("Failed to build population".into());
    }

    Ok(IslandState {
        ctx,
        rng,
        pop,
        archive,
        archive_sigs,
        cur_mut_rate: initial_mut_rate,
        hist_bal: Vec::new(),
        hist_com: Vec::new(),
        gens_without_archive_improvement: 0,
        completed_generations: 0,
        repair_diagnostics: RepairDiagnostics::default(),
        stopped: start_stopped,
    })
}

pub(crate) fn run_island_epoch(
    state: &mut IslandState,
    epoch_generations: usize,
) -> Result<(), String> {
    if state.stopped {
        return Ok(());
    }

    let remaining = state
        .ctx
        .config
        .generation_count
        .saturating_sub(state.completed_generations);
    let steps = remaining.min(epoch_generations.max(1));

    for _ in 0..steps {
        let objs: Vec<Objectives> = state.pop.iter().map(|entry| entry.obj).collect();
        let norm = normalize_objectives(&objs);
        let fronts = fast_non_dominated_sort(&norm);
        let mut ranks = vec![0; state.pop.len()];
        let mut dists = vec![0.0; state.pop.len()];
        for (r, f) in fronts.iter().enumerate() {
            let cd = crowding_distance(f, &norm);
            for (pos, &i) in f.iter().enumerate() {
                ranks[i] = r;
                dists[i] = cd[pos];
            }
        }

        let mut off = Vec::with_capacity(state.ctx.config.population_size);
        let kick_active = state.ctx.config.stagnation_kick_patience > 0
            && state.gens_without_archive_improvement >= state.ctx.config.stagnation_kick_patience;
        let effective_strength = if kick_active {
            state.ctx.config.mutation_strength.saturating_mul(3).max(2)
        } else {
            state.ctx.config.mutation_strength
        };
        let effective_rate = if kick_active {
            state.cur_mut_rate.max(0.8)
        } else {
            state.cur_mut_rate
        };
        let effective_crossover_rate = if kick_active {
            state.ctx.config.crossover_rate.max(0.9)
        } else {
            state.ctx.config.crossover_rate
        };
        let mut archive_improved = false;

        while off.len() < state.ctx.config.population_size {
            let p1_idx = tournament_pick(&ranks, &dists, &mut state.rng);
            let crossed =
                state.pop.len() >= 2 && state.rng.random::<f64>() < effective_crossover_rate;
            let mutated = state.rng.random::<f64>() < effective_rate;

            if !crossed && !mutated {
                off.push(state.pop[p1_idx].clone());
                continue;
            }

            let mut child_sol: Solution = if crossed {
                let mut p2_idx = tournament_pick(&ranks, &dists, &mut state.rng);
                let mut tries = 0;
                while p2_idx == p1_idx && state.pop.len() > 1 && tries < 8 {
                    p2_idx = tournament_pick(&ranks, &dists, &mut state.rng);
                    tries += 1;
                }
                // Team-preserving crossover включается только на малых
                // турнирах: абляция (10 сидов) показала выигрыш на 4 командах
                // (mmr_std 5.9→3.8, gap 66→39) и регресс на 12/40 командах —
                // при копировании половины команд из A вторая половина B
                // остаётся полупустой, и repair превращает скрещивание в
                // крупную мутацию, разрушающую сходимость.
                let team_share = if state.ctx.num_teams <= 6 {
                    state.ctx.config.team_crossover_share
                } else {
                    0.0
                };
                if state.rng.random::<f64>() < team_share {
                    crossover_team_preserving(
                        &state.pop[p1_idx].sol,
                        &state.pop[p2_idx].sol,
                        &state.ctx,
                        &mut state.rng,
                    )
                } else {
                    crossover_role_lines(
                        &state.pop[p1_idx].sol,
                        &state.pop[p2_idx].sol,
                        &state.ctx,
                        &mut state.rng,
                    )
                }
            } else {
                state.pop[p1_idx].sol.clone()
            };

            if mutated {
                child_sol =
                    mutate_targeted(&child_sol, &state.ctx, &mut state.rng, effective_strength);
            }

            // Если repair не нужен, ensure_feasibility лишь канонизирует порядок
            // внутри ростеров (набор (role, player) не меняется) — сигнатура
            // инвариантна к этому порядку, поэтому pre/post хэши можно не считать.
            let repair_need = analyze_repair_need(&child_sol, &state.ctx);
            let (changed_by_repair, child_sig) = if repair_need.needs_repair() {
                let pre_repair_sig = signature(&child_sol);
                ensure_feasibility(&mut child_sol, &state.ctx, &mut state.rng);
                let post_repair_sig = signature(&child_sol);
                (pre_repair_sig != post_repair_sig, post_repair_sig)
            } else {
                ensure_feasibility(&mut child_sol, &state.ctx, &mut state.rng);
                (false, signature(&child_sol))
            };
            state
                .repair_diagnostics
                .record_child(crossed, mutated, repair_need, changed_by_repair);
            let child_obj = calculate_objectives(&child_sol, &state.ctx);
            let child = ArchiveEntry {
                obj: child_obj,
                sol: child_sol,
                sig: child_sig,
            };
            if archive_update(
                &mut state.archive,
                &mut state.archive_sigs,
                child.clone(),
                &state.ctx,
            ) {
                archive_improved = true;
            }
            off.push(child);
        }

        if archive_improved {
            state.gens_without_archive_improvement = 0;
        } else {
            state.gens_without_archive_improvement += 1;
        }

        let elite_items =
            archive_select_elites(&state.archive, ARCHIVE_ELITE_COUNT.min(state.archive.len()));
        let parent_count = state.pop.len();
        let mut comb = std::mem::take(&mut state.pop);
        comb.extend(off);
        comb.extend(elite_items);
        let (nxt, offspring_survived) =
            environmental_select(comb, state.ctx.config.population_size, parent_count);
        state.pop = nxt;

        if state.ctx.config.mutation_rate_min < state.ctx.config.mutation_rate_max {
            let survival = offspring_survived as f64 / state.ctx.config.population_size as f64;
            let delta = (survival - 0.25) * 0.15;
            state.cur_mut_rate = (state.cur_mut_rate - delta)
                .max(state.ctx.config.mutation_rate_min)
                .min(state.ctx.config.mutation_rate_max);
        }

        state.completed_generations += 1;

        if state.ctx.config.convergence_patience > 0
            && state.completed_generations >= state.ctx.config.convergence_patience
        {
            let (cur_b, cur_c) = best_front_progress(&state.pop);
            state.hist_bal.push(cur_b);
            state.hist_com.push(cur_c);

            if state.hist_bal.len() > state.ctx.config.convergence_patience {
                let idx = state.hist_bal.len() - state.ctx.config.convergence_patience - 1;
                let imp_b = if state.hist_bal[idx] > 0.0 {
                    (state.hist_bal[idx] - cur_b) / state.hist_bal[idx]
                } else {
                    0.0
                };
                let imp_c = if state.hist_com[idx] > 0.0 {
                    (state.hist_com[idx] - cur_c) / state.hist_com[idx]
                } else {
                    0.0
                };
                if imp_b < state.ctx.config.convergence_epsilon
                    && imp_c < state.ctx.config.convergence_epsilon
                {
                    state.stopped = true;
                    break;
                }
            }
        }

        if state.completed_generations >= state.ctx.config.generation_count {
            state.stopped = true;
            break;
        }
    }

    Ok(())
}

pub(crate) fn inject_migrants(state: &mut IslandState, migrants: &[ArchiveEntry]) {
    if state.stopped || migrants.is_empty() {
        return;
    }

    for migrant in migrants {
        // Решение то же — переоцениваем только objectives локальными весами,
        // сигнатура переиспользуется из кэша.
        let local_obj = calculate_objectives(&migrant.sol, &state.ctx);
        let candidate = migrant.rescored(local_obj);
        archive_update(
            &mut state.archive,
            &mut state.archive_sigs,
            candidate,
            &state.ctx,
        );
    }
}

pub(crate) fn finalize_island_state(state: &mut IslandState) {
    for item in &state.pop {
        archive_update(
            &mut state.archive,
            &mut state.archive_sigs,
            item.clone(),
            &state.ctx,
        );
    }
}

/// Профиль острова — мультипликаторы для весов, определяющие "характер" поиска.
/// Гетерогенные острова расширяют Парето-фронт: каждый ищет в своей области
/// компромисса между balance и comfort, вместо 4 копий одной и той же скаляризации.
#[derive(Debug, Clone, Copy)]
pub(crate) struct IslandProfile {
    /// Множитель для всех balance-related весов (std, gap, role-line, tank).
    balance_scale: f64,
    /// Множитель для comfort-related весов (discomfort, sub-role collisions).
    comfort_scale: f64,
    /// Множитель для максимумов (max_team_gap, max_role_discomfort) —
    /// профиль "экстремальные хвосты", ищет решения без провалов.
    extreme_scale: f64,
}

pub(crate) fn default_island_profiles() -> [IslandProfile; 4] {
    [
        // 0: нейтральный — базовые веса
        IslandProfile {
            balance_scale: 1.0,
            comfort_scale: 1.0,
            extreme_scale: 1.0,
        },
        // 1: balance-heavy — жёсткая балансировка по MMR/gap, comfort полуоблегчён
        IslandProfile {
            balance_scale: 2.0,
            comfort_scale: 0.5,
            extreme_scale: 1.0,
        },
        // 2: comfort-heavy — максимум комфорта ролей
        IslandProfile {
            balance_scale: 0.5,
            comfort_scale: 2.0,
            extreme_scale: 1.0,
        },
        // 3: extreme tails — штраф за выбросы усилен
        IslandProfile {
            balance_scale: 1.0,
            comfort_scale: 1.0,
            extreme_scale: 2.5,
        },
    ]
}

/// Возвращает копию контекста с весами, скорректированными под профиль острова.
pub(crate) fn ctx_with_profile(base: &Context, profile: IslandProfile) -> Context {
    let mut c = base.clone();
    let cfg = &mut c.config;
    // balance-related
    cfg.average_mmr_balance_weight *= profile.balance_scale;
    cfg.team_total_balance_weight *= profile.balance_scale;
    cfg.tank_gap_weight *= profile.balance_scale;
    cfg.tank_std_weight *= profile.balance_scale;
    cfg.effective_total_std_weight *= profile.balance_scale;
    cfg.intra_team_std_weight *= profile.balance_scale;
    cfg.role_line_balance_weight *= profile.balance_scale;
    cfg.internal_role_spread_weight *= profile.balance_scale;
    // comfort-related
    cfg.role_discomfort_weight *= profile.comfort_scale;
    cfg.sub_role_collision_weight *= profile.comfort_scale;
    // extreme tails
    cfg.max_team_gap_weight *= profile.extreme_scale;
    cfg.max_role_discomfort_weight *= profile.extreme_scale;
    cfg.team_max_pain_weight *= profile.extreme_scale;
    c
}
