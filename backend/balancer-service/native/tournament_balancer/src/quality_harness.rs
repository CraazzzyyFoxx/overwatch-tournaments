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

pub(crate) fn rebuild_solution(ctx: &Context, variant: &VariantResponse) -> Solution {
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

fn quality_of_variant(ctx: &Context, variant: &VariantResponse) -> VariantQuality {
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
    if let Some(tank_idx) = ctx.tank_role_idx {
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
        balance: variant.balance,
        comfort: variant.comfort,
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

/// Продакшен-бюджет HIGH_QUALITY — точка отсчёта для абляции.
fn hq_baseline(cfg: &mut ConfigSpec) {
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

/// Дешёвый бюджет для скрина направления весов: состав объектива —
/// структурный эффект, он виден и на коротком поиске, а прогон профиля
/// занимает доли секунды вместо десятка секунд.
fn fast_baseline(cfg: &mut ConfigSpec) {
    hq_baseline(cfg);
    cfg.population_size = 80;
    cfg.generation_count = 200;
    cfg.island_count = 4;
    cfg.polish_max_passes = 40;
    cfg.convergence_patience = 60;
    cfg.max_result_variants = 10;
}

type Knob = (&'static str, fn(&mut ConfigSpec));

/// По одному изменению от baseline: пересечения знобов проверяются отдельно,
/// иначе матрица не читается.
const ABLATIONS: &[Knob] = &[
    ("baseline", |_| {}),
    ("islands_4", |c| c.island_count = 4),
    ("islands_16", |c| c.island_count = 16),
    ("pop_120", |c| c.population_size = 120),
    ("pop_320", |c| c.population_size = 320),
    ("gens_400", |c| c.generation_count = 400),
    ("gens_2000", |c| c.generation_count = 2000),
    ("polish_60", |c| c.polish_max_passes = 60),
    ("polish_400", |c| c.polish_max_passes = 400),
    ("mut_str_2", |c| c.mutation_strength = 2),
    ("mut_str_5", |c| c.mutation_strength = 5),
    ("mut_window_narrow", |c| {
        c.mutation_rate_min = 0.1;
        c.mutation_rate_max = 0.5;
    }),
    ("mut_window_wide", |c| {
        c.mutation_rate_min = 0.35;
        c.mutation_rate_max = 0.95;
    }),
    ("cross_060", |c| c.crossover_rate = 0.6),
    ("cross_095", |c| c.crossover_rate = 0.95),
    ("greedy_12", |c| c.greedy_seed_count = 12),
    ("kick_10", |c| c.stagnation_kick_patience = 10),
    ("kick_60", |c| c.stagnation_kick_patience = 60),
    ("conv_off", |c| c.convergence_patience = 0),
    ("conv_60", |c| c.convergence_patience = 60),
    ("conv_400", |c| c.convergence_patience = 400),
    ("eps_001", |c| c.convergence_epsilon = 0.001),
    ("collision_x2", |c| c.sub_role_collision_weight = 48.0),
    ("max_gap_x2", |c| c.max_team_gap_weight = 3.0),
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

/// Геометрическое среднее отношений к baseline (<1 — лучше baseline).
/// Метрики разной размерности, поэтому аддитивное среднее утащило бы вес в
/// самую крупную (tank_adj_gap); +1 к каждой снимает деление на ноль на
/// плотных пулах, где метрика вырождается в 0.
fn ratio_geomean(terms: &[(f64, f64)]) -> f64 {
    let sum: f64 = terms
        .iter()
        .map(|(b, c)| ((c + 1.0) / (b + 1.0)).ln())
        .sum();
    (sum / terms.len() as f64).exp()
}

/// Ось баланса: разброс силы команд. Именно её минимизирует HIGH_QUALITY.
fn balance_score(base: &AblationSummary, cur: &AblationSummary) -> f64 {
    ratio_geomean(&[
        (base.mmr_std, cur.mmr_std),
        (base.total_gap, cur.total_gap),
        (base.tank_adj_gap, cur.tank_adj_gap),
    ])
}

/// Ось комфорта: игра не на своей роли и боль. Её минимизирует
/// PREFERENCE_FOCUSED.
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

/// Прогон набора кнобов по всем профилям пула: на разных средних по ролям и
/// разной глубине флекс-пула один и тот же кноб ведёт себя по-разному,
/// поэтому решение принимается по сводке, а не по одной фикстуре.
fn run_ablation(
    knobs: &[Knob],
    seeds: &[u64],
    sizes: &[usize],
    profiles: &[bench_api::FixtureProfile],
    base: fn(&mut ConfigSpec),
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
                base(&mut ctx.config);
                knob(&mut ctx.config);
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

/// Сводка последнего тюнинга (2026-09-17, geo-среднее по профилям):
/// 8-16 команд — conv_200 0.943 лучший из 20 кнобов; 24-40 команд —
/// conv_200 0.938 при +50% времени, conv_400 не лучше, islands_16 0.976,
/// polish_60 регресс 1.05; 40 команд — conv200+pop320 и conv200+gens2000
/// не обошли conv_200. Веса objective (x2 по каждому) дали ±3% со знаком,
/// зависящим от профиля — не менялись. Размеры/профили/сиды правятся здесь.
#[test]
#[ignore = "абляция параметров поиска — только ручной запуск"]
fn harness_search_param_ablation() {
    run_ablation(ABLATIONS, &[11, 22, 33], &[8, 16], &bench_api::PROFILES, hq_baseline);
}

/// Кандидаты профилей пресетов. balance = total_rating_std·w_team_total +
/// gap·w_max_gap + **mmr_std·w_avg_mmr** + role_line + intra_std +
/// role_spread + tank_gap + tank_std + eff_total; comfort =
/// **avg_discomfort·w_discomfort** + global_max_pain + team_max_pain +
/// collisions. Поэтому «HQ по mmr_std» — это поднять w_avg_mmr и опустить
/// конкурирующие внутри той же оси члены (intra_std, role_spread, tank_gap),
/// а «preference по off_role» — поднять w_discomfort (сумма боли ≈ число
/// не-первых предпочтений) и опустить хвостовые max/pain-члены.
/// Однородное масштабирование всей оси — no-op: доминирование и нормировка
/// к нему инвариантны (проверяется кнобом `comfort_uniform_x2`).
const PRESET_KNOBS: &[Knob] = &[
    ("baseline", |_| {}),
    ("comfort_uniform_x2", |c| {
        c.role_discomfort_weight = 2.0;
        c.max_role_discomfort_weight = 4.0;
        c.team_max_pain_weight = 2.0;
        c.sub_role_collision_weight = 48.0;
    }),
    // --- HQ: целимся в mmr_std ---
    ("hq_mmr_focus", |c| {
        c.average_mmr_balance_weight = 3.0;
        c.intra_team_std_weight = 1.0;
        c.internal_role_spread_weight = 0.4;
        c.tank_gap_weight = 0.5;
        c.tank_std_weight = 1.0;
        c.effective_total_std_weight = 1.0;
        c.rank_comfort_tilt = 0.25;
    }),
    ("hq_mmr_focus_hard", |c| {
        c.average_mmr_balance_weight = 4.0;
        c.intra_team_std_weight = 0.5;
        c.internal_role_spread_weight = 0.2;
        c.tank_gap_weight = 0.25;
        c.tank_std_weight = 0.75;
        c.effective_total_std_weight = 0.75;
        c.rank_comfort_tilt = 0.1;
    }),
    // --- PREFERENCE: целимся в off_role ---
    ("pref_offrole_focus", |c| {
        c.role_discomfort_weight = 4.0;
        c.max_role_discomfort_weight = 0.5;
        c.team_max_pain_weight = 0.25;
        c.rank_comfort_tilt = 0.8;
    }),
    ("pref_offrole_focus_hard", |c| {
        c.role_discomfort_weight = 6.0;
        c.max_role_discomfort_weight = 0.25;
        c.team_max_pain_weight = 0.1;
        c.sub_role_collision_weight = 12.0;
        c.rank_comfort_tilt = 0.95;
    }),
    // --- COMBINED: середина по обеим осям ---
    ("combined", |c| {
        c.average_mmr_balance_weight = 2.0;
        c.intra_team_std_weight = 1.8;
        c.internal_role_spread_weight = 0.8;
        c.tank_gap_weight = 0.8;
        c.role_discomfort_weight = 2.0;
        c.max_role_discomfort_weight = 1.0;
        c.team_max_pain_weight = 0.6;
        c.rank_comfort_tilt = 0.45;
    }),
];

#[test]
#[ignore = "абляция профилей пресетов — только ручной запуск"]
fn harness_preset_profile_ablation() {
    run_ablation(PRESET_KNOBS, &[11, 22, 33, 44, 55], &[12, 24], &bench_api::PROFILES, fast_baseline);
}

/// Постоянный отчёт по всем профилям пула: перекошенные средние по ролям,
/// плотный пул и зажатый флекс ведут себя по-разному, и регресс objective
/// часто виден только на одном из них.
#[test]
fn harness_profiles_12_teams() {
    for profile in bench_api::PROFILES.iter() {
        let base = bench_api::synthetic_profiled_context(profile, 12, 6006);
        let results = run_fixture(&base, &SEEDS);
        report(&format!("profile_{}_12t", profile.name), &results);
    }
}
