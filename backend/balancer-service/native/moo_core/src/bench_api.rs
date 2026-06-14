use super::*;

pub struct BenchContext(pub(crate) Context);
pub struct BenchSolution(pub(crate) Solution);
pub struct BenchCandidates(pub(crate) Vec<ArchiveEntry>);

fn bench_config() -> ConfigSpec {
    ConfigSpec {
        population_size: 40,
        generation_count: 60,
        mutation_rate: 0.35,
        mutation_strength: 2,
        max_result_variants: 7,
        average_mmr_balance_weight: 0.8,
        team_total_balance_weight: 1.0,
        max_team_gap_weight: 1.5,
        role_discomfort_weight: 1.0,
        max_role_discomfort_weight: 2.0,
        team_max_pain_weight: 1.0,
        role_line_balance_weight: 1.0,
        sub_role_collision_weight: 24.0,
        use_captains: false,
        tank_impact_weight: 1.4,
        dps_impact_weight: 1.0,
        support_impact_weight: 1.1,
        tank_gap_weight: 1.0,
        tank_std_weight: 1.5,
        effective_total_std_weight: 1.2,
        intra_team_std_weight: 2.8,
        internal_role_spread_weight: 1.2,
        convergence_patience: 0,
        convergence_epsilon: 0.005,
        mutation_rate_min: 0.15,
        mutation_rate_max: 0.65,
        island_count: 4,
        polish_max_passes: 50,
        greedy_seed_count: 3,
        stagnation_kick_patience: 15,
        crossover_rate: 0.85,
        team_crossover_share: 0.5,
        time_limit_ms: None,
        rank_comfort_tilt: 0.5,
    }
}

/// Детерминированная синтетическая фикстура: маска Tank 1 / Damage 2 /
/// Support 2, по 5 игроков на команду. Никакой зависимости от часов или
/// глобального состояния — один seed → одна фикстура.
pub fn synthetic_context(num_teams: usize, seed: u64) -> BenchContext {
    let mut rng = MooRng::seed_from_u64(seed);
    let roles = ["Tank", "Damage", "Support"];
    let caps = [1usize, 2, 2];
    let mask: HashMap<String, usize> = roles
        .iter()
        .zip(caps)
        .map(|(role, cap)| (role.to_string(), cap))
        .collect();

    let mut seed_roles: Vec<&str> = Vec::new();
    for (role, cap) in roles.iter().zip(caps) {
        for _ in 0..cap * num_teams {
            seed_roles.push(role);
        }
    }

    let subclass_pool = ["hitscan", "projectile", "main_heal", "light_heal"];
    let players: Vec<PlayerSpec> = seed_roles
        .iter()
        .enumerate()
        .map(|(i, &seed_role)| {
            let mut ratings = HashMap::new();
            ratings.insert(seed_role.to_string(), rng.random_range(100..2000));
            for role in roles.iter() {
                if *role != seed_role && rng.random_bool(0.5) {
                    ratings.insert(role.to_string(), rng.random_range(100..2000));
                }
            }
            // ВАЖНО: порядок ключей HashMap недетерминирован — сортируем
            // перед shuffle, чтобы фикстура зависела только от seed.
            let mut preferences: Vec<String> = ratings.keys().cloned().collect();
            preferences.sort();
            preferences.shuffle(&mut rng);
            let mut subclasses = HashMap::new();
            if rng.random_bool(0.4) {
                subclasses.insert(
                    seed_role.to_string(),
                    subclass_pool[rng.random_range(0..subclass_pool.len())].to_string(),
                );
            }
            PlayerSpec {
                uuid: format!("p{i}"),
                name: format!("p{i}"),
                ratings,
                preferences,
                subclasses,
                is_captain: false,
                is_flex: rng.random_bool(0.08),
                seed_role: Some(seed_role.to_string()),
            }
        })
        .collect();

    let request = NativeRequest {
        players,
        num_teams,
        seed,
        mask,
        config: bench_config(),
    };
    BenchContext(Context::from_request(request).expect("synthetic fixture must be valid"))
}

