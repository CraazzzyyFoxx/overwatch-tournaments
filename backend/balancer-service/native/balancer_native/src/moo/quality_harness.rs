use std::cmp::Ordering;

use super::*;

const SEEDS: [u64; 10] = [11, 22, 33, 44, 55, 66, 77, 88, 99, 1010];

#[derive(Debug, Clone, Default)]
struct VariantQuality {
    mmr_std: f64,
    total_gap: f64,
    tank_gap: f64,
    tank_adjacent_gap: f64,
    off_role_count: usize,
    pain_1000_count: usize,
    pain_5000_count: usize,
    subrole_collisions: i32,
    balance: f64,
    comfort: f64,
    signature: u64,
}

/// Фикстуры харнесса — овервотчевые (Tank/Damage/Support), и отчёт меряет
/// именно танк-линию: в движке роль безымянна, здесь её ищем по имени.
fn tank_role_idx(ctx: &Context) -> Option<usize> {
    ctx.roles.iter().position(|r| r == "Tank")
}

/// Веса танк-линии фикстуры — то, что абляции крутят вместе с конфигом.
fn tank_settings(ctx: &mut Context) -> &mut MooRoleSettings {
    let idx = tank_role_idx(ctx).expect("harness fixtures have a Tank role");
    &mut ctx.role_settings[idx]
}

pub(crate) fn rebuild_solution(ctx: &Context, variant: &VariantResponse<MooMetrics>) -> Solution {
    let by_uuid: HashMap<&str, usize> = ctx
        .players
        .iter()
        .enumerate()
        .map(|(i, p)| (p.uuid.as_str(), i))
        .collect();
    let role_idx: HashMap<&str, usize> = ctx
        .roles
        .iter()
        .enumerate()
        .map(|(i, r)| (r.as_str(), i))
        .collect();
    let mut sol = create_empty_solution(ctx);
    for (t, team) in variant.teams.iter().enumerate() {
        for (role, uuids) in &team.roster {
            let r = role_idx[role.as_str()];
            for uuid in uuids {
                sol[t].roster[r].push(by_uuid[uuid.as_str()]);
            }
        }
    }
    sol
}

fn quality_of_variant(ctx: &Context, variant: &VariantResponse<MooMetrics>) -> VariantQuality {
    let sol = rebuild_solution(ctx, variant);
    let stats: Vec<TeamStats> = sol.iter().map(|t| calculate_team_stats(ctx, t)).collect();

    let mut mmr_sum = 0.0;
    let mut mmr_sum2 = 0.0;
    let mut totals: Vec<f64> = Vec::new();
    let mut collisions = 0i32;
    for s in &stats {
        mmr_sum += s.mmr;
        mmr_sum2 += s.mmr * s.mmr;
        totals.push(s.total_rating);
        collisions += s.subrole_collisions;
    }
    let mmr_std = sample_stdev_from_sums(mmr_sum, mmr_sum2, stats.len());
    let total_gap = totals.iter().cloned().fold(f64::NEG_INFINITY, f64::max)
        - totals.iter().cloned().fold(f64::INFINITY, f64::min);

    let mut tank_ratings: Vec<f64> = Vec::new();
    if let Some(tank_idx) = tank_role_idx(ctx) {
        for team in &sol {
            let roster = &team.roster[tank_idx];
            if !roster.is_empty() {
                let sum: f64 = roster
                    .iter()
                    .map(|&p| ctx.players[p].ratings[tank_idx] as f64)
                    .sum();
                tank_ratings.push(sum / roster.len() as f64);
            }
        }
    }
    let (tank_gap, tank_adjacent_gap) = if tank_ratings.len() >= 2 {
        let mut sorted = tank_ratings.clone();
        sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(Ordering::Equal));
        let gap = sorted[sorted.len() - 1] - sorted[0];
        let adjacent = sorted
            .windows(2)
            .map(|w| w[1] - w[0])
            .fold(0.0f64, f64::max);
        (gap, adjacent)
    } else {
        (0.0, 0.0)
    };

    let mut off_role_count = 0usize;
    let mut pain_1000_count = 0usize;
    let mut pain_5000_count = 0usize;
    for team in &sol {
        for (r, roster) in team.roster.iter().enumerate() {
            for &p in roster {
                let pain = ctx.players[p].discomfort[r];
                if pain >= 100 {
                    off_role_count += 1;
                }
                if pain >= 1000 {
                    pain_1000_count += 1;
                }
                if pain >= 5000 {
                    pain_5000_count += 1;
                }
            }
        }
    }

    VariantQuality {
        mmr_std,
        total_gap,
        tank_gap,
        tank_adjacent_gap,
        off_role_count,
        pain_1000_count,
        pain_5000_count,
        subrole_collisions: collisions,
        balance: variant.metrics.balance,
        comfort: variant.metrics.comfort,
        signature: signature(&sol),
    }
}

