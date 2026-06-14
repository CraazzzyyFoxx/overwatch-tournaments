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

fn rebuild_solution(ctx: &Context, variant: &VariantResponse) -> Solution {
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
