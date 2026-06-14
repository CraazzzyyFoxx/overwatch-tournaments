use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use super::*;

#[derive(Debug)]
struct VariantMetrics {
    off_role_count: usize,
    mmr_std_dev: f64,
}

fn regression_config() -> ConfigSpec {
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

fn player(
    uuid: &str,
    seed_role: &str,
    ratings: &[(&str, i32)],
    preferences: &[&str],
) -> PlayerSpec {
    PlayerSpec {
        uuid: uuid.to_string(),
        name: uuid.to_string(),
        ratings: ratings
            .iter()
            .map(|(role, rating)| (role.to_string(), *rating))
            .collect(),
        preferences: preferences.iter().map(|role| role.to_string()).collect(),
        subclasses: HashMap::new(),
        is_captain: false,
        is_flex: false,
        seed_role: Some(seed_role.to_string()),
    }
}

fn regression_request() -> NativeRequest {
    NativeRequest {
        players: vec![
            player(
                "tank-1",
                "Tank",
                &[("Tank", 2980), ("Damage", 2550), ("Support", 2480)],
                &["Tank", "Damage"],
            ),
            player(
                "tank-2",
                "Tank",
                &[("Tank", 2890), ("Damage", 2490), ("Support", 2520)],
                &["Tank", "Support"],
            ),
            player(
                "tank-3",
                "Tank",
                &[("Tank", 2810), ("Damage", 2460), ("Support", 2440)],
                &["Tank", "Support"],
            ),
            player(
                "tank-4",
                "Tank",
                &[("Tank", 2740), ("Damage", 2400), ("Support", 2470)],
                &["Tank", "Damage"],
            ),
            player(
                "dps-1",
                "Damage",
                &[("Damage", 2860), ("Support", 2540)],
                &["Damage", "Support"],
            ),
            player(
                "dps-2",
                "Damage",
                &[("Damage", 2800), ("Support", 2510)],
                &["Damage", "Support"],
            ),
            player(
                "dps-3",
                "Damage",
                &[("Damage", 2730), ("Support", 2480)],
                &["Damage", "Support"],
            ),
            player(
                "dps-4",
                "Damage",
                &[("Damage", 2690), ("Support", 2450)],
                &["Damage", "Support"],
            ),
            player(
                "dps-5",
                "Damage",
                &[("Damage", 2620), ("Support", 2440), ("Tank", 2350)],
                &["Damage", "Support"],
            ),
            player(
                "dps-6",
                "Damage",
                &[("Damage", 2580), ("Support", 2410)],
                &["Damage", "Support"],
            ),
            player(
                "dps-7",
                "Damage",
                &[("Damage", 2520), ("Support", 2390)],
                &["Damage", "Support"],
            ),
            player(
                "dps-8",
                "Damage",
                &[("Damage", 2470), ("Support", 2360)],
                &["Damage", "Support"],
            ),
            player(
                "sup-1",
                "Support",
                &[("Support", 2840), ("Damage", 2560)],
                &["Support", "Damage"],
            ),
            player(
                "sup-2",
                "Support",
                &[("Support", 2780), ("Damage", 2520)],
                &["Support", "Damage"],
            ),
            player(
                "sup-3",
                "Support",
                &[("Support", 2720), ("Damage", 2490)],
                &["Support", "Damage"],
            ),
            player(
                "sup-4",
                "Support",
                &[("Support", 2680), ("Damage", 2460)],
                &["Support", "Damage"],
            ),
            player(
                "sup-5",
                "Support",
                &[("Support", 2610), ("Damage", 2430)],
                &["Support", "Damage"],
            ),
            player(
                "sup-6",
                "Support",
                &[("Support", 2570), ("Damage", 2400)],
                &["Support", "Damage"],
            ),
            player(
                "sup-7",
                "Support",
                &[("Support", 2510), ("Damage", 2370)],
                &["Support", "Damage"],
            ),
            player(
                "sup-8",
                "Support",
                &[("Support", 2460), ("Damage", 2350)],
                &["Support", "Damage"],
            ),
        ],
        num_teams: 4,
        seed: 20260422,
        mask: [
            ("Tank".to_string(), 1usize),
            ("Damage".to_string(), 2usize),
            ("Support".to_string(), 2usize),
        ]
        .into_iter()
        .collect(),
        config: regression_config(),
    }
}

fn variant_metrics(
    variant: &VariantResponse,
    ctx: &Context,
    original_players: &HashMap<String, PlayerSpec>,
) -> VariantMetrics {
    let player_index: HashMap<&str, usize> = ctx
        .players
        .iter()
        .enumerate()
        .map(|(idx, player)| (player.uuid.as_str(), idx))
        .collect();
    let role_index: HashMap<&str, usize> = ctx
        .roles
        .iter()
        .enumerate()
        .map(|(idx, role)| (role.as_str(), idx))
        .collect();

    let mut mmr_sum = 0.0;
    let mut mmr_sum2 = 0.0;
    let mut team_count = 0usize;
    let mut off_role_count = 0usize;

    for (team_pos, team) in variant.teams.iter().enumerate() {
        let mut state = TeamState {
            id: team_pos + 1,
            roster: vec![Vec::new(); ctx.roles.len()],
        };
        for (role, uuids) in &team.roster {
            let r = *role_index
                .get(role.as_str())
                .expect("unknown role in variant");
            for uuid in uuids {
                let idx = *player_index
                    .get(uuid.as_str())
                    .expect("unknown player in variant");
                state.roster[r].push(idx);

                let original = original_players
                    .get(uuid)
                    .expect("missing original player metadata");
                if !original.is_flex
                    && !original.preferences.is_empty()
                    && original.preferences[0] != *role
                {
                    off_role_count += 1;
                }
            }
        }

        let stats = calculate_team_stats(ctx, &state);
        mmr_sum += stats.mmr;
        mmr_sum2 += stats.mmr * stats.mmr;
        team_count += 1;
    }

    VariantMetrics {
        off_role_count,
        mmr_std_dev: sample_stdev_from_sums(mmr_sum, mmr_sum2, team_count),
    }
}

#[test]
fn optimizer_output_is_deterministic() {
    let request = regression_request();
    let ctx = Context::from_request(request).expect("regression fixture should be valid");
    let first = run_optimizer(&ctx, None).expect("first run should succeed");
    let second = run_optimizer(&ctx, None).expect("second run should succeed");
    let first_json = serde_json::to_string(&first).expect("serialize first");
    let second_json = serde_json::to_string(&second).expect("serialize second");
    assert_eq!(
        first_json, second_json,
        "same seed + config must produce byte-identical output"
    );
}

/// Страховка [BIT]-контракта Фазы 1: хэш полного ответа на regression-фикстуре
/// не должен меняться от рефакторингов. Перекалибровывается один раз при
/// осознанном изменении objective (Фаза 2).
#[test]
fn optimizer_output_snapshot_guard() {
    let request = regression_request();
    let ctx = Context::from_request(request).expect("regression fixture should be valid");
    let resp = run_optimizer(&ctx, None).expect("optimizer should return variants");
    let json = serde_json::to_string(&resp).expect("serialize response");
    let mut hasher = DefaultHasher::new();
    json.hash(&mut hasher);
    let fingerprint = hasher.finish();
    assert_eq!(
        fingerprint, SNAPSHOT_FINGERPRINT,
        "optimizer output changed; if intentional, re-baseline SNAPSHOT_FINGERPRINT"
    );
}

// Re-baseline 2026-06-11 (Фаза 4): апгрейд rand 0.8→0.9 — сырой поток ChaCha12
// идентичен (пиннинг), но rand 0.9 изменил алгоритм сэмплирования random_range,
// поэтому розыгрыши отличаются (эквивалентно смене seed, семантика не менялась).
// Предыдущие re-baseline: Фаза 3 (поиск), Фаза 2 (objective).
const SNAPSHOT_FINGERPRINT: u64 = 3838046900446554683;

// --- Валидация входа -------------------------------------------------

fn mini_player(uuid: &str, seed_role: &str, rating: i32) -> PlayerSpec {
    player(uuid, seed_role, &[(seed_role, rating)], &[seed_role])
}

fn mini_request(num_teams: usize, players: Vec<PlayerSpec>) -> NativeRequest {
    NativeRequest {
        players,
        num_teams,
        seed: 1,
        mask: [("Tank".to_string(), 1usize)].into_iter().collect(),
        config: regression_config(),
    }
}

#[test]
fn validation_rejects_player_slot_mismatch() {
    // 3 игрока на 2 слота (2 команды × 1 Tank) — раньше лишний игрок
    // молча выпадал из результата.
    let request = mini_request(
        2,
        vec![
            mini_player("a", "Tank", 1000),
            mini_player("b", "Tank", 900),
            mini_player("c", "Tank", 800),
        ],
    );
    let err = Context::from_request(request).expect_err("oversubscription must fail");
    assert!(err.contains("3 players"), "error should name counts: {err}");
    assert!(err.contains("2 slots"), "error should name counts: {err}");

    let request = mini_request(2, vec![mini_player("a", "Tank", 1000)]);
    let err = Context::from_request(request).expect_err("undersupply must fail");
    assert!(err.contains("1 players"), "error should name counts: {err}");
}

#[test]
fn validation_rejects_duplicate_uuid_and_single_team() {
    let request = mini_request(
        2,
        vec![
            mini_player("a", "Tank", 1000),
            mini_player("a", "Tank", 900),
        ],
    );
    let err = Context::from_request(request).expect_err("duplicate uuid must fail");
    assert!(err.contains("duplicate player uuid"), "{err}");

    let request = mini_request(1, vec![mini_player("a", "Tank", 1000)]);
    let err = Context::from_request(request).expect_err("single team must fail");
    assert!(err.contains("num_teams"), "{err}");
}

/// time_limit_ms=1 истекает до первой эпохи: результат собирается из
/// неполированных greedy-сидов, но обязан быть валидным.
#[test]
fn time_limit_returns_valid_unpolished_result() {
    let mut request = regression_request();
    request.config.time_limit_ms = Some(1);
    let original_players: HashMap<String, PlayerSpec> = request
        .players
        .iter()
        .cloned()
        .map(|player| (player.uuid.clone(), player))
        .collect();
    let ctx = Context::from_request(request).expect("fixture should be valid");
    let resp = run_optimizer(&ctx, None).expect("must succeed under time limit");
    assert!(
        !resp.variants.is_empty(),
        "time-limited run must return variants"
    );
    // Вариант валиден: все игроки на месте (metrics-хелпер падает на
    // неизвестных uuid / ролях)
    let _ = variant_metrics(&resp.variants[0], &ctx, &original_players);
}

#[test]
fn validation_rejects_bad_config_rates() {
    let mut request = mini_request(
        2,
        vec![
            mini_player("a", "Tank", 1000),
            mini_player("b", "Tank", 900),
        ],
    );
    request.config.mutation_rate = 1.5;
    let err = Context::from_request(request).expect_err("mutation_rate > 1 must fail");
    assert!(err.contains("mutation_rate"), "{err}");
}

// --- Objectives: ручной расчёт ---------------------------------------

#[test]
fn objectives_match_hand_computed_two_team_case() {
    // 2 команды × 1 Tank. A: Tank 1000, prefs [Tank] (pain 0).
    // B: Tank 500, prefs [Damage, Tank] (pain 100).
    let request = NativeRequest {
        players: vec![
            player("a", "Tank", &[("Tank", 1000)], &["Tank"]),
            player("b", "Tank", &[("Tank", 500)], &["Damage", "Tank"]),
        ],
        num_teams: 2,
        seed: 1,
        mask: [("Tank".to_string(), 1usize)].into_iter().collect(),
        config: regression_config(),
    };
    let ctx = Context::from_request(request).expect("valid");
    let sol: Solution = vec![
        TeamState {
            id: 1,
            roster: vec![vec![0]],
        },
        TeamState {
            id: 2,
            roster: vec![vec![1]],
        },
    ];
    let obj = calculate_objectives(&sol, &ctx);

    let cfg = &ctx.config;
    // Выборочное СКО тоталов [1000, 500]
    let total_std = ((1000.0_f64 - 750.0).powi(2) + (500.0_f64 - 750.0).powi(2)).sqrt();
    // Маржинальный gap penalty для 500: 25·1 + 25·3 + 50·8 + 100·18 + 300·40
    let gap_penalty = 25.0 + 75.0 + 400.0 + 1800.0 + 12000.0;
    // role-line: выборочное СКО средних [1000, 500] = total_std
    let role_line = total_std;
    // Танк: adjacent gap = 500 → 50·1 + 50·3 + 100·8 + 300·20 = 7000;
    // tank_std = total_std; eff_std = 1.4 × total_std
    let tank_penalty = 7000.0 * cfg.tank_gap_weight
        + total_std * cfg.tank_std_weight
        + total_std * 1.4 * cfg.effective_total_std_weight;
    let expected_balance = total_std * cfg.team_total_balance_weight
        + gap_penalty * cfg.max_team_gap_weight
        + total_std * cfg.average_mmr_balance_weight
        + role_line * cfg.role_line_balance_weight
        + tank_penalty;
    // comfort: средний дискомфорт (0+100)/2, глобальный max 100,
    // средний per-team max (0+100)/2
    let expected_comfort = 50.0 * cfg.role_discomfort_weight
        + 100.0 * cfg.max_role_discomfort_weight
        + 50.0 * cfg.team_max_pain_weight;

    assert!(
        (obj.balance - expected_balance).abs() < 1e-9,
        "balance {} != expected {}",
        obj.balance,
        expected_balance
    );
    assert!(
        (obj.comfort - expected_comfort).abs() < 1e-9,
        "comfort {} != expected {}",
        obj.comfort,
        expected_comfort
    );
}

/// Инвариант breakdown: взвешенная сумма сырых членов точно равна
/// итоговым balance/comfort.
#[test]
fn breakdown_terms_sum_to_objectives() {
    let ctx = bench_api::synthetic_context(6, 17);
    for seed in 0..4u64 {
        let sol = bench_api::randomized_solution(&ctx, seed);
        let b = calculate_objective_breakdown(&sol.0, &ctx.0);
        let cfg = &ctx.0.config;
        let balance = b.total_rating_std * cfg.team_total_balance_weight
            + b.gap_penalty * cfg.max_team_gap_weight
            + b.mmr_std * cfg.average_mmr_balance_weight
            + b.role_line_std * cfg.role_line_balance_weight
            + b.intra_team_std_avg * cfg.intra_team_std_weight
            + b.internal_role_spread_avg * cfg.internal_role_spread_weight
            + b.tank_adjacent_gap_penalty * cfg.tank_gap_weight
            + b.tank_std * cfg.tank_std_weight
            + b.effective_total_std * cfg.effective_total_std_weight;
        let comfort = b.avg_discomfort * cfg.role_discomfort_weight
            + b.global_max_pain * cfg.max_role_discomfort_weight
            + b.avg_team_max_pain * cfg.team_max_pain_weight
            + b.avg_subrole_collisions * cfg.sub_role_collision_weight;
        assert!(
            (balance - b.balance).abs() < 1e-9,
            "balance breakdown mismatch"
        );
        assert!(
            (comfort - b.comfort).abs() < 1e-9,
            "comfort breakdown mismatch"
        );

        // breakdown согласован с горячим путём
        let obj = calculate_objectives(&sol.0, &ctx.0);
        assert_eq!(obj.balance.to_bits(), b.balance.to_bits());
        assert_eq!(obj.comfort.to_bits(), b.comfort.to_bits());
    }
}

/// Маржинальные penalty непрерывны (Липшицева константа = старшая ставка):
/// прежние "ступеньки" имели скачки значения в точках порогов.
#[test]
fn gap_penalties_are_continuous() {
    let mut g = 0.0f64;
    while g < 400.0 {
        let delta = 0.01;
        let jump_total = (calculate_gap_penalty(g + delta) - calculate_gap_penalty(g)).abs();
        assert!(
            jump_total <= 40.0 * delta + 1e-9,
            "calculate_gap_penalty jump at {g}: {jump_total}"
        );
        let jump_tank = (tank_gap_penalty(g + delta) - tank_gap_penalty(g)).abs();
        assert!(
            jump_tank <= 20.0 * delta + 1e-9,
            "tank_gap_penalty jump at {g}: {jump_tank}"
        );
        g += delta * 10.0;
    }
}

/// Клон-эквивариантность: дублирование турнира (каждый игрок и каждая
/// команда ×2) не меняет нормированные на команду члены objective.
/// До нормализации sum-члены удваивались, и веса не переносились
/// между размерами турниров.
#[test]
fn per_team_terms_are_clone_equivariant() {
    let base_players = vec![
        player("a", "Tank", &[("Tank", 1000)], &["Tank"]),
        player("b", "Damage", &[("Damage", 900)], &["Damage", "Tank"]),
        player("c", "Damage", &[("Damage", 600)], &["Tank", "Damage"]),
        player("d", "Tank", &[("Tank", 500)], &["Tank"]),
        player("e", "Damage", &[("Damage", 800)], &["Damage"]),
        player("f", "Damage", &[("Damage", 700)], &["Damage"]),
    ];
    let mask: HashMap<String, usize> =
        [("Tank".to_string(), 1usize), ("Damage".to_string(), 2usize)]
            .into_iter()
            .collect();

    let ctx_small = Context::from_request(NativeRequest {
        players: base_players.clone(),
        num_teams: 2,
        seed: 1,
        mask: mask.clone(),
        config: regression_config(),
    })
    .expect("small ctx");
    // Дублируем игроков с новыми uuid
    let mut doubled = base_players.clone();
    for p in &base_players {
        let mut clone = p.clone();
        clone.uuid = format!("{}-copy", p.uuid);
        doubled.push(clone);
    }
    let ctx_big = Context::from_request(NativeRequest {
        players: doubled,
        num_teams: 4,
        seed: 1,
        mask,
        config: regression_config(),
    })
    .expect("big ctx");

    // Роли отсортированы: Damage=0, Tank=1. Решение: (a | b,c), (d | e,f)
    let sol_small: Solution = vec![
        TeamState {
            id: 1,
            roster: vec![vec![1, 2], vec![0]],
        },
        TeamState {
            id: 2,
            roster: vec![vec![4, 5], vec![3]],
        },
    ];
    // Копии игроков в ctx_big имеют индексы 6..11 в том же порядке
    let sol_big: Solution = vec![
        TeamState {
            id: 1,
            roster: vec![vec![1, 2], vec![0]],
        },
        TeamState {
            id: 2,
            roster: vec![vec![4, 5], vec![3]],
        },
        TeamState {
            id: 3,
            roster: vec![vec![7, 8], vec![6]],
        },
        TeamState {
            id: 4,
            roster: vec![vec![10, 11], vec![9]],
        },
    ];

    let small = calculate_objective_breakdown(&sol_small, &ctx_small);
    let big = calculate_objective_breakdown(&sol_big, &ctx_big);

    let close = |x: f64, y: f64| (x - y).abs() < 1e-9;
    assert!(close(small.avg_discomfort, big.avg_discomfort));
    assert!(close(small.intra_team_std_avg, big.intra_team_std_avg));
    assert!(close(
        small.internal_role_spread_avg,
        big.internal_role_spread_avg
    ));
    assert!(close(
        small.avg_subrole_collisions,
        big.avg_subrole_collisions
    ));
    assert!(close(small.avg_team_max_pain, big.avg_team_max_pain));
    assert!(close(small.gap_penalty, big.gap_penalty));
    assert!(close(
        small.tank_adjacent_gap_penalty,
        big.tank_adjacent_gap_penalty
    ));
}

#[test]
fn knee_scores_weights_shift_priority() {
    // Невырожденный фронт: A — лучший баланс/худший комфорт, C — наоборот, B — колено.
    let objectives = vec![
        Objectives {
            balance: 0.0,
            comfort: 10.0,
        },
        Objectives {
            balance: 5.0,
            comfort: 5.0,
        },
        Objectives {
            balance: 10.0,
            comfort: 0.0,
        },
    ];

    // Чистый вес баланса → лучший баланс (idx 0) ранжируется первым.
    let balance_tilt = knee_scores(&objectives, 1.0, 0.0);
    assert!(
        balance_tilt[0] < balance_tilt[1] && balance_tilt[1] < balance_tilt[2],
        "balance-weighted scores must rank best-balance first"
    );

    // Чистый вес комфорта → лучший комфорт (idx 2) первым.
    let comfort_tilt = knee_scores(&objectives, 0.0, 1.0);
    assert!(
        comfort_tilt[2] < comfort_tilt[1] && comfort_tilt[1] < comfort_tilt[0],
        "comfort-weighted scores must rank best-comfort first"
    );

    // Нейтральные веса (1,1) = прежняя формула sqrt(b²+c²) → колено (idx 1) первым.
    let neutral = knee_scores(&objectives, 1.0, 1.0);
    assert!(
        neutral[1] < neutral[0] && neutral[1] < neutral[2],
        "neutral weights keep the knee point first (legacy behaviour)"
    );
}

/// Knee-ранжирование: на содержательном фронте порядок — по расстоянию
/// до идеала; на вырожденном (две точки) — лексикографический фолбэк.
#[test]
fn knee_order_ranks_by_distance_with_degenerate_fallback() {
    // 5 точек: «колено» (0.2, 0.2) ближе всех к идеалу, несмотря на то,
    // что по сумме (0.4) оно равно точкам (0.0,0.4)/(0.4,0.0) не было бы
    // строго лучше краёв при сумме norm_b+norm_c.
    let objectives = vec![
        obj(0.0, 1.0),
        obj(0.2, 0.2),
        obj(1.0, 0.0),
        obj(0.1, 0.6),
        obj(0.6, 0.1),
    ];
    let signatures: Vec<u64> = (0..objectives.len() as u64).collect();
    let scores = knee_scores(&objectives, 1.0, 1.0);
    let order = knee_order(&objectives, &signatures, &scores);
    assert_eq!(order[0], 1, "knee point must rank first");

    // Вырожденный двухточечный фронт: сумма нормированных целей у обеих
    // точек равна 1.0 — порядок должен решаться лексикографически.
    let two = vec![obj(10.0, 500.0), obj(20.0, 100.0)];
    let sigs = vec![7u64, 3u64];
    let two_scores = knee_scores(&two, 1.0, 1.0);
    let two_order = knee_order(&two, &sigs, &two_scores);
    assert_eq!(
        two_order,
        vec![0, 1],
        "fallback must pick lower balance first"
    );
}

/// Элиты — это колено + якоря best-balance/best-comfort, а не топ-3 по
/// скаляру (раньше все элиты кучковались у колена).
#[test]
fn elites_cover_knee_and_both_anchors() {
    let ctx = quad_ctx();
    let entries = vec![
        ArchiveEntry::new(obj(0.0, 10.0), quad_solution(0, 1, 2, 3)),
        ArchiveEntry::new(obj(2.0, 2.0), quad_solution(0, 3, 2, 1)),
        ArchiveEntry::new(obj(10.0, 0.0), quad_solution(1, 0, 3, 2)),
        ArchiveEntry::new(obj(3.0, 3.5), quad_solution(3, 0, 1, 2)),
    ];
    let _ = &ctx;
    let elites = archive_select_elites(&entries, 3);
    let sigs: HashSet<u64> = elites.iter().map(|e| e.sig).collect();
    assert!(
        sigs.contains(&entries[0].sig),
        "best-balance anchor missing"
    );
    assert!(
        sigs.contains(&entries[2].sig),
        "best-comfort anchor missing"
    );
    assert!(sigs.contains(&entries[1].sig), "knee point missing");
}

#[test]
fn objectives_scratch_matches_fresh_computation() {
    let ctx = bench_api::synthetic_context(6, 11);
    let mut scratch = ObjectiveScratch::default();
    for seed in 0..8u64 {
        let sol = bench_api::randomized_solution(&ctx, seed);
        let stats: Vec<TeamStats> = sol
            .0
            .iter()
            .map(|t| calculate_team_stats(&ctx.0, t))
            .collect();
        let fresh = calculate_objectives_from_stats(&stats, &ctx.0);
        let scratched = calculate_objectives_with_scratch(&stats, &ctx.0, &mut scratch);
        assert_eq!(fresh.balance.to_bits(), scratched.balance.to_bits());
        assert_eq!(fresh.comfort.to_bits(), scratched.comfort.to_bits());
    }
}

// --- NSGA-II примитивы ------------------------------------------------

fn obj(balance: f64, comfort: f64) -> Objectives {
    Objectives { balance, comfort }
}

#[test]
fn dominates_textbook_cases() {
    assert!(dominates(&obj(1.0, 1.0), &obj(2.0, 2.0)));
    assert!(dominates(&obj(1.0, 2.0), &obj(2.0, 2.0)));
    assert!(!dominates(&obj(1.0, 3.0), &obj(2.0, 2.0))); // несравнимы
    assert!(!dominates(&obj(2.0, 2.0), &obj(1.0, 1.0)));
    assert!(!dominates(&obj(1.0, 1.0), &obj(1.0, 1.0))); // равные не доминируют
}

#[test]
fn fast_non_dominated_sort_builds_expected_fronts() {
    let objectives = vec![
        obj(1.0, 4.0), // фронт 0
        obj(4.0, 1.0), // фронт 0
        obj(2.0, 5.0), // фронт 1 (доминируется [0])
        obj(5.0, 5.0), // фронт 2 (доминируется всеми)
    ];
    let fronts = fast_non_dominated_sort(&objectives);
    assert_eq!(fronts.len(), 3);
    let mut f0 = fronts[0].clone();
    f0.sort_unstable();
    assert_eq!(f0, vec![0, 1]);
    assert_eq!(fronts[1], vec![2]);
    assert_eq!(fronts[2], vec![3]);
}

#[test]
fn crowding_distance_marks_extremes_infinite() {
    let objectives = vec![obj(1.0, 5.0), obj(3.0, 3.0), obj(5.0, 1.0)];
    let front = vec![0, 1, 2];
    let distances = crowding_distance(&front, &objectives);
    assert!(distances[0].is_infinite());
    assert!(distances[2].is_infinite());
    assert!(distances[1].is_finite());
    assert!(distances[1] > 0.0);
}

// --- Архив -------------------------------------------------------------

/// 2 команды × (Tank 1 + Damage 1), 4 игрока — мир, в котором существуют
/// решения с разными каноническими сигнатурами (в мире из одной роли с
/// capacity 1 любые решения совпадают с точностью до перестановки команд).
fn quad_ctx() -> Context {
    let request = NativeRequest {
        players: vec![
            player("a", "Tank", &[("Tank", 1000)], &["Tank"]),
            player("b", "Damage", &[("Damage", 900)], &["Damage"]),
            player("c", "Tank", &[("Tank", 800)], &["Tank"]),
            player("d", "Damage", &[("Damage", 700)], &["Damage"]),
        ],
        num_teams: 2,
        seed: 1,
        mask: [("Tank".to_string(), 1usize), ("Damage".to_string(), 1usize)]
            .into_iter()
            .collect(),
        config: regression_config(),
    };
    Context::from_request(request).expect("valid quad ctx")
}

/// Решение для quad_ctx: (tank1, dmg1 | tank2, dmg2). Роли отсортированы:
/// Damage = 0, Tank = 1.
fn quad_solution(tank1: usize, dmg1: usize, tank2: usize, dmg2: usize) -> Solution {
    vec![
        TeamState {
            id: 1,
            roster: vec![vec![dmg1], vec![tank1]],
        },
        TeamState {
            id: 2,
            roster: vec![vec![dmg2], vec![tank2]],
        },
    ]
}

#[test]
fn archive_update_semantics() {
    let ctx = quad_ctx();
    let mut archive: Vec<ArchiveEntry> = Vec::new();
    let mut sigs: HashSet<u64> = HashSet::new();

    let base = ArchiveEntry::new(obj(1.0, 1.0), quad_solution(0, 1, 2, 3));
    assert!(archive_update(&mut archive, &mut sigs, base.clone(), &ctx));

    // Дубликат по сигнатуре отклоняется (в т.ч. с переставленными командами)
    assert!(!archive_update(&mut archive, &mut sigs, base.clone(), &ctx));
    let permuted = ArchiveEntry::new(obj(0.1, 0.1), quad_solution(2, 3, 0, 1));
    assert_eq!(
        permuted.sig, base.sig,
        "signature must be team-order invariant"
    );
    assert!(!archive_update(&mut archive, &mut sigs, permuted, &ctx));

    // Доминируемый кандидат отклоняется (другое решение, хуже по обоим)
    let dominated = ArchiveEntry::new(obj(2.0, 2.0), quad_solution(0, 3, 2, 1));
    assert!(!archive_update(&mut archive, &mut sigs, dominated, &ctx));
    assert_eq!(archive.len(), 1);

    // Равные objectives при другой сигнатуре — оба остаются
    let equal = ArchiveEntry::new(obj(1.0, 1.0), quad_solution(0, 3, 2, 1));
    assert!(archive_update(&mut archive, &mut sigs, equal, &ctx));
    assert_eq!(archive.len(), 2);

    // Доминирующий кандидат вытесняет всех доминируемых
    let dominating = ArchiveEntry::new(obj(0.5, 0.5), quad_solution(1, 0, 3, 2));
    assert!(archive_update(
        &mut archive,
        &mut sigs,
        dominating.clone(),
        &ctx
    ));
    assert_eq!(archive.len(), 1);
    assert_eq!(archive[0].sig, dominating.sig);
    assert_eq!(sigs.len(), 1);
}

#[test]
fn analyze_repair_need_detects_breakage() {
    let ctx = quad_ctx();
    // Дубликат игрока 0, игроки 1 и 3 отсутствуют, превышение capacity
    // в Tank-слоте команды 1, битый индекс 99.
    let sol: Solution = vec![
        TeamState {
            id: 1,
            roster: vec![vec![2], vec![0, 0, 99]],
        },
        TeamState {
            id: 2,
            roster: vec![vec![], vec![]],
        },
    ];
    let need = analyze_repair_need(&sol, &ctx);
    assert!(need.needs_repair());
    assert_eq!(need.duplicate_assignments, 1);
    assert_eq!(need.missing_players, 2);
    assert_eq!(need.over_capacity_assignments, 2);
    assert_eq!(need.invalid_player_refs, 1);

    let clean = quad_solution(0, 1, 2, 3);
    assert!(!analyze_repair_need(&clean, &ctx).needs_repair());
}

// --- Property-тесты ----------------------------------------------------

use proptest::prelude::*;

/// Случайный валидный сценарий, детерминированный по seed.
fn random_scenario(seed: u64) -> Context {
    let mut rng = MooRng::seed_from_u64(seed);
    let all_roles = ["Tank", "Damage", "Support"];
    let num_roles = rng.random_range(1..=3usize);
    let mut roles: Vec<&str> = all_roles.to_vec();
    roles.shuffle(&mut rng);
    roles.truncate(num_roles);
    let mask: HashMap<String, usize> = roles
        .iter()
        .map(|r| (r.to_string(), rng.random_range(1..=2usize)))
        .collect();
    let num_teams = rng.random_range(2..=4usize);
    let slots: usize = mask.values().sum::<usize>() * num_teams;

    let players: Vec<PlayerSpec> = (0..slots)
        .map(|i| {
            let seed_role = roles[rng.random_range(0..roles.len())].to_string();
            let mut ratings = HashMap::new();
            for r in &roles {
                if *r == seed_role || rng.random_bool(0.7) {
                    ratings.insert(r.to_string(), rng.random_range(100..2000));
                }
            }
            let mut prefs: Vec<String> = roles
                .iter()
                .filter(|_| rng.random_bool(0.7))
                .map(|r| r.to_string())
                .collect();
            prefs.shuffle(&mut rng);
            PlayerSpec {
                uuid: format!("p{i}"),
                name: format!("p{i}"),
                ratings,
                preferences: prefs,
                subclasses: HashMap::new(),
                is_captain: rng.random_bool(0.15),
                is_flex: rng.random_bool(0.1),
                seed_role: Some(seed_role),
            }
        })
        .collect();

    let mut config = regression_config();
    config.use_captains = rng.random_bool(0.5);
    let request = NativeRequest {
        players,
        num_teams,
        seed,
        mask,
        config,
    };
    Context::from_request(request).expect("random scenario must be valid")
}

fn random_broken_solution(ctx: &Context, rng: &mut MooRng) -> Solution {
    let mut sol = create_empty_solution(ctx);
    let p_count = ctx.players.len();
    for t in 0..ctx.num_teams {
        for r in 0..ctx.roles.len() {
            let fill = rng.random_range(0..=ctx.capacities[r] + 1);
            for _ in 0..fill {
                let p = if rng.random_bool(0.05) {
                    p_count + rng.random_range(0..3)
                } else {
                    rng.random_range(0..p_count)
                };
                sol[t].roster[r].push(p);
            }
        }
    }
    sol
}

fn assert_feasible(sol: &Solution, ctx: &Context) {
    let mut seen = vec![0usize; ctx.players.len()];
    assert_eq!(sol.len(), ctx.num_teams);
    for (t, team) in sol.iter().enumerate() {
        assert_eq!(team.roster.len(), ctx.roles.len());
        for (r, roster) in team.roster.iter().enumerate() {
            assert_eq!(
                roster.len(),
                ctx.capacities[r],
                "team {t} role {r} must be exactly at capacity"
            );
            for &p in roster {
                assert!(p < ctx.players.len(), "invalid player index {p}");
                seen[p] += 1;
            }
        }
    }
    for (p, &n) in seen.iter().enumerate() {
        assert_eq!(n, 1, "player {p} placed {n} times");
    }
    if ctx.config.use_captains {
        for (p, pl) in ctx.players.iter().enumerate() {
            if let Some(t) = pl.captain_team {
                assert!(
                    sol[t].roster[pl.seed_role].contains(&p),
                    "locked captain {p} must sit at (team {t}, seed role)"
                );
            }
        }
    }
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(64))]

    #[test]
    fn prop_ensure_feasibility_repairs_any_solution(seed in any::<u64>()) {
        let ctx = random_scenario(seed);
        let mut rng = MooRng::seed_from_u64(seed ^ 0xDEAD_BEEF);
        let mut sol = random_broken_solution(&ctx, &mut rng);
        ensure_feasibility(&mut sol, &ctx, &mut rng);
        assert_feasible(&sol, &ctx);

        // Идемпотентность с точностью до сигнатуры
        let sig_first = signature(&sol);
        ensure_feasibility(&mut sol, &ctx, &mut rng);
        prop_assert_eq!(sig_first, signature(&sol));
    }

    #[test]
    fn prop_crossover_with_repair_preserves_players(seed in any::<u64>()) {
        let ctx = random_scenario(seed);
        let mut rng = MooRng::seed_from_u64(seed ^ 0xC0FF_EE00);
        let mut a = create_random_solution(&ctx, &mut rng);
        ensure_feasibility(&mut a, &ctx, &mut rng);
        let mut b = create_random_solution(&ctx, &mut rng);
        ensure_feasibility(&mut b, &ctx, &mut rng);
        let mut child = crossover_role_lines(&a, &b, &ctx, &mut rng);
        ensure_feasibility(&mut child, &ctx, &mut rng);
        assert_feasible(&child, &ctx);

        let mut team_child = crossover_team_preserving(&a, &b, &ctx, &mut rng);
        ensure_feasibility(&mut team_child, &ctx, &mut rng);
        assert_feasible(&team_child, &ctx);
    }

    /// Контракт polish: результат feasible и не хуже входа ни по одной цели.
    #[test]
    fn prop_polish_never_worsens_and_stays_feasible(seed in any::<u64>()) {
        let ctx = random_scenario(seed);
        let mut rng = MooRng::seed_from_u64(seed ^ 0x090_1158);
        let mut sol = create_random_solution(&ctx, &mut rng);
        ensure_feasibility(&mut sol, &ctx, &mut rng);
        let before = calculate_objectives(&sol, &ctx);
        let polished = polish_pareto(&sol, &ctx, 10);
        assert_feasible(&polished, &ctx);
        let after = calculate_objectives(&polished, &ctx);
        prop_assert!(after.balance <= before.balance + 1e-6);
        prop_assert!(after.comfort <= before.comfort + 1e-6);
    }

    #[test]
    fn prop_signature_invariant_to_team_order(seed in any::<u64>()) {
        let ctx = random_scenario(seed);
        let mut rng = MooRng::seed_from_u64(seed ^ 0x5160_0000);
        let mut sol = create_random_solution(&ctx, &mut rng);
        ensure_feasibility(&mut sol, &ctx, &mut rng);
        let sig_original = signature(&sol);

        // Перестановка команд + перемешивание внутри ростеров
        let mut permuted = sol.clone();
        permuted.rotate_left(1);
        for team in &mut permuted {
            for roster in &mut team.roster {
                roster.reverse();
            }
        }
        prop_assert_eq!(sig_original, signature(&permuted));

        // Обмен двух разных игроков одной роли между командами меняет
        // сигнатуру — кроме вырожденного мира с 1 слотом на команду,
        // где такой обмен эквивалентен перестановке команд.
        let slots_per_team: usize = ctx.capacities.iter().sum();
        if slots_per_team >= 2 {
            'outer: for r in 0..ctx.roles.len() {
                for i in 0..sol.len() {
                    for j in (i + 1)..sol.len() {
                        if sol[i].roster[r].is_empty() || sol[j].roster[r].is_empty() {
                            continue;
                        }
                        let mut swapped = sol.clone();
                        swap_players(&mut swapped, i, r, 0, j, r, 0);
                        prop_assert_ne!(sig_original, signature(&swapped));
                        break 'outer;
                    }
                }
            }
        }
    }

    /// Обоснование оптимизации диагностики (P0-6): если repair не нужен,
    /// ensure_feasibility не меняет сигнатуру (только канонизирует порядок).
    #[test]
    fn prop_clean_solution_signature_stable_through_repair(seed in any::<u64>()) {
        let ctx = random_scenario(seed);
        let mut rng = MooRng::seed_from_u64(seed ^ 0x00C1_EA00);
        let mut sol = create_random_solution(&ctx, &mut rng);
        ensure_feasibility(&mut sol, &ctx, &mut rng);
        let need = analyze_repair_need(&sol, &ctx);
        prop_assert!(!need.needs_repair(), "repaired solution must be clean");
        let sig_before = signature(&sol);
        ensure_feasibility(&mut sol, &ctx, &mut rng);
        prop_assert_eq!(sig_before, signature(&sol));
    }
}

#[test]
fn best_variant_regression_fixture_metrics() {
    let request = regression_request();
    let original_players: HashMap<String, PlayerSpec> = request
        .players
        .iter()
        .cloned()
        .map(|player| (player.uuid.clone(), player))
        .collect();
    let ctx = Context::from_request(request).expect("regression fixture should be valid");
    let response = run_optimizer(&ctx, None).expect("optimizer should return variants");

    assert!(
        !response.variants.is_empty(),
        "expected at least one variant"
    );
    assert!(
        response.repair_diagnostics.crossover_children > 0,
        "expected crossover diagnostics to capture generated children"
    );
    let best = variant_metrics(&response.variants[0], &ctx, &original_players);
    assert_eq!(
        best.off_role_count, 0,
        "top variant should preserve zero off-roles on regression fixture"
    );
    assert!(
        best.mmr_std_dev <= 2.0 + 1e-9,
        "top variant mmr stddev regressed: got {}",
        best.mmr_std_dev
    );
}