fn run_fixture(base: &bench_api::BenchContext, seeds: &[u64]) -> Vec<VariantQuality> {
    seeds
        .iter()
        .map(|&seed| {
            let ctx = bench_api::with_optimizer_seed(base, seed);
            let resp = run_optimizer(&ctx.0, None).expect("harness run must succeed");
            assert!(
                !resp.variants.is_empty(),
                "harness run must return variants"
            );
            // Жёсткий инвариант: ни в одном возвращённом варианте не должно
            // быть назначений на неиграбельную роль (pain = 5000).
            for variant in &resp.variants {
                let quality = quality_of_variant(&ctx.0, variant);
                assert_eq!(
                    quality.pain_5000_count, 0,
                    "variant contains unplayable (pain=5000) assignment"
                );
            }
            quality_of_variant(&ctx.0, &resp.variants[0])
        })
        .collect()
}

fn median(mut values: Vec<f64>) -> f64 {
    values.sort_by(|a, b| a.partial_cmp(b).unwrap_or(Ordering::Equal));
    let n = values.len();
    if n == 0 {
        return 0.0;
    }
    if n % 2 == 1 {
        values[n / 2]
    } else {
        (values[n / 2 - 1] + values[n / 2]) / 2.0
    }
}

fn report(name: &str, results: &[VariantQuality]) {
    let med = |f: fn(&VariantQuality) -> f64| median(results.iter().map(f).collect());
    let mut signature_counts: HashMap<u64, usize> = HashMap::new();
    for r in results {
        *signature_counts.entry(r.signature).or_insert(0) += 1;
    }
    let stability = signature_counts.values().copied().max().unwrap_or(0);
    println!(
        "HARNESS {name}: mmr_std={:.2} total_gap={:.1} tank_gap={:.1} tank_adj_gap={:.1} \
             off_role={:.1} pain1000={:.1} pain5000={:.1} collisions={:.1} \
             balance={:.1} comfort={:.1} sig_stability={stability}/{}",
        med(|r| r.mmr_std),
        med(|r| r.total_gap),
        med(|r| r.tank_gap),
        med(|r| r.tank_adjacent_gap),
        med(|r| r.off_role_count as f64),
        med(|r| r.pain_1000_count as f64),
        med(|r| r.pain_5000_count as f64),
        med(|r| r.subrole_collisions as f64),
        med(|r| r.balance),
        med(|r| r.comfort),
        results.len(),
    );
}

#[test]
fn harness_4_teams() {
    let base = bench_api::synthetic_context(4, 1001);
    let results = run_fixture(&base, &SEEDS);
    report("4t", &results);
}

#[test]
fn harness_12_teams() {
    let base = bench_api::synthetic_context(12, 2002);
    let results = run_fixture(&base, &SEEDS);
    report("12t", &results);
}

#[test]
fn harness_wide_tank_12_teams() {
    let base = bench_api::synthetic_wide_tank_context(12, 3003);
    let results = run_fixture(&base, &SEEDS);
    report("wide_tank_12t", &results);
}

#[test]
#[ignore = "долгий прогон 40 команд — для nightly/ручного запуска"]
fn harness_40_teams() {
    let base = bench_api::synthetic_context(40, 4004);
    let results = run_fixture(&base, &SEEDS);
    report("40t", &results);
}

#[test]
#[ignore = "долгий прогон 40 команд — для nightly/ручного запуска"]
fn harness_wide_tank_40_teams() {
    let base = bench_api::synthetic_wide_tank_context(40, 5005);
    let results = run_fixture(&base, &SEEDS);
    report("wide_tank_40t", &results);
}