/// Фикстура «широкий пул танков»: рейтинги Tank-игроков равномерно
/// размазаны по ~40..1700 (как в реальном турнире, где разрыв танк-линии
/// структурно неустраним при capacity 1), flex-игроков мало.
pub fn synthetic_wide_tank_context(num_teams: usize, seed: u64) -> BenchContext {
    let mut rng = MooRng::seed_from_u64(seed);
    let roles = ["Tank", "Damage", "Support"];
    let caps = [1usize, 2, 2];
    let mask: HashMap<String, usize> = roles
        .iter()
        .zip(caps)
        .map(|(role, cap)| (role.to_string(), cap))
        .collect();

    let mut players: Vec<PlayerSpec> = Vec::new();
    let mut index = 0usize;
    for (role, cap) in roles.iter().zip(caps) {
        let line_count = cap * num_teams;
        for line_pos in 0..line_count {
            let rating = if *role == "Tank" {
                // Равномерная сетка 40..1700 — гарантированно широкий пул
                let span = 1700 - 40;
                40 + (span * line_pos / line_count.max(1)) as i32
            } else {
                rng.random_range(300..1500)
            };
            let mut ratings = HashMap::new();
            ratings.insert(role.to_string(), rating);
            for other in roles.iter() {
                if other != role && rng.random_bool(0.4) {
                    ratings.insert(other.to_string(), rng.random_range(200..1200));
                }
            }
            let mut preferences: Vec<String> = ratings.keys().cloned().collect();
            preferences.sort();
            preferences.shuffle(&mut rng);
            players.push(PlayerSpec {
                uuid: format!("p{index}"),
                name: format!("p{index}"),
                ratings,
                preferences,
                subclasses: HashMap::new(),
                is_captain: false,
                is_flex: rng.random_bool(0.05),
                seed_role: Some(role.to_string()),
            });
            index += 1;
        }
    }

    let request = NativeRequest {
        players,
        num_teams,
        seed,
        mask,
        config: bench_config(),
    };
    BenchContext(Context::from_request(request).expect("wide-tank fixture must be valid"))
}

/// Копия контекста с другим seed оптимизатора (фикстура та же).
pub fn with_optimizer_seed(ctx: &BenchContext, seed: u64) -> BenchContext {
    let mut copy = ctx.0.clone();
    copy.seed = seed;
    BenchContext(copy)
}

pub fn snake_seed(ctx: &BenchContext) -> BenchSolution {
    let mut rng = MooRng::seed_from_u64(42);
    let mut sol = create_snake_draft_solution(&ctx.0);
    ensure_feasibility(&mut sol, &ctx.0, &mut rng);
    BenchSolution(sol)
}

pub fn randomized_solution(ctx: &BenchContext, seed: u64) -> BenchSolution {
    let mut rng = MooRng::seed_from_u64(seed);
    let mut sol = create_random_solution(&ctx.0, &mut rng);
    ensure_feasibility(&mut sol, &ctx.0, &mut rng);
    BenchSolution(sol)
}

pub fn objectives(ctx: &BenchContext, sol: &BenchSolution) -> (f64, f64) {
    let obj = calculate_objectives(&sol.0, &ctx.0);
    (obj.balance, obj.comfort)
}

pub fn polish(ctx: &BenchContext, sol: &BenchSolution, max_passes: usize) -> (f64, f64) {
    let polished = polish_pareto(&sol.0, &ctx.0, max_passes);
    let obj = calculate_objectives(&polished, &ctx.0);
    (obj.balance, obj.comfort)
}

pub fn make_candidates(ctx: &BenchContext, count: usize, seed: u64) -> BenchCandidates {
    let mut rng = MooRng::seed_from_u64(seed);
    let entries = (0..count)
        .map(|_| {
            let mut sol = create_random_solution(&ctx.0, &mut rng);
            ensure_feasibility(&mut sol, &ctx.0, &mut rng);
            ArchiveEntry::new(calculate_objectives(&sol, &ctx.0), sol)
        })
        .collect();
    BenchCandidates(entries)
}

pub fn archive_storm(ctx: &BenchContext, candidates: &BenchCandidates) -> usize {
    let mut archive: Vec<ArchiveEntry> = Vec::new();
    let mut sigs: HashSet<u64> = HashSet::new();
    for entry in &candidates.0 {
        archive_update(&mut archive, &mut sigs, entry.clone(), &ctx.0);
    }
    archive.len()
}

pub fn run_full(ctx: &BenchContext) -> usize {
    run_optimizer(&ctx.0, None)
        .map(|resp| resp.variants.len())
        .unwrap_or(0)
}