/// Абляция доли team-preserving crossover.
#[test]
#[ignore = "абляция — только ручной запуск"]
fn harness_crossover_share_ablation() {
    for (teams, fixture_seed) in [(4usize, 1001u64), (12, 2002), (40, 4004)] {
        for share in [0.0_f64, 0.5] {
            let base = bench_api::synthetic_context(teams, fixture_seed);
            let mut ctx = base.0.clone();
            ctx.config.team_crossover_share = share;
            let results = run_fixture(&bench_api::BenchContext(ctx), &SEEDS);
            report(&format!("{teams}t_share_{share}"), &results);
        }
    }
}

/// Production HIGH_QUALITY budget — the reference point for ablations.
fn hq_baseline(ctx: &mut Context) {
    let cfg = &mut ctx.config;
    cfg.population_size = 200;
    cfg.generation_count = 1000;
    cfg.mutation_rate = 0.45;
    cfg.mutation_strength = 3;
    cfg.mutation_rate_min = 0.2;
    cfg.mutation_rate_max = 0.75;
    cfg.polish_max_passes = 150;
    cfg.island_count = 8;
    cfg.stagnation_kick_patience = 25;
    cfg.convergence_patience = 200;
    cfg.max_result_variants = 30;
    cfg.time_limit_ms = Some(600_000);
}

/// Cheap budget for screening weight directions: the composition of an axis is
/// a structural effect, visible on a short search too, and one profile run
/// takes a fraction of a second instead of ten.
fn fast_baseline(ctx: &mut Context) {
    hq_baseline(ctx);
    let cfg = &mut ctx.config;
    cfg.population_size = 80;
    cfg.generation_count = 200;
    cfg.island_count = 4;
    cfg.polish_max_passes = 40;
    cfg.convergence_patience = 60;
    cfg.max_result_variants = 10;
}

/// Production `AlgorithmConfig` defaults (a.k.a. the DEFAULT preset).
fn default_baseline(ctx: &mut Context) {
    hq_baseline(ctx);
    mid_weights(ctx);
    let cfg = &mut ctx.config;
    cfg.population_size = 100;
    cfg.generation_count = 400;
    cfg.mutation_rate = 0.35;
    cfg.mutation_strength = 2;
    cfg.mutation_rate_min = 0.15;
    cfg.mutation_rate_max = 0.65;
    cfg.island_count = 6;
    cfg.polish_max_passes = 50;
    cfg.stagnation_kick_patience = 15;
    cfg.convergence_patience = 100;
    cfg.max_result_variants = 10;
}

/// Middle of both axes — the composition DEFAULT and COMBINED use.
fn mid_weights(ctx: &mut Context) {
    tank_settings(ctx).line_gap_weight = 0.8;
    let cfg = &mut ctx.config;
    cfg.average_mmr_balance_weight = 2.0;
    cfg.intra_team_std_weight = 1.8;
    cfg.internal_role_spread_weight = 0.8;
    cfg.role_discomfort_weight = 2.0;
    cfg.max_role_discomfort_weight = 1.0;
    cfg.team_max_pain_weight = 0.6;
    cfg.rank_comfort_tilt = 0.45;
}

/// DEFAULT against the previous defaults and the next budget steps. Measured
/// on 6 profiles x 12/24 teams x 3 seeds: legacy (60/120, 4 islands, canonical
/// weights, no early stop) scores bal 1.64 / com 1.27 against the current one
/// at 0.3s versus 1.7s; 300 generations and population 100 land in between.
const DEFAULT_KNOBS: &[Knob] = &[
    ("baseline", |_| {}),
    ("legacy_defaults", |c| {
        tank_settings(c).line_gap_weight = 1.0;
        c.config.population_size = 60;
        c.config.generation_count = 120;
        c.config.island_count = 4;
        c.config.convergence_patience = 0;
        c.config.average_mmr_balance_weight = 0.8;
        c.config.intra_team_std_weight = 2.8;
        c.config.internal_role_spread_weight = 1.2;
        c.config.role_discomfort_weight = 1.0;
        c.config.max_role_discomfort_weight = 2.0;
        c.config.team_max_pain_weight = 1.0;
        c.config.rank_comfort_tilt = 0.5;
    }),
    ("pop150_gens600", |c| {
        c.config.population_size = 150;
        c.config.generation_count = 600;
    }),
    ("islands8_conv200", |c| {
        c.config.island_count = 8;
        c.config.convergence_patience = 200;
    }),
];

#[test]
#[ignore = "DEFAULT tuning — manual run only"]
fn harness_default_budget_ablation() {
    run_ablation(
        DEFAULT_KNOBS,
        &[11, 22, 33],
        &[12, 24],
        &bench_api::PROFILES,
        default_baseline,
    );
}

/// Абляции крутят не только конфиг, но и ролевые веса, поэтому knob получает
/// весь контекст.
type Knob = (&'static str, fn(&mut Context));

/// One change per row from the baseline: knob interactions are checked
/// separately, otherwise the matrix is unreadable.
const ABLATIONS: &[Knob] = &[
    ("baseline", |_| {}),
    ("islands_4", |c| c.config.island_count = 4),
    ("islands_16", |c| c.config.island_count = 16),
    ("pop_120", |c| c.config.population_size = 120),
    ("pop_320", |c| c.config.population_size = 320),
    ("gens_400", |c| c.config.generation_count = 400),
    ("gens_2000", |c| c.config.generation_count = 2000),
    ("polish_60", |c| c.config.polish_max_passes = 60),
    ("polish_400", |c| c.config.polish_max_passes = 400),
    ("mut_str_2", |c| c.config.mutation_strength = 2),
    ("mut_str_5", |c| c.config.mutation_strength = 5),
    ("mut_window_narrow", |c| {
        c.config.mutation_rate_min = 0.1;
        c.config.mutation_rate_max = 0.5;
    }),
    ("mut_window_wide", |c| {
        c.config.mutation_rate_min = 0.35;
        c.config.mutation_rate_max = 0.95;
    }),
    ("cross_060", |c| c.config.crossover_rate = 0.6),
    ("cross_095", |c| c.config.crossover_rate = 0.95),
    ("greedy_12", |c| c.config.greedy_seed_count = 12),
    ("kick_10", |c| c.config.stagnation_kick_patience = 10),
    ("kick_60", |c| c.config.stagnation_kick_patience = 60),
    ("conv_off", |c| c.config.convergence_patience = 0),
    ("conv_60", |c| c.config.convergence_patience = 60),
    ("conv_400", |c| c.config.convergence_patience = 400),
    ("eps_001", |c| c.config.convergence_epsilon = 0.001),
    ("collision_x2", |c| c.config.sub_role_collision_weight = 48.0),
    ("max_gap_x2", |c| c.config.max_team_gap_weight = 3.0),
];

#[derive(Debug, Clone, Copy, Default)]
struct AblationSummary {
    mmr_std: f64,
    total_gap: f64,
    tank_adj_gap: f64,
    off_role: f64,
    pain_1000: f64,
    collisions: f64,
    secs: f64,
}

fn summarize(results: &[VariantQuality], secs: f64) -> AblationSummary {
    let med = |f: fn(&VariantQuality) -> f64| median(results.iter().map(f).collect());
    AblationSummary {
        mmr_std: med(|r| r.mmr_std),
        total_gap: med(|r| r.total_gap),
        tank_adj_gap: med(|r| r.tank_adjacent_gap),
        off_role: med(|r| r.off_role_count as f64),
        pain_1000: med(|r| r.pain_1000_count as f64),
        collisions: med(|r| r.subrole_collisions as f64),
        secs,
    }
}

/// Geometric mean of the ratios to the baseline (<1 is better than baseline).
/// The metrics have different magnitudes, so an arithmetic mean would let the
/// largest one (tank_adj_gap) dominate; the +1 offsets avoid dividing by zero
/// on dense pools where a metric degenerates to 0.
fn ratio_geomean(terms: &[(f64, f64)]) -> f64 {
    let sum: f64 = terms
        .iter()
        .map(|(b, c)| ((c + 1.0) / (b + 1.0)).ln())
        .sum();
    (sum / terms.len() as f64).exp()
}

/// Balance axis: spread of team strength. This is what HIGH_QUALITY minimizes.
fn balance_score(base: &AblationSummary, cur: &AblationSummary) -> f64 {
    ratio_geomean(&[
        (base.mmr_std, cur.mmr_std),
        (base.total_gap, cur.total_gap),
        (base.tank_adj_gap, cur.tank_adj_gap),
    ])
}

/// Comfort axis: off-role play and pain. This is what PREFERENCE_FOCUSED
/// minimizes.
fn comfort_score(base: &AblationSummary, cur: &AblationSummary) -> f64 {
    ratio_geomean(&[
        (base.off_role, cur.off_role),
        (base.pain_1000, cur.pain_1000),
        (base.collisions, cur.collisions),
    ])
}

fn composite(base: &AblationSummary, cur: &AblationSummary) -> f64 {
    (balance_score(base, cur) * comfort_score(base, cur)).sqrt()
}

/// Runs a knob set over every pool profile: with different per-role averages
/// and flex depth the same knob behaves differently, so the decision is made
/// on the summary rather than on a single fixture.
fn run_ablation(
    knobs: &[Knob],
    seeds: &[u64],
    sizes: &[usize],
    profiles: &[bench_api::FixtureProfile],
    base: fn(&mut Context),
) {
    let mut log_sums = vec![0.0f64; knobs.len()];
    let mut bal_sums = vec![0.0f64; knobs.len()];
    let mut com_sums = vec![0.0f64; knobs.len()];
    let mut secs_sums = vec![0.0f64; knobs.len()];
    let mut counts = vec![0usize; knobs.len()];

    for profile in profiles.iter() {
        for &teams in sizes {
            let fixture =
                bench_api::synthetic_profiled_context(profile, teams, 7000 + teams as u64);
            let mut base_summary = AblationSummary::default();
            for (idx, (name, knob)) in knobs.iter().enumerate() {
                let mut ctx = fixture.0.clone();
                base(&mut ctx);
                knob(&mut ctx);
                let started = std::time::Instant::now();
                let results = run_fixture(&bench_api::BenchContext(ctx), seeds);
                let summary =
                    summarize(&results, started.elapsed().as_secs_f64() / seeds.len() as f64);
                if idx == 0 {
                    base_summary = summary;
                }
                let bal = balance_score(&base_summary, &summary);
                let com = comfort_score(&base_summary, &summary);
                println!(
                    "ABL {fixture}/{teams}t {name}: bal={bal:.3} com={com:.3} \
                     comp={comp:.3} mmr_std={mmr:.2} gap={gap:.1} tank_adj={tank:.1} \
                     off_role={off:.1} pain1000={pain:.1} coll={coll:.1} t={secs:.1}s",
                    fixture = profile.name,
                    comp = composite(&base_summary, &summary),
                    mmr = summary.mmr_std,
                    gap = summary.total_gap,
                    tank = summary.tank_adj_gap,
                    off = summary.off_role,
                    pain = summary.pain_1000,
                    coll = summary.collisions,
                    secs = summary.secs,
                );
                log_sums[idx] += (bal * com).sqrt().ln();
                bal_sums[idx] += bal.ln();
                com_sums[idx] += com.ln();
                secs_sums[idx] += summary.secs;
                counts[idx] += 1;
            }
        }
    }

    for (idx, (name, _)) in knobs.iter().enumerate() {
        let n = counts[idx].max(1) as f64;
        println!(
            "ABL SUMMARY {name}: bal_geo={:.3} com_geo={:.3} comp_geo={:.3} avg_secs={:.1}",
            (bal_sums[idx] / n).exp(),
            (com_sums[idx] / n).exp(),
            (log_sums[idx] / n).exp(),
            secs_sums[idx] / n
        );
    }
}

/// Summary of the last tuning pass (2026-09-17, geometric mean over profiles):
/// at 8-16 teams conv_200 was the best of 20 knobs (0.943); at 24-40 teams
/// conv_200 scored 0.938 for +50% runtime, conv_400 was no better,
/// islands_16 0.976 and polish_60 regressed to 1.05; at 40 teams neither
/// conv200+pop320 nor conv200+gens2000 beat conv_200. Doubling any single
/// objective weight moved the composite by +-3% with a profile-dependent sign,
/// so those were left alone. Sizes, profiles and seeds are edited here.
#[test]
#[ignore = "search parameter ablation — manual run only"]
fn harness_search_param_ablation() {
    run_ablation(ABLATIONS, &[11, 22, 33], &[8, 16], &bench_api::PROFILES, hq_baseline);
}

/// Preset weight candidates. balance = total_rating_std*w_team_total +
/// gap*w_max_gap + **mmr_std*w_avg_mmr** + role_line + intra_std +
/// role_spread + role_line_gap + role_line_std + eff_total; comfort =
/// **avg_discomfort*w_discomfort** + global_max_pain + team_max_pain +
/// collisions. So "HQ on mmr_std" means raising w_avg_mmr and lowering the
/// terms competing inside the same axis (intra_std, role_spread, tank line
/// weights), and "preference on off_role" means raising w_discomfort (total
/// pain is roughly the count of non-first preferences) and lowering the tail
/// max/pain terms. Scaling a whole axis uniformly is a no-op: dominance and
/// normalization are invariant to it (checked by the `comfort_uniform_x2`
/// knob).
const PRESET_KNOBS: &[Knob] = &[
    ("baseline", |_| {}),
    ("comfort_uniform_x2", |c| {
        c.config.role_discomfort_weight = 2.0;
        c.config.max_role_discomfort_weight = 4.0;
        c.config.team_max_pain_weight = 2.0;
        c.config.sub_role_collision_weight = 48.0;
    }),
    // --- HQ: aiming at mmr_std ---
    ("hq_mmr_focus", |c| {
        let tank = tank_settings(c);
        tank.line_gap_weight = 0.5;
        tank.line_std_weight = 1.0;
        c.config.average_mmr_balance_weight = 3.0;
        c.config.intra_team_std_weight = 1.0;
        c.config.internal_role_spread_weight = 0.4;
        c.config.effective_total_std_weight = 1.0;
        c.config.rank_comfort_tilt = 0.25;
    }),
    ("preset_HIGH_QUALITY", |c| {
        let tank = tank_settings(c);
        tank.line_gap_weight = 0.25;
        tank.line_std_weight = 0.75;
        c.config.average_mmr_balance_weight = 4.0;
        c.config.intra_team_std_weight = 0.5;
        c.config.internal_role_spread_weight = 0.2;
        c.config.effective_total_std_weight = 0.75;
        c.config.rank_comfort_tilt = 0.1;
    }),
    // --- PREFERENCE: aiming at off_role ---
    ("preset_PREFERENCE_FOCUSED", |c| {
        c.config.role_discomfort_weight = 4.0;
        c.config.max_role_discomfort_weight = 0.5;
        c.config.team_max_pain_weight = 0.25;
        c.config.rank_comfort_tilt = 0.8;
    }),
    ("pref_offrole_focus_hard", |c| {
        c.config.role_discomfort_weight = 6.0;
        c.config.max_role_discomfort_weight = 0.25;
        c.config.team_max_pain_weight = 0.1;
        c.config.sub_role_collision_weight = 12.0;
        c.config.rank_comfort_tilt = 0.95;
    }),
    // --- COMBINED: middle of both axes ---
    ("preset_COMBINED", |c| {
        tank_settings(c).line_gap_weight = 0.8;
        c.config.average_mmr_balance_weight = 2.0;
        c.config.intra_team_std_weight = 1.8;
        c.config.internal_role_spread_weight = 0.8;
        c.config.role_discomfort_weight = 2.0;
        c.config.max_role_discomfort_weight = 1.0;
        c.config.team_max_pain_weight = 0.6;
        c.config.rank_comfort_tilt = 0.45;
    }),
];

#[test]
#[ignore = "preset weight ablation — manual run only"]
fn harness_preset_profile_ablation() {
    run_ablation(PRESET_KNOBS, &[11, 22, 33, 44, 55], &[12, 24], &bench_api::PROFILES, fast_baseline);
}

/// The same three weight sets on the production deep budget: the screen ran on
/// the cheap one (axis composition is a structural effect) while the presets
/// ship with the deep budget.
#[test]
#[ignore = "preset confirmation on the production budget — manual run only"]
fn harness_preset_confirm_deep() {
    let shipped: Vec<Knob> = PRESET_KNOBS
        .iter()
        .copied()
        .filter(|(name, _)| name == &"baseline" || name.starts_with("preset_"))
        .collect();
    let profiles: Vec<bench_api::FixtureProfile> = bench_api::PROFILES
        .iter()
        .copied()
        .filter(|p| p.name == "uniform" || p.name == "role_skew" || p.name == "wide_tank")
        .collect();
    run_ablation(&shipped, &[11, 22, 33], &[16], &profiles, hq_baseline);
}

/// Permanent report over every pool profile: skewed per-role averages, a dense
/// pool and a boxed-in flex pool behave differently, and an objective
/// regression is often visible on only one of them.
#[test]
fn harness_profiles_12_teams() {
    for profile in bench_api::PROFILES.iter() {
        let base = bench_api::synthetic_profiled_context(profile, 12, 6006);
        let results = run_fixture(&base, &SEEDS);
        report(&format!("profile_{}_12t", profile.name), &results);
    }
}
