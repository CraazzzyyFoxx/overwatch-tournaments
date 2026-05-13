use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use rand::prelude::*;
use rand::rngs::StdRng;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use std::collections::hash_map::DefaultHasher;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::hash::{Hash, Hasher};

type Solution = Vec<TeamState>;

// --- OW2 & MOO Config Defaults ---
fn default_tank_impact() -> f64 {
    1.4
}
fn default_dps_impact() -> f64 {
    1.0
}
fn default_support_impact() -> f64 {
    1.1
}
fn default_tank_gap_weight() -> f64 {
    2.0
}
fn default_tank_std_weight() -> f64 {
    1.5
}
fn default_eff_total_std_weight() -> f64 {
    1.2
}
fn default_intra_team_std_weight() -> f64 {
    0.7
}
fn default_internal_role_spread_weight() -> f64 {
    0.3
}
fn default_convergence_patience() -> usize {
    0
}
fn default_convergence_epsilon() -> f64 {
    0.005
}
fn default_mut_rate_min() -> f64 {
    0.15
}
fn default_mut_rate_max() -> f64 {
    0.65
}
fn default_island_count() -> usize {
    4
}
fn default_polish_max_passes() -> usize {
    50
}
fn default_greedy_seed_count() -> usize {
    3
}
fn default_stagnation_kick_patience() -> usize {
    15
}
fn default_crossover_rate() -> f64 {
    0.85
}

const DEFAULT_ARCHIVE_LIMIT: usize = 96;
const MAX_ARCHIVE_LIMIT: usize = 200;
const ARCHIVE_ELITE_COUNT: usize = 3;
const ARCHIVE_SCORE_KEEP: usize = 5;
const MIGRATION_INTERVAL_GENS: usize = 20;
const MIGRATION_TOP_K: usize = 3;

#[derive(Debug, Clone, Deserialize)]
struct ConfigSpec {
    population_size: usize,
    generation_count: usize,
    mutation_rate: f64,
    mutation_strength: usize,
    max_result_variants: usize,
    average_mmr_balance_weight: f64,
    team_total_balance_weight: f64,
    max_team_gap_weight: f64,
    role_discomfort_weight: f64,
    intra_team_variance_weight: f64,
    max_role_discomfort_weight: f64,
    role_line_balance_weight: f64,
    role_spread_weight: f64,
    sub_role_collision_weight: f64,
    use_captains: bool,
    #[serde(default = "default_tank_impact")]
    tank_impact_weight: f64,
    #[serde(default = "default_dps_impact")]
    dps_impact_weight: f64,
    #[serde(default = "default_support_impact")]
    support_impact_weight: f64,
    #[serde(default = "default_tank_gap_weight")]
    tank_gap_weight: f64,
    #[serde(default = "default_tank_std_weight")]
    tank_std_weight: f64,
    #[serde(default = "default_eff_total_std_weight")]
    effective_total_std_weight: f64,
    #[serde(default = "default_intra_team_std_weight")]
    intra_team_std_weight: f64,
    #[serde(default = "default_internal_role_spread_weight")]
    internal_role_spread_weight: f64,
    #[serde(default = "default_convergence_patience")]
    convergence_patience: usize,
    #[serde(default = "default_convergence_epsilon")]
    convergence_epsilon: f64,
    #[serde(default = "default_mut_rate_min")]
    mutation_rate_min: f64,
    #[serde(default = "default_mut_rate_max")]
    mutation_rate_max: f64,
    #[serde(default = "default_island_count")]
    island_count: usize,
    #[serde(default = "default_polish_max_passes")]
    polish_max_passes: usize,
    #[serde(default = "default_greedy_seed_count")]
    greedy_seed_count: usize,
    #[serde(default = "default_stagnation_kick_patience")]
    stagnation_kick_patience: usize,
    #[serde(default = "default_crossover_rate")]
    crossover_rate: f64,
}

#[derive(Debug, Clone, Deserialize)]
struct PlayerSpec {
    uuid: String,
    #[allow(dead_code)]
    name: String,
    ratings: HashMap<String, i32>,
    preferences: Vec<String>,
    subclasses: HashMap<String, String>,
    is_captain: bool,
    is_flex: bool,
    seed_role: Option<String>,
}

#[derive(Debug, Deserialize)]
struct NativeRequest {
    players: Vec<PlayerSpec>,
    num_teams: usize,
    seed: u64,
    mask: HashMap<String, usize>,
    config: ConfigSpec,
}

#[derive(Debug, Clone)]
struct PlayerData {
    uuid: String,
    ratings: Vec<i32>,
    can_play: Vec<bool>,
    discomfort: Vec<i32>,
    subclasses: Vec<Option<String>>,
    is_captain: bool,
    first_preference: Option<usize>,
    seed_role: usize,
    captain_team: Option<usize>,
}

#[derive(Debug, Clone)]
struct Context {
    roles: Vec<String>,
    capacities: Vec<usize>,
    num_teams: usize,
    seed: u64,
    players: Vec<PlayerData>,
    config: ConfigSpec,
    tank_role_idx: Option<usize>,
    dps_role_idx: Option<usize>,
    support_role_idx: Option<usize>,
}

#[derive(Debug, Clone)]
struct TeamState {
    id: usize,
    roster: Vec<Vec<usize>>,
}

#[derive(Debug, Clone)]
struct TeamStats {
    mmr: f64,
    total_rating: f64,
    discomfort: f64,
    intra_std: f64,
    max_pain: i32,
    subrole_collisions: i32,
    role_totals: Vec<f64>,
    role_counts: Vec<usize>,
    internal_role_spread: f64,
}

#[derive(Debug, Clone, Copy, Serialize)]
struct Objectives {
    balance: f64,
    comfort: f64,
}

#[derive(Debug, Serialize)]
struct TeamResponse {
    id: usize,
    roster: BTreeMap<String, Vec<String>>,
}

#[derive(Debug, Serialize)]
struct VariantResponse {
    teams: Vec<TeamResponse>,
    balance: f64,
    comfort: f64,
    balance_norm: f64,
    comfort_norm: f64,
    score: f64,
}

#[derive(Debug, Serialize)]
struct NativeResponse {
    variants: Vec<VariantResponse>,
    repair_diagnostics: RepairDiagnostics,
}

#[derive(Debug, Clone, Copy, Default, Serialize)]
struct RepairDiagnostics {
    offspring_total: usize,
    crossover_children: usize,
    crossover_children_requiring_repair: usize,
    crossover_children_changed_by_repair: usize,
    crossover_duplicate_assignments_total: usize,
    crossover_missing_players_total: usize,
    crossover_over_capacity_total: usize,
    crossover_invalid_player_refs_total: usize,
    crossover_captain_lock_conflicts_total: usize,
    mutation_only_children: usize,
    mutation_only_children_requiring_repair: usize,
    mutation_only_children_changed_by_repair: usize,
}

#[derive(Debug, Clone, Copy, Default)]
struct RepairNeed {
    duplicate_assignments: usize,
    missing_players: usize,
    over_capacity_assignments: usize,
    invalid_player_refs: usize,
    captain_lock_conflicts: usize,
}

impl RepairNeed {
    fn needs_repair(&self) -> bool {
        self.duplicate_assignments > 0
            || self.missing_players > 0
            || self.over_capacity_assignments > 0
            || self.invalid_player_refs > 0
            || self.captain_lock_conflicts > 0
    }
}

impl RepairDiagnostics {
    fn record_child(
        &mut self,
        crossed: bool,
        mutated: bool,
        repair_need: RepairNeed,
        changed_by_repair: bool,
    ) {
        if !crossed && !mutated {
            return;
        }

        self.offspring_total += 1;
        if crossed {
            self.crossover_children += 1;
            if repair_need.needs_repair() {
                self.crossover_children_requiring_repair += 1;
            }
            if changed_by_repair {
                self.crossover_children_changed_by_repair += 1;
            }
            self.crossover_duplicate_assignments_total += repair_need.duplicate_assignments;
            self.crossover_missing_players_total += repair_need.missing_players;
            self.crossover_over_capacity_total += repair_need.over_capacity_assignments;
            self.crossover_invalid_player_refs_total += repair_need.invalid_player_refs;
            self.crossover_captain_lock_conflicts_total += repair_need.captain_lock_conflicts;
        } else if mutated {
            self.mutation_only_children += 1;
            if repair_need.needs_repair() {
                self.mutation_only_children_requiring_repair += 1;
            }
            if changed_by_repair {
                self.mutation_only_children_changed_by_repair += 1;
            }
        }
    }

    fn merge(&mut self, other: &Self) {
        self.offspring_total += other.offspring_total;
        self.crossover_children += other.crossover_children;
        self.crossover_children_requiring_repair += other.crossover_children_requiring_repair;
        self.crossover_children_changed_by_repair += other.crossover_children_changed_by_repair;
        self.crossover_duplicate_assignments_total += other.crossover_duplicate_assignments_total;
        self.crossover_missing_players_total += other.crossover_missing_players_total;
        self.crossover_over_capacity_total += other.crossover_over_capacity_total;
        self.crossover_invalid_player_refs_total += other.crossover_invalid_player_refs_total;
        self.crossover_captain_lock_conflicts_total += other.crossover_captain_lock_conflicts_total;
        self.mutation_only_children += other.mutation_only_children;
        self.mutation_only_children_requiring_repair +=
            other.mutation_only_children_requiring_repair;
        self.mutation_only_children_changed_by_repair +=
            other.mutation_only_children_changed_by_repair;
    }
}

impl Context {
    fn from_request(request: NativeRequest) -> Result<Self, String> {
        let mut roles: Vec<String> = request
            .mask
            .iter()
            .filter_map(|(role, count)| if *count > 0 { Some(role.clone()) } else { None })
            .collect();
        roles.sort();

        if roles.is_empty() {
            return Err("role_mask cannot be empty".to_string());
        }

        let role_index: HashMap<&str, usize> = roles
            .iter()
            .enumerate()
            .map(|(index, role)| (role.as_str(), index))
            .collect();

        let capacities: Vec<usize> = roles
            .iter()
            .map(|role| request.mask.get(role).copied().unwrap_or_default())
            .collect();

        let tank_role_idx = roles.iter().position(|r| r.eq_ignore_ascii_case("Tank"));
        let dps_role_idx = roles.iter().position(|r| r.eq_ignore_ascii_case("Damage"));
        let support_role_idx = roles.iter().position(|r| r.eq_ignore_ascii_case("Support"));

        let mut players = Vec::with_capacity(request.players.len());
        for player in request.players {
            let seed_role_name = player
                .seed_role
                .as_deref()
                .ok_or_else(|| format!("player {} is missing seed_role", player.uuid))?;
            let seed_role = role_index.get(seed_role_name).copied().ok_or_else(|| {
                format!(
                    "player {} has unknown seed_role {}",
                    player.uuid, seed_role_name
                )
            })?;

            let mut ratings = Vec::with_capacity(roles.len());
            let mut can_play = Vec::with_capacity(roles.len());
            let mut discomfort = Vec::with_capacity(roles.len());
            let mut subclasses = Vec::with_capacity(roles.len());

            for role in &roles {
                let rating = player.ratings.get(role).copied().unwrap_or_default();
                let role_is_playable = player.ratings.contains_key(role);
                ratings.push(rating);
                can_play.push(role_is_playable);
                subclasses.push(player.subclasses.get(role).cloned());

                let pain = if player.is_flex && role_is_playable {
                    0
                } else if let Some(position) = player
                    .preferences
                    .iter()
                    .position(|preference| preference == role)
                {
                    (position as i32) * 100
                } else if role_is_playable {
                    1000
                } else {
                    5000
                };
                discomfort.push(pain);
            }

            let first_preference = player
                .preferences
                .first()
                .and_then(|role| role_index.get(role.as_str()).copied());

            players.push(PlayerData {
                uuid: player.uuid,
                ratings,
                can_play,
                discomfort,
                subclasses,
                is_captain: player.is_captain,
                first_preference,
                seed_role,
                captain_team: None,
            });
        }

        // Фиксируем капитанов за командами: один капитан на одну команду.
        // Каждый залоченный капитан сидит в своём seed_role на captain_team.
        // Если капитанов больше, чем команд, лишние остаются is_captain=true, но без лока (captain_team=None).
        // Если капитанов меньше, чем команд, часть команд остаётся без залоченного капитана.
        if request.config.use_captains && request.num_teams > 0 {
            let mut captain_indices: Vec<usize> = (0..players.len())
                .filter(|&i| players[i].is_captain)
                .collect();
            // Детерминированный порядок: сперва по seed_role, затем по uuid
            captain_indices.sort_by(|&a, &b| {
                players[a]
                    .seed_role
                    .cmp(&players[b].seed_role)
                    .then_with(|| players[a].uuid.cmp(&players[b].uuid))
            });
            for (i, p) in captain_indices.iter().copied().enumerate() {
                if i < request.num_teams {
                    players[p].captain_team = Some(i);
                }
            }
        }

        Ok(Self {
            roles,
            capacities,
            num_teams: request.num_teams,
            seed: request.seed,
            players,
            config: request.config,
            tank_role_idx,
            dps_role_idx,
            support_role_idx,
        })
    }
}

fn sample_stdev_from_sums(sum_x: f64, sum_x2: f64, count: usize) -> f64 {
    if count < 2 {
        return 0.0;
    }
    let variance = (sum_x2 - (sum_x * sum_x) / count as f64) / (count as f64 - 1.0);
    if variance <= 0.0 {
        return 0.0;
    }
    variance.sqrt()
}

fn calculate_gap_penalty(max_team_gap: f64) -> f64 {
    if max_team_gap <= 25.0 {
        max_team_gap
    } else if max_team_gap <= 50.0 {
        max_team_gap * 2.0
    } else if max_team_gap <= 100.0 {
        max_team_gap * 5.0
    } else if max_team_gap <= 200.0 {
        max_team_gap * 12.0
    } else {
        max_team_gap * 30.0
    }
}

fn tank_gap_penalty(gap: f64) -> f64 {
    if gap <= 50.0 {
        gap * 1.0
    } else if gap <= 100.0 {
        gap * 3.0
    } else if gap <= 200.0 {
        gap * 8.0
    } else {
        gap * 20.0
    }
}

fn calculate_team_stats(context: &Context, team: &TeamState) -> TeamStats {
    let mut sum_rating = 0.0;
    let mut sum_rating2 = 0.0;
    let mut count = 0usize;
    let mut total_pain = 0.0;
    let mut max_pain = 0i32;
    let mut subrole_collisions = 0i32;
    let mut role_totals = vec![0.0; context.roles.len()];
    let mut role_counts = vec![0usize; context.roles.len()];
    let mut role_avg_sum = 0.0;
    let mut role_avg_sum2 = 0.0;
    let mut role_avg_count = 0usize;

    for (role_index, roster) in team.roster.iter().enumerate() {
        if roster.is_empty() {
            continue;
        }

        let mut role_sum_rating = 0.0;
        let mut subclass_counts: HashMap<&str, usize> = HashMap::new();

        for &player_index in roster {
            let player = &context.players[player_index];
            let rating = player.ratings[role_index] as f64;
            let pain = player.discomfort[role_index];

            role_sum_rating += rating;
            sum_rating2 += rating * rating;
            total_pain += pain as f64;
            count += 1;
            if pain > max_pain {
                max_pain = pain;
            }

            if let Some(subclass) = player.subclasses[role_index].as_deref() {
                *subclass_counts.entry(subclass).or_insert(0) += 1;
            }
        }

        sum_rating += role_sum_rating;
        role_totals[role_index] = role_sum_rating;
        role_counts[role_index] = roster.len();

        let role_avg = role_sum_rating / roster.len() as f64;
        role_avg_sum += role_avg;
        role_avg_sum2 += role_avg * role_avg;
        role_avg_count += 1;

        for &occurrences in subclass_counts.values() {
            if occurrences > 1 {
                subrole_collisions += ((occurrences * (occurrences - 1)) / 2) as i32;
            }
        }
    }

    let mmr = if count > 0 {
        sum_rating / count as f64
    } else {
        0.0
    };
    let intra_std = sample_stdev_from_sums(sum_rating, sum_rating2, count);

    let internal_role_spread = if role_avg_count >= 2 {
        let mean = role_avg_sum / role_avg_count as f64;
        let var = (role_avg_sum2 / role_avg_count as f64) - mean.powi(2);
        var.max(0.0).sqrt()
    } else {
        0.0
    };

    TeamStats {
        mmr,
        total_rating: sum_rating,
        discomfort: total_pain,
        intra_std,
        max_pain,
        subrole_collisions,
        role_totals,
        role_counts,
        internal_role_spread,
    }
}

fn calculate_objectives_from_stats(stats: &[TeamStats], ctx: &Context) -> Objectives {
    if stats.is_empty() {
        return Objectives {
            balance: f64::INFINITY,
            comfort: f64::INFINITY,
        };
    }
    let team_count = stats.len();
    let mut sum_mmr = 0.0;
    let mut sum_mmr2 = 0.0;
    let mut sum_total = 0.0;
    let mut sum_total2 = 0.0;
    let mut min_team_total = f64::INFINITY;
    let mut max_team_total = f64::NEG_INFINITY;
    let mut role_line_avgs: Vec<Vec<f64>> = vec![Vec::new(); ctx.roles.len()];
    let mut sum_discomfort = 0.0;
    let mut global_max_pain = 0i32;
    let mut sum_subrole_collisions = 0i32;
    let mut sum_intra_std = 0.0;
    let mut sum_internal_role_spread = 0.0;
    let mut tank_ratings: Vec<f64> = Vec::with_capacity(team_count);
    let mut effective_totals: Vec<f64> = Vec::with_capacity(team_count);

    for s in stats {
        sum_mmr += s.mmr;
        sum_mmr2 += s.mmr * s.mmr;
        sum_total += s.total_rating;
        sum_total2 += s.total_rating * s.total_rating;
        min_team_total = min_team_total.min(s.total_rating);
        max_team_total = max_team_total.max(s.total_rating);
        sum_discomfort += s.discomfort;
        global_max_pain = global_max_pain.max(s.max_pain);
        sum_subrole_collisions += s.subrole_collisions;
        sum_intra_std += s.intra_std;
        sum_internal_role_spread += s.internal_role_spread;

        let mut eff_total = 0.0;
        let mut team_tank_rating = 0.0;

        for (r_idx, &total) in s.role_totals.iter().enumerate() {
            if s.role_counts[r_idx] == 0 {
                continue;
            }
            let avg = total / s.role_counts[r_idx] as f64;
            role_line_avgs[r_idx].push(avg);

            let impact = if ctx.tank_role_idx == Some(r_idx) {
                ctx.config.tank_impact_weight
            } else if ctx.dps_role_idx == Some(r_idx) {
                ctx.config.dps_impact_weight
            } else if ctx.support_role_idx == Some(r_idx) {
                ctx.config.support_impact_weight
            } else {
                1.0
            };
            eff_total += total * impact;

            if ctx.tank_role_idx == Some(r_idx) {
                team_tank_rating = avg;
            }
        }
        effective_totals.push(eff_total);
        tank_ratings.push(team_tank_rating);
    }

    let total_rating_std = sample_stdev_from_sums(sum_total, sum_total2, team_count);
    let max_team_gap = if team_count >= 2 {
        max_team_total - min_team_total
    } else {
        0.0
    };
    let gap_penalty = calculate_gap_penalty(max_team_gap);
    let inter_team_std = sample_stdev_from_sums(sum_mmr, sum_mmr2, team_count);

    let mut role_line_penalty = 0.0;
    let mut counted_roles = 0usize;
    for averages in role_line_avgs {
        if averages.len() < 2 {
            continue;
        }
        let mean = averages.iter().sum::<f64>() / averages.len() as f64;
        let variance =
            averages.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / averages.len() as f64;
        role_line_penalty += variance.sqrt();
        counted_roles += 1;
    }
    if counted_roles > 0 {
        role_line_penalty /= counted_roles as f64;
    }

    let intra_team_penalty = sum_intra_std * ctx.config.intra_team_std_weight;
    let role_spread_penalty = sum_internal_role_spread * ctx.config.internal_role_spread_weight;

    let tank_gap = if team_count >= 2 {
        let t_max = tank_ratings
            .iter()
            .cloned()
            .fold(f64::NEG_INFINITY, f64::max);
        let t_min = tank_ratings.iter().cloned().fold(f64::INFINITY, f64::min);
        t_max - t_min
    } else {
        0.0
    };

    let tank_std = sample_stdev_from_sums(
        tank_ratings.iter().sum(),
        tank_ratings.iter().map(|v| v * v).sum(),
        team_count,
    );
    let eff_total_std = sample_stdev_from_sums(
        effective_totals.iter().sum(),
        effective_totals.iter().map(|v| v * v).sum(),
        team_count,
    );

    let ow2_tank_penalty = tank_gap_penalty(tank_gap) * ctx.config.tank_gap_weight
        + tank_std * ctx.config.tank_std_weight
        + eff_total_std * ctx.config.effective_total_std_weight;

    let objective_balance = total_rating_std * ctx.config.team_total_balance_weight
        + gap_penalty * ctx.config.max_team_gap_weight
        + inter_team_std * ctx.config.average_mmr_balance_weight
        + role_line_penalty * ctx.config.role_line_balance_weight
        + intra_team_penalty
        + role_spread_penalty
        + ow2_tank_penalty;

    let avg_discomfort = sum_discomfort / team_count as f64;
    let objective_comfort = avg_discomfort * ctx.config.role_discomfort_weight
        + global_max_pain as f64 * ctx.config.max_role_discomfort_weight
        + sum_subrole_collisions as f64 * ctx.config.sub_role_collision_weight;

    Objectives {
        balance: objective_balance,
        comfort: objective_comfort,
    }
}

fn calculate_objectives(solution: &Solution, context: &Context) -> Objectives {
    let stats: Vec<TeamStats> = solution
        .iter()
        .map(|t| calculate_team_stats(context, t))
        .collect();
    calculate_objectives_from_stats(&stats, context)
}

fn dominates(left: &Objectives, right: &Objectives) -> bool {
    let better_or_equal = left.balance <= right.balance && left.comfort <= right.comfort;
    let strictly_better = left.balance < right.balance || left.comfort < right.comfort;
    better_or_equal && strictly_better
}

fn fast_non_dominated_sort(objectives: &[Objectives]) -> Vec<Vec<usize>> {
    if objectives.is_empty() {
        return Vec::new();
    }
    let count = objectives.len();
    let mut dominated_sets: Vec<Vec<usize>> = vec![Vec::new(); count];
    let mut domination_counts = vec![0usize; count];
    let mut fronts: Vec<Vec<usize>> = vec![Vec::new()];

    for left in 0..count {
        for right in 0..count {
            if left == right {
                continue;
            }
            if dominates(&objectives[left], &objectives[right]) {
                dominated_sets[left].push(right);
            } else if dominates(&objectives[right], &objectives[left]) {
                domination_counts[left] += 1;
            }
        }
        if domination_counts[left] == 0 {
            fronts[0].push(left);
        }
    }

    let mut current = 0usize;
    while current < fronts.len() && !fronts[current].is_empty() {
        let mut next_front = Vec::new();
        for &left in &fronts[current] {
            for &right in &dominated_sets[left] {
                domination_counts[right] -= 1;
                if domination_counts[right] == 0 {
                    next_front.push(right);
                }
            }
        }
        if !next_front.is_empty() {
            fronts.push(next_front);
        }
        current += 1;
    }
    fronts
}

/// Возвращает Vec<f64> длины front.len(), где distances[k] соответствует front[k].
/// Вызывающая сторона сопоставляет позицию во фронте с population index через front[pos].
fn crowding_distance(front: &[usize], objectives: &[Objectives]) -> Vec<f64> {
    let n = front.len();
    let mut distances = vec![0.0; n];
    if n == 0 {
        return distances;
    }
    if n <= 2 {
        for d in distances.iter_mut() {
            *d = f64::INFINITY;
        }
        return distances;
    }

    // order переиспользуется между итерациями m — одна аллокация на вызов
    let mut order: Vec<usize> = (0..n).collect();
    for m in 0..2 {
        order.sort_by(|&a, &b| {
            let va = if m == 0 {
                objectives[front[a]].balance
            } else {
                objectives[front[a]].comfort
            };
            let vb = if m == 0 {
                objectives[front[b]].balance
            } else {
                objectives[front[b]].comfort
            };
            va.partial_cmp(&vb).unwrap_or(Ordering::Equal)
        });
        let first = order[0];
        let last = order[n - 1];
        let min_v = if m == 0 {
            objectives[front[first]].balance
        } else {
            objectives[front[first]].comfort
        };
        let max_v = if m == 0 {
            objectives[front[last]].balance
        } else {
            objectives[front[last]].comfort
        };
        let span = if max_v > min_v { max_v - min_v } else { 1.0 };

        distances[first] = f64::INFINITY;
        distances[last] = f64::INFINITY;
        for k in 1..n - 1 {
            let prev_pos = order[k - 1];
            let next_pos = order[k + 1];
            let prev = if m == 0 {
                objectives[front[prev_pos]].balance
            } else {
                objectives[front[prev_pos]].comfort
            };
            let next = if m == 0 {
                objectives[front[next_pos]].balance
            } else {
                objectives[front[next_pos]].comfort
            };
            // если уже INFINITY (edge в m=0) — ∞ + finite = ∞, семантика сохраняется
            distances[order[k]] += (next - prev) / span;
        }
    }
    distances
}

fn normalize_objectives(objectives: &[Objectives]) -> Vec<Objectives> {
    if objectives.is_empty() {
        return vec![];
    }
    let b_min = objectives
        .iter()
        .map(|o| o.balance)
        .fold(f64::INFINITY, f64::min);
    let b_max = objectives
        .iter()
        .map(|o| o.balance)
        .fold(f64::NEG_INFINITY, f64::max);
    let c_min = objectives
        .iter()
        .map(|o| o.comfort)
        .fold(f64::INFINITY, f64::min);
    let c_max = objectives
        .iter()
        .map(|o| o.comfort)
        .fold(f64::NEG_INFINITY, f64::max);
    let b_span = (b_max - b_min).max(1e-6);
    let c_span = (c_max - c_min).max(1e-6);
    objectives
        .iter()
        .map(|o| Objectives {
            balance: (o.balance - b_min) / b_span,
            comfort: (o.comfort - c_min) / c_span,
        })
        .collect()
}

fn archive_capacity_limit(ctx: &Context) -> usize {
    ctx.config
        .max_result_variants
        .max(DEFAULT_ARCHIVE_LIMIT)
        .min(MAX_ARCHIVE_LIMIT)
}

fn archive_selection_order(archive: &[(Objectives, Solution)], ctx: &Context) -> Vec<usize> {
    if archive.is_empty() {
        return Vec::new();
    }

    let objectives: Vec<Objectives> = archive.iter().map(|(obj, _)| *obj).collect();
    let normed = normalize_objectives(&objectives);
    let front: Vec<usize> = (0..archive.len()).collect();
    let crowding = crowding_distance(&front, &objectives);
    let signatures: Vec<u64> = archive.iter().map(|(_, sol)| signature(sol, ctx)).collect();

    let mut score_ranked: Vec<usize> = (0..archive.len()).collect();
    score_ranked.sort_by(|&left, &right| {
        let left_score = normed[left].balance + normed[left].comfort;
        let right_score = normed[right].balance + normed[right].comfort;
        left_score
            .partial_cmp(&right_score)
            .unwrap_or(Ordering::Equal)
            .then_with(|| {
                objectives[left]
                    .balance
                    .partial_cmp(&objectives[right].balance)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| {
                objectives[left]
                    .comfort
                    .partial_cmp(&objectives[right].comfort)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| signatures[left].cmp(&signatures[right]))
    });

    let best_balance_idx = (0..archive.len())
        .min_by(|&left, &right| {
            objectives[left]
                .balance
                .partial_cmp(&objectives[right].balance)
                .unwrap_or(Ordering::Equal)
                .then_with(|| {
                    objectives[left]
                        .comfort
                        .partial_cmp(&objectives[right].comfort)
                        .unwrap_or(Ordering::Equal)
                })
                .then_with(|| signatures[left].cmp(&signatures[right]))
        })
        .unwrap_or(0);
    let best_comfort_idx = (0..archive.len())
        .min_by(|&left, &right| {
            objectives[left]
                .comfort
                .partial_cmp(&objectives[right].comfort)
                .unwrap_or(Ordering::Equal)
                .then_with(|| {
                    objectives[left]
                        .balance
                        .partial_cmp(&objectives[right].balance)
                        .unwrap_or(Ordering::Equal)
                })
                .then_with(|| signatures[left].cmp(&signatures[right]))
        })
        .unwrap_or(0);

    let mut anchor_seen = HashSet::new();
    let mut order = Vec::with_capacity(archive.len());
    for idx in score_ranked
        .iter()
        .copied()
        .take(ARCHIVE_SCORE_KEEP.min(score_ranked.len()))
        .chain([best_balance_idx, best_comfort_idx].into_iter())
    {
        if anchor_seen.insert(idx) {
            order.push(idx);
        }
    }

    let mut crowding_ranked: Vec<usize> = (0..archive.len()).collect();
    crowding_ranked.sort_by(|&left, &right| {
        let left_score = normed[left].balance + normed[left].comfort;
        let right_score = normed[right].balance + normed[right].comfort;
        crowding[right]
            .partial_cmp(&crowding[left])
            .unwrap_or(Ordering::Equal)
            .then_with(|| {
                left_score
                    .partial_cmp(&right_score)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| {
                objectives[left]
                    .balance
                    .partial_cmp(&objectives[right].balance)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| {
                objectives[left]
                    .comfort
                    .partial_cmp(&objectives[right].comfort)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| signatures[left].cmp(&signatures[right]))
    });

    for idx in crowding_ranked {
        if anchor_seen.insert(idx) {
            order.push(idx);
        }
    }
    order
}

fn archive_select_items(
    archive: &[(Objectives, Solution)],
    count: usize,
    ctx: &Context,
) -> Vec<(Objectives, Solution)> {
    archive_selection_order(archive, ctx)
        .into_iter()
        .take(count.min(archive.len()))
        .map(|idx| archive[idx].clone())
        .collect()
}

fn archive_select_best_items(
    archive: &[(Objectives, Solution)],
    count: usize,
    ctx: &Context,
) -> Vec<(Objectives, Solution)> {
    if archive.is_empty() {
        return Vec::new();
    }

    let objectives: Vec<Objectives> = archive.iter().map(|(obj, _)| *obj).collect();
    let normed = normalize_objectives(&objectives);
    let mut ranked: Vec<usize> = (0..archive.len()).collect();
    ranked.sort_by(|&left, &right| {
        let left_score = normed[left].balance + normed[left].comfort;
        let right_score = normed[right].balance + normed[right].comfort;
        left_score
            .partial_cmp(&right_score)
            .unwrap_or(Ordering::Equal)
            .then_with(|| {
                objectives[left]
                    .balance
                    .partial_cmp(&objectives[right].balance)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| {
                objectives[left]
                    .comfort
                    .partial_cmp(&objectives[right].comfort)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| signature(&archive[left].1, ctx).cmp(&signature(&archive[right].1, ctx)))
    });

    ranked
        .into_iter()
        .take(count.min(archive.len()))
        .map(|idx| archive[idx].clone())
        .collect()
}

fn prune_archive(
    archive: &mut Vec<(Objectives, Solution)>,
    archive_sigs: &mut HashSet<u64>,
    ctx: &Context,
) {
    let limit = archive_capacity_limit(ctx);
    if archive.len() <= limit {
        return;
    }

    let retained = archive_select_items(archive, limit, ctx);
    let retained_sigs: HashSet<u64> = retained
        .iter()
        .map(|(_, sol)| signature(sol, ctx))
        .collect();
    *archive = retained;
    *archive_sigs = retained_sigs;
}

fn solution_is_complete(solution: &Solution, context: &Context) -> bool {
    solution.iter().all(|team| {
        team.roster
            .iter()
            .enumerate()
            .all(|(r_idx, r)| r.len() == context.capacities[r_idx])
    })
}

fn create_empty_solution(context: &Context) -> Solution {
    (0..context.num_teams)
        .map(|i| TeamState {
            id: i + 1,
            roster: vec![Vec::new(); context.roles.len()],
        })
        .collect()
}

/// Распределяет игроков, предварительно отсортированных по убыванию приоритетного
/// критерия, round-robin по командам в "змейке" (snake draft) внутри каждой роли.
/// Это даёт сильно сбалансированное стартовое решение по MMR.
fn create_snake_draft_solution(context: &Context) -> Solution {
    let mut teams = create_empty_solution(context);
    if context.num_teams == 0 || context.players.is_empty() {
        return teams;
    }

    let mut buckets: Vec<Vec<usize>> = vec![Vec::new(); context.roles.len()];
    for (i, p) in context.players.iter().enumerate() {
        buckets[p.seed_role].push(i);
    }

    for r in 0..context.roles.len() {
        // Капитаны распределяются первыми, по одному в команду (если use_captains)
        let (mut captains, mut others): (Vec<usize>, Vec<usize>) = if context.config.use_captains {
            buckets[r]
                .iter()
                .copied()
                .partition(|&i| context.players[i].is_captain)
        } else {
            (Vec::new(), buckets[r].clone())
        };
        captains
            .sort_by(|&a, &b| context.players[b].ratings[r].cmp(&context.players[a].ratings[r]));
        others.sort_by(|&a, &b| context.players[b].ratings[r].cmp(&context.players[a].ratings[r]));

        // Залоченные капитаны — строго на свою команду; остальные (без лока) — по кругу.
        let mut t = 0usize;
        for p in captains {
            if let Some(ct) = context.players[p].captain_team {
                if ct < teams.len() && teams[ct].roster[r].len() < context.capacities[r] {
                    teams[ct].roster[r].push(p);
                    continue;
                }
            }
            if teams[t].roster[r].len() < context.capacities[r] {
                teams[t].roster[r].push(p);
            }
            t = (t + 1) % context.num_teams;
        }

        // Змейка: чередуем направление на каждой "волне"
        let mut idx = 0usize;
        let mut forward = true;
        for p in others {
            let mut placed = false;
            for _ in 0..context.num_teams {
                let target = if forward {
                    idx
                } else {
                    context.num_teams - 1 - idx
                };
                if teams[target].roster[r].len() < context.capacities[r] {
                    teams[target].roster[r].push(p);
                    placed = true;
                    idx += 1;
                    if idx >= context.num_teams {
                        idx = 0;
                        forward = !forward;
                    }
                    break;
                } else {
                    idx += 1;
                    if idx >= context.num_teams {
                        idx = 0;
                        forward = !forward;
                    }
                }
            }
            if !placed {
                break;
            }
        }
    }
    teams
}

/// Жадное распределение, минимизирующее дискомфорт: для каждой позиции
/// выбирается игрок с наименьшим discomfort[role], игроки с `first_preference == role`
/// идут первыми.
fn create_comfort_greedy_solution(context: &Context) -> Solution {
    let mut teams = create_empty_solution(context);
    if context.num_teams == 0 || context.players.is_empty() {
        return teams;
    }

    let mut buckets: Vec<Vec<usize>> = vec![Vec::new(); context.roles.len()];
    for (i, p) in context.players.iter().enumerate() {
        buckets[p.seed_role].push(i);
    }

    for r in 0..context.roles.len() {
        // Сортируем: капитаны первыми, затем по возрастанию discomfort, затем по убыванию rating
        buckets[r].sort_by(|&a, &b| {
            let ca = context.players[a].is_captain && context.config.use_captains;
            let cb = context.players[b].is_captain && context.config.use_captains;
            cb.cmp(&ca)
                .then_with(|| {
                    context.players[a].discomfort[r].cmp(&context.players[b].discomfort[r])
                })
                .then_with(|| context.players[b].ratings[r].cmp(&context.players[a].ratings[r]))
        });

        let mut cur = 0usize;
        for &p in &buckets[r] {
            for _ in 0..context.num_teams {
                let t = cur % context.num_teams;
                cur += 1;
                if teams[t].roster[r].len() < context.capacities[r] {
                    teams[t].roster[r].push(p);
                    break;
                }
            }
        }
    }
    teams
}

fn create_random_solution(context: &Context, rng: &mut StdRng) -> Solution {
    let mut teams = create_empty_solution(context);
    if context.num_teams == 0 || context.players.is_empty() {
        return teams;
    }

    let mut buckets = vec![Vec::new(); context.roles.len()];
    let mut captain_buckets = vec![Vec::new(); context.roles.len()];

    for (i, p) in context.players.iter().enumerate() {
        if context.config.use_captains && p.is_captain {
            captain_buckets[p.seed_role].push(i);
        } else {
            buckets[p.seed_role].push(i);
        }
    }
    for b in &mut buckets {
        b.shuffle(rng);
    }
    for b in &mut captain_buckets {
        b.shuffle(rng);
    }

    if context.config.use_captains {
        let mut caps = Vec::new();
        for (r, b) in captain_buckets.iter().enumerate() {
            for &p in b {
                caps.push((r, p));
            }
        }
        caps.shuffle(rng);
        let mut cur = 0;
        for (r, p) in caps {
            let mut placed = false;
            for _ in 0..context.num_teams {
                let t = cur % context.num_teams;
                cur += 1;
                if teams[t].roster[r].len() < context.capacities[r] {
                    teams[t].roster[r].push(p);
                    placed = true;
                    break;
                }
            }
            if !placed {
                buckets[r].push(p);
            }
        }
    }

    for (r, b) in buckets.iter_mut().enumerate() {
        let mut cur = 0;
        while let Some(p) = b.pop() {
            let mut placed = false;
            for _ in 0..context.num_teams {
                let t = cur % context.num_teams;
                cur += 1;
                if teams[t].roster[r].len() < context.capacities[r] {
                    teams[t].roster[r].push(p);
                    placed = true;
                    break;
                }
            }
            if !placed {
                break;
            }
        }
    }
    teams
}

/// Приоритет размещения игрока в роли. Выше — лучше.
/// Капитан в seed_role при use_captains имеет абсолютный приоритет.
#[inline]
fn placement_score(ctx: &Context, p: usize, r: usize) -> i32 {
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

fn analyze_repair_need(sol: &Solution, ctx: &Context) -> RepairNeed {
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
                .is_some_and(|roster| roster.iter().any(|&assigned| assigned == p));
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
fn enforce_captain_locks(sol: &mut Solution, ctx: &Context) {
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
        if sol[t0].roster[r0].iter().any(|&x| x == p) {
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
                    if ct != t0 || cr != r0 {
                        if sol[ct].roster[cr].len() < ctx.capacities[cr] {
                            sol[ct].roster[cr].push(evicted);
                            continue;
                        }
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
fn ensure_feasibility(sol: &mut Solution, ctx: &Context, rng: &mut StdRng) {
    let p_count = ctx.players.len();
    let num_roles = ctx.roles.len();
    if p_count == 0 || num_roles == 0 || ctx.num_teams == 0 {
        return;
    }

    // Сначала вкорачиваем капитанов на их зафиксированные места —
    // это гарантирует инвариант "один капитан на команду, фиксированная роль".
    enforce_captain_locks(sol, ctx);

    // --- Шаг 1: обрезка невалидных индексов и превышений capacity ---
    for t in 0..ctx.num_teams {
        for r in 0..num_roles {
            let cap = ctx.capacities[r];
            let roster = &mut sol[t].roster[r];
            roster.retain(|&p| p < p_count);
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

fn swap_players(
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

fn strategy_robin_hood(sol: &mut Solution, ctx: &Context, rng: &mut StdRng) -> bool {
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

fn strategy_fix_discomfort(sol: &mut Solution, ctx: &Context) -> bool {
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

fn strategy_role_rebalance(sol: &mut Solution, ctx: &Context) -> bool {
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

fn mutate_random(sol: &Solution, ctx: &Context, str: usize, rng: &mut StdRng) -> Solution {
    let mut nxt = sol.clone();
    if ctx.roles.is_empty() || nxt.len() < 2 {
        return nxt;
    }
    for _ in 0..str.max(1) {
        if rng.gen::<f64>() < 0.8 {
            let r = rng.gen_range(0..ctx.roles.len());
            let mut ts = (0..nxt.len()).collect::<Vec<_>>();
            ts.shuffle(rng);
            let a = ts[0];
            let b = ts[1];
            if nxt[a].roster[r].is_empty() || nxt[b].roster[r].is_empty() {
                continue;
            }
            let sa = rng.gen_range(0..nxt[a].roster[r].len());
            let sb = rng.gen_range(0..nxt[b].roster[r].len());
            if ctx.config.use_captains
                && (ctx.players[nxt[a].roster[r][sa]].is_captain
                    || ctx.players[nxt[b].roster[r][sb]].is_captain)
            {
                continue;
            }
            swap_players(&mut nxt, a, r, sa, b, r, sb);
        } else if ctx.roles.len() >= 2 {
            let t = rng.gen_range(0..nxt.len());
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
                c1[rng.gen_range(0..c1.len())],
                t,
                r2,
                c2[rng.gen_range(0..c2.len())],
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
fn crossover_role_lines(a: &Solution, b: &Solution, ctx: &Context, rng: &mut StdRng) -> Solution {
    let mut child = create_empty_solution(ctx);
    if ctx.roles.is_empty() || a.len() != b.len() || a.len() != child.len() {
        // Фолбэк: клонируем A, если структуры не совпадают
        return a.clone();
    }
    // Гарантируем, что хотя бы одна роль от каждого родителя — иначе ребёнок
    // идентичен одному из них и crossover вырождается в клон.
    let num_roles = ctx.roles.len();
    let mut from_a: Vec<bool> = (0..num_roles).map(|_| rng.gen::<bool>()).collect();
    if num_roles >= 2 {
        if from_a.iter().all(|&v| v) {
            let flip = rng.gen_range(0..num_roles);
            from_a[flip] = false;
        } else if from_a.iter().all(|&v| !v) {
            let flip = rng.gen_range(0..num_roles);
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

fn mutate_targeted(sol: &Solution, ctx: &Context, rng: &mut StdRng, strength: usize) -> Solution {
    let mut nxt = sol.clone();
    for _ in 0..strength.max(1) {
        let roll = rng.gen::<f64>();
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

/// Принять ход, если новое решение доминирует старое по Парето ИЛИ
/// скалярный рефери (взвешенная сумма) строго улучшается при нестрогом
/// доминировании по Парето. Это позволяет принимать "латеральные" ходы,
/// ускоряя сходимость к угловым точкам Парето.
#[inline]
fn accept_move(old: &Objectives, new: &Objectives) -> bool {
    const EPS: f64 = 1e-6;
    let pareto_ok = new.balance <= old.balance + EPS && new.comfort <= old.comfort + EPS;
    if !pareto_ok {
        return false;
    }
    let strictly_pareto = new.balance < old.balance - EPS || new.comfort < old.comfort - EPS;
    if strictly_pareto {
        return true;
    }
    // Скалярный tie-breaker для латеральных ходов
    let old_s = old.balance + old.comfort;
    let new_s = new.balance + new.comfort;
    new_s < old_s - EPS
}

/// Расширенный локальный поиск:
/// 1) same-role swap между командами;
/// 2) cross-role swap внутри одной команды (часто снимает role-line penalty);
/// 3) cross-role swap между разными командами.
/// Идёт до фиксированной точки (с лимитом `max_passes` как safety-net).
fn polish_pareto(sol: &Solution, ctx: &Context, max_passes: usize) -> Solution {
    let mut cur = sol.clone();
    if ctx.roles.is_empty() || cur.len() < 2 {
        return cur;
    }
    let mut stats: Vec<TeamStats> = cur.iter().map(|t| calculate_team_stats(ctx, t)).collect();
    let mut best_obj = calculate_objectives_from_stats(&stats, ctx);

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

                            swap_players(&mut cur, i, r, a, j, r, b);
                            stats[i] = calculate_team_stats(ctx, &cur[i]);
                            stats[j] = calculate_team_stats(ctx, &cur[j]);
                            let nw = calculate_objectives_from_stats(&stats, ctx);
                            if accept_move(&best_obj, &nw) {
                                best_obj = nw;
                                improved = true;
                                break 'same_role;
                            }
                            swap_players(&mut cur, i, r, a, j, r, b);
                            stats[i] = calculate_team_stats(ctx, &cur[i]);
                            stats[j] = calculate_team_stats(ctx, &cur[j]);
                        }
                    }
                }
            }
        }
        if improved {
            continue;
        }

        // (2) cross-role swap внутри одной команды
        'intra_cross: for t in 0..cur.len() {
            for r1 in 0..ctx.roles.len() {
                for r2 in (r1 + 1)..ctx.roles.len() {
                    let l1 = cur[t].roster[r1].len();
                    let l2 = cur[t].roster[r2].len();
                    if l1 == 0 || l2 == 0 {
                        continue;
                    }
                    for a in 0..l1 {
                        let pa = cur[t].roster[r1][a];
                        if is_captain(pa) || !ctx.players[pa].can_play[r2] {
                            continue;
                        }
                        for b in 0..l2 {
                            let pb = cur[t].roster[r2][b];
                            if is_captain(pb) || !ctx.players[pb].can_play[r1] {
                                continue;
                            }
                            swap_players(&mut cur, t, r1, a, t, r2, b);
                            stats[t] = calculate_team_stats(ctx, &cur[t]);
                            let nw = calculate_objectives_from_stats(&stats, ctx);
                            if accept_move(&best_obj, &nw) {
                                best_obj = nw;
                                improved = true;
                                break 'intra_cross;
                            }
                            swap_players(&mut cur, t, r1, a, t, r2, b);
                            stats[t] = calculate_team_stats(ctx, &cur[t]);
                        }
                    }
                }
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
                                swap_players(&mut cur, i, r1, a, j, r2, b);
                                stats[i] = calculate_team_stats(ctx, &cur[i]);
                                stats[j] = calculate_team_stats(ctx, &cur[j]);
                                let nw = calculate_objectives_from_stats(&stats, ctx);
                                if accept_move(&best_obj, &nw) {
                                    best_obj = nw;
                                    improved = true;
                                    break 'cross_team;
                                }
                                swap_players(&mut cur, i, r1, a, j, r2, b);
                                stats[i] = calculate_team_stats(ctx, &cur[i]);
                                stats[j] = calculate_team_stats(ctx, &cur[j]);
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

/// Обновить внешний Парето-архив кандидатом. Возвращает true если кандидат
/// попал в архив. Удаляет все доминируемые им элементы. Дедуп по сигнатуре.
fn archive_update(
    archive: &mut Vec<(Objectives, Solution)>,
    archive_sigs: &mut HashSet<u64>,
    candidate: (Objectives, Solution),
    ctx: &Context,
) -> bool {
    let sig = signature(&candidate.1, ctx);
    if archive_sigs.contains(&sig) {
        return false;
    }
    for (obj, _) in archive.iter() {
        if dominates(obj, &candidate.0) {
            return false;
        }
        // Равенство — считаем "есть уже"
        if (obj.balance - candidate.0.balance).abs() < 1e-9
            && (obj.comfort - candidate.0.comfort).abs() < 1e-9
        {
            // Разные по сигнатуре, но численно идентичны — оставляем оба не нужно, добавим один раз
        }
    }
    // Удаляем всех, кого кандидат доминирует
    let mut i = 0;
    while i < archive.len() {
        if dominates(&candidate.0, &archive[i].0) {
            let removed_sig = signature(&archive[i].1, ctx);
            archive_sigs.remove(&removed_sig);
            archive.swap_remove(i);
        } else {
            i += 1;
        }
    }
    archive_sigs.insert(sig);
    archive.push(candidate);
    prune_archive(archive, archive_sigs, ctx);
    true
}

/// Бинарный турнир без аллокации: два случайных индекса (без повтора при n>1),
/// победитель по rank, tie-break по crowding distance. Поведение 1:1 с прежней версией.
fn tournament_pick(ranks: &[usize], dists: &[f64], rng: &mut StdRng) -> usize {
    let n = ranks.len();
    debug_assert!(n > 0);
    let a = rng.gen_range(0..n);
    let mut b = rng.gen_range(0..n);
    while n > 1 && b == a {
        b = rng.gen_range(0..n);
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

/// Канонический хэш решения, инвариантный к перестановке команд.
/// Для каждой команды строится отсортированный набор (role_idx, player_idx),
/// хэш команды независим от её team.id; затем сортируются хэши команд.
fn signature(sol: &Solution, _ctx: &Context) -> u64 {
    let mut team_hashes: Vec<u64> = Vec::with_capacity(sol.len());
    for t in sol {
        let mut entries: Vec<(usize, usize)> = Vec::new();
        for (r, rs) in t.roster.iter().enumerate() {
            for &p in rs {
                entries.push((r, p));
            }
        }
        entries.sort_unstable();
        let mut h = DefaultHasher::new();
        entries.hash(&mut h);
        team_hashes.push(h.finish());
    }
    team_hashes.sort_unstable();
    let mut h = DefaultHasher::new();
    team_hashes.hash(&mut h);
    h.finish()
}

/// Запускает один "остров" NSGA-II с заданным сидом. Поддерживает внешний
/// Парето-архив (Hall of Fame) — все недоминируемые решения, встреченные
/// за весь прогон, включая промежуточные поколения.
#[allow(dead_code)]
fn run_single_island(
    ctx: &Context,
    island_seed: u64,
) -> Result<Vec<(Objectives, Solution)>, String> {
    let mut rng = StdRng::seed_from_u64(island_seed);
    let mut pop: Vec<(Objectives, Solution)> = Vec::new();
    let mut archive: Vec<(Objectives, Solution)> = Vec::new();
    let mut archive_sigs: HashSet<u64> = HashSet::new();

    // Жадные seed-решения (только на первом острове для детерминизма —
    // на всех островах они одинаковы, так что нет смысла добавлять больше одного раза,
    // но tournament + мутации расходятся сильно из-за разных сидов).
    let greedy_count = ctx.config.greedy_seed_count.min(ctx.config.population_size);
    if greedy_count >= 1 {
        let mut sol = create_snake_draft_solution(ctx);
        ensure_feasibility(&mut sol, ctx, &mut rng);
        if solution_is_complete(&sol, ctx) {
            let obj = calculate_objectives(&sol, ctx);
            archive_update(&mut archive, &mut archive_sigs, (obj, sol.clone()), ctx);
            pop.push((obj, sol));
        }
    }
    if greedy_count >= 2 {
        let mut sol = create_comfort_greedy_solution(ctx);
        ensure_feasibility(&mut sol, ctx, &mut rng);
        if solution_is_complete(&sol, ctx) {
            let obj = calculate_objectives(&sol, ctx);
            archive_update(&mut archive, &mut archive_sigs, (obj, sol.clone()), ctx);
            pop.push((obj, sol));
        }
    }
    if greedy_count >= 3 {
        // Гибрид: snake draft + одно применение strategy_fix_discomfort
        let mut sol = create_snake_draft_solution(ctx);
        strategy_fix_discomfort(&mut sol, ctx);
        ensure_feasibility(&mut sol, ctx, &mut rng);
        if solution_is_complete(&sol, ctx) {
            let obj = calculate_objectives(&sol, ctx);
            archive_update(&mut archive, &mut archive_sigs, (obj, sol.clone()), ctx);
            pop.push((obj, sol));
        }
    }

    let mut att = 0;
    while pop.len() < ctx.config.population_size && att < ctx.config.population_size * 4 {
        let mut sol = create_random_solution(ctx, &mut rng);
        ensure_feasibility(&mut sol, ctx, &mut rng);
        att += 1;
        if !solution_is_complete(&sol, ctx) {
            return Err("Incomplete initial solution".into());
        }
        let obj = calculate_objectives(&sol, ctx);
        archive_update(&mut archive, &mut archive_sigs, (obj, sol.clone()), ctx);
        pop.push((obj, sol));
    }
    if pop.is_empty() {
        return Err("Failed to build population".into());
    }

    let mut cur_mut_rate = ctx.config.mutation_rate;
    let cur_mut_strength = ctx.config.mutation_strength;
    let mut hist_bal = Vec::new();
    let mut hist_com = Vec::new();
    let mut gens_without_archive_improvement = 0usize;

    for gen in 0..ctx.config.generation_count {
        let objs: Vec<Objectives> = pop.iter().map(|(o, _)| *o).collect();
        let norm = normalize_objectives(&objs);
        let fronts = fast_non_dominated_sort(&norm);
        let mut ranks = vec![0; pop.len()];
        let mut dists = vec![0.0; pop.len()];
        for (r, f) in fronts.iter().enumerate() {
            let cd = crowding_distance(f, &norm);
            for (pos, &i) in f.iter().enumerate() {
                ranks[i] = r;
                dists[i] = cd[pos];
            }
        }

        let mut off = Vec::with_capacity(ctx.config.population_size);
        let mut offspring_survived = 0usize;
        // Kick при долгой стагнации архива: временно увеличиваем силу мутации
        let kick_active = ctx.config.stagnation_kick_patience > 0
            && gens_without_archive_improvement >= ctx.config.stagnation_kick_patience;
        let effective_strength = if kick_active {
            cur_mut_strength.saturating_mul(3).max(2)
        } else {
            cur_mut_strength
        };
        let effective_rate = if kick_active {
            cur_mut_rate.max(0.8)
        } else {
            cur_mut_rate
        };
        let mut archive_improved = false;
        let effective_crossover_rate = if kick_active {
            ctx.config.crossover_rate.max(0.9)
        } else {
            ctx.config.crossover_rate
        };
        while off.len() < ctx.config.population_size {
            let p1_idx = tournament_pick(&ranks, &dists, &mut rng);
            let crossed = pop.len() >= 2 && rng.gen::<f64>() < effective_crossover_rate;
            let mutated = rng.gen::<f64>() < effective_rate;

            // Если ни crossover, ни мутации — дешёвый elitism-путь: клонируем родителя как есть.
            if !crossed && !mutated {
                off.push(pop[p1_idx].clone());
                continue;
            }

            let mut child_sol: Solution = if crossed {
                // Второй родитель — предпочтительно отличный от первого
                let mut p2_idx = tournament_pick(&ranks, &dists, &mut rng);
                let mut tries = 0;
                while p2_idx == p1_idx && pop.len() > 1 && tries < 8 {
                    p2_idx = tournament_pick(&ranks, &dists, &mut rng);
                    tries += 1;
                }
                crossover_role_lines(&pop[p1_idx].1, &pop[p2_idx].1, ctx, &mut rng)
            } else {
                pop[p1_idx].1.clone()
            };

            if mutated {
                child_sol = mutate_targeted(&child_sol, ctx, &mut rng, effective_strength);
            }

            ensure_feasibility(&mut child_sol, ctx, &mut rng);
            let child_obj = calculate_objectives(&child_sol, ctx);
            if archive_update(
                &mut archive,
                &mut archive_sigs,
                (child_obj, child_sol.clone()),
                ctx,
            ) {
                archive_improved = true;
            }
            off.push((child_obj, child_sol));
        }
        if archive_improved {
            gens_without_archive_improvement = 0;
        } else {
            gens_without_archive_improvement += 1;
        }

        // Elitism: инжектим топ-K из архива в пул отбора, чтобы лучшие исторические
        // решения гарантированно участвовали в next-gen и не терялись из-за неудачных мутаций.
        // K=3 — компромисс между давлением отбора и разнообразием.
        let elite_k = 3.min(archive.len());
        let elite_items: Vec<(Objectives, Solution)> = if elite_k > 0 {
            let a_objs: Vec<Objectives> = archive.iter().map(|(o, _)| *o).collect();
            let a_norm = normalize_objectives(&a_objs);
            let mut a_scored: Vec<(usize, f64)> = a_norm
                .iter()
                .enumerate()
                .map(|(i, o)| (i, o.balance + o.comfort))
                .collect();
            a_scored.sort_by(|x, y| x.1.partial_cmp(&y.1).unwrap_or(Ordering::Equal));
            a_scored
                .into_iter()
                .take(elite_k)
                .map(|(i, _)| archive[i].clone())
                .collect()
        } else {
            Vec::new()
        };

        let parent_count = pop.len();
        let mut comb = pop;
        comb.extend(off);
        comb.extend(elite_items);
        let c_objs: Vec<Objectives> = comb.iter().map(|(o, _)| *o).collect();
        let c_norm = normalize_objectives(&c_objs);
        let c_fronts = fast_non_dominated_sort(&c_norm);
        let mut nxt = Vec::with_capacity(ctx.config.population_size);

        for f in c_fronts {
            if nxt.len() + f.len() <= ctx.config.population_size {
                for &i in &f {
                    if i >= parent_count {
                        offspring_survived += 1;
                    }
                    nxt.push(comb[i].clone());
                }
            } else {
                let cd = crowding_distance(&f, &c_norm);
                // pair (pop_index, distance), сортируем по distance по убыванию
                let mut pairs: Vec<(usize, f64)> = f.iter().copied().zip(cd.into_iter()).collect();
                pairs.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(Ordering::Equal));
                let rem = ctx.config.population_size - nxt.len();
                for (i, _) in pairs.into_iter().take(rem) {
                    if i >= parent_count {
                        offspring_survived += 1;
                    }
                    nxt.push(comb[i].clone());
                }
                break;
            }
        }
        pop = nxt;

        if ctx.config.mutation_rate_min < ctx.config.mutation_rate_max {
            let survival = offspring_survived as f64 / ctx.config.population_size as f64;
            let delta = (survival - 0.25) * 0.15;
            cur_mut_rate = (cur_mut_rate - delta)
                .max(ctx.config.mutation_rate_min)
                .min(ctx.config.mutation_rate_max);
        }

        if ctx.config.convergence_patience > 0 && gen >= ctx.config.convergence_patience {
            let (cur_b, cur_c) = best_front_progress(&pop);
            hist_bal.push(cur_b);
            hist_com.push(cur_c);

            if hist_bal.len() > ctx.config.convergence_patience {
                let idx = hist_bal.len() - ctx.config.convergence_patience - 1;
                let imp_b = if hist_bal[idx] > 0.0 {
                    (hist_bal[idx] - cur_b) / hist_bal[idx]
                } else {
                    0.0
                };
                let imp_c = if hist_com[idx] > 0.0 {
                    (hist_com[idx] - cur_c) / hist_com[idx]
                } else {
                    0.0
                };
                if imp_b < ctx.config.convergence_epsilon && imp_c < ctx.config.convergence_epsilon
                {
                    break;
                }
            }
        }
    }

    // Финально: добавляем всю текущую популяцию в архив
    for item in &pop {
        archive_update(&mut archive, &mut archive_sigs, item.clone(), ctx);
    }
    Ok(archive)
}

struct IslandState {
    ctx: Context,
    rng: StdRng,
    pop: Vec<(Objectives, Solution)>,
    archive: Vec<(Objectives, Solution)>,
    archive_sigs: HashSet<u64>,
    cur_mut_rate: f64,
    hist_bal: Vec<f64>,
    hist_com: Vec<f64>,
    gens_without_archive_improvement: usize,
    completed_generations: usize,
    repair_diagnostics: RepairDiagnostics,
    stopped: bool,
}

fn environmental_select(
    comb: Vec<(Objectives, Solution)>,
    population_size: usize,
    parent_count: usize,
) -> (Vec<(Objectives, Solution)>, usize) {
    let c_objs: Vec<Objectives> = comb.iter().map(|(o, _)| *o).collect();
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

fn best_front_progress(pop: &[(Objectives, Solution)]) -> (f64, f64) {
    let objs: Vec<Objectives> = pop.iter().map(|(o, _)| *o).collect();
    let norm = normalize_objectives(&objs);
    let fronts = fast_non_dominated_sort(&norm);
    let cur_b = fronts[0]
        .iter()
        .map(|&i| pop[i].0.balance)
        .fold(f64::INFINITY, f64::min);
    let cur_c = fronts[0]
        .iter()
        .map(|&i| pop[i].0.comfort)
        .fold(f64::INFINITY, f64::min);
    (cur_b, cur_c)
}

fn init_island_state(ctx: Context, island_seed: u64) -> Result<IslandState, String> {
    let mut rng = StdRng::seed_from_u64(island_seed);
    let mut pop: Vec<(Objectives, Solution)> = Vec::new();
    let mut archive: Vec<(Objectives, Solution)> = Vec::new();
    let mut archive_sigs: HashSet<u64> = HashSet::new();
    let initial_mut_rate = ctx.config.mutation_rate;
    let start_stopped = ctx.config.generation_count == 0;

    let greedy_count = ctx.config.greedy_seed_count.min(ctx.config.population_size);
    if greedy_count >= 1 {
        let mut sol = create_snake_draft_solution(&ctx);
        ensure_feasibility(&mut sol, &ctx, &mut rng);
        if solution_is_complete(&sol, &ctx) {
            let obj = calculate_objectives(&sol, &ctx);
            archive_update(&mut archive, &mut archive_sigs, (obj, sol.clone()), &ctx);
            pop.push((obj, sol));
        }
    }
    if greedy_count >= 2 {
        let mut sol = create_comfort_greedy_solution(&ctx);
        ensure_feasibility(&mut sol, &ctx, &mut rng);
        if solution_is_complete(&sol, &ctx) {
            let obj = calculate_objectives(&sol, &ctx);
            archive_update(&mut archive, &mut archive_sigs, (obj, sol.clone()), &ctx);
            pop.push((obj, sol));
        }
    }
    if greedy_count >= 3 {
        let mut sol = create_snake_draft_solution(&ctx);
        strategy_fix_discomfort(&mut sol, &ctx);
        ensure_feasibility(&mut sol, &ctx, &mut rng);
        if solution_is_complete(&sol, &ctx) {
            let obj = calculate_objectives(&sol, &ctx);
            archive_update(&mut archive, &mut archive_sigs, (obj, sol.clone()), &ctx);
            pop.push((obj, sol));
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
        let obj = calculate_objectives(&sol, &ctx);
        archive_update(&mut archive, &mut archive_sigs, (obj, sol.clone()), &ctx);
        pop.push((obj, sol));
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

fn run_island_epoch(state: &mut IslandState, epoch_generations: usize) -> Result<(), String> {
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
        let objs: Vec<Objectives> = state.pop.iter().map(|(o, _)| *o).collect();
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
            let crossed = state.pop.len() >= 2 && state.rng.gen::<f64>() < effective_crossover_rate;
            let mutated = state.rng.gen::<f64>() < effective_rate;

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
                crossover_role_lines(
                    &state.pop[p1_idx].1,
                    &state.pop[p2_idx].1,
                    &state.ctx,
                    &mut state.rng,
                )
            } else {
                state.pop[p1_idx].1.clone()
            };

            if mutated {
                child_sol =
                    mutate_targeted(&child_sol, &state.ctx, &mut state.rng, effective_strength);
            }

            let repair_need = analyze_repair_need(&child_sol, &state.ctx);
            let pre_repair_sig = signature(&child_sol, &state.ctx);
            ensure_feasibility(&mut child_sol, &state.ctx, &mut state.rng);
            let changed_by_repair = pre_repair_sig != signature(&child_sol, &state.ctx);
            state
                .repair_diagnostics
                .record_child(crossed, mutated, repair_need, changed_by_repair);
            let child_obj = calculate_objectives(&child_sol, &state.ctx);
            if archive_update(
                &mut state.archive,
                &mut state.archive_sigs,
                (child_obj, child_sol.clone()),
                &state.ctx,
            ) {
                archive_improved = true;
            }
            off.push((child_obj, child_sol));
        }

        if archive_improved {
            state.gens_without_archive_improvement = 0;
        } else {
            state.gens_without_archive_improvement += 1;
        }

        let elite_items = archive_select_best_items(
            &state.archive,
            ARCHIVE_ELITE_COUNT.min(state.archive.len()),
            &state.ctx,
        );
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

fn inject_migrants(state: &mut IslandState, migrants: &[(Objectives, Solution)]) {
    if state.stopped || migrants.is_empty() {
        return;
    }

    for (_, sol) in migrants {
        let local_obj = calculate_objectives(sol, &state.ctx);
        let candidate = (local_obj, sol.clone());
        archive_update(
            &mut state.archive,
            &mut state.archive_sigs,
            candidate,
            &state.ctx,
        );
    }
}

fn finalize_island_state(state: &mut IslandState) {
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
struct IslandProfile {
    /// Множитель для всех balance-related весов (std, gap, role-line, tank).
    balance_scale: f64,
    /// Множитель для comfort-related весов (discomfort, sub-role collisions).
    comfort_scale: f64,
    /// Множитель для максимумов (max_team_gap, max_role_discomfort) —
    /// профиль "экстремальные хвосты", ищет решения без провалов.
    extreme_scale: f64,
}

fn default_island_profiles() -> [IslandProfile; 4] {
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
fn ctx_with_profile(base: &Context, profile: IslandProfile) -> Context {
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
    c
}

#[derive(Debug, Clone, Copy, Default)]
struct ProgressSnapshot {
    current: Option<usize>,
    total: Option<usize>,
    percent: Option<f64>,
}

fn emit_progress_event(
    progress_callback: Option<&Py<PyAny>>,
    stage: &str,
    message: String,
    progress: Option<ProgressSnapshot>,
) -> Result<(), String> {
    let Some(callback) = progress_callback else {
        return Ok(());
    };

    Python::with_gil(|py| -> PyResult<()> {
        let payload = PyDict::new_bound(py);
        payload.set_item("status", "running")?;
        payload.set_item("stage", stage)?;
        payload.set_item("message", message)?;
        payload.set_item("level", "info")?;

        if let Some(progress) = progress {
            let progress_payload = PyDict::new_bound(py);
            if let Some(current) = progress.current {
                progress_payload.set_item("current", current)?;
            }
            if let Some(total) = progress.total {
                progress_payload.set_item("total", total)?;
            }
            if let Some(percent) = progress.percent {
                progress_payload.set_item("percent", percent)?;
            }
            payload.set_item("progress", progress_payload)?;
        }

        callback.call1(py, (payload,))?;
        Ok(())
    })
    .map_err(|err| err.to_string())
}

fn generation_progress_snapshot(current: usize, total: usize) -> ProgressSnapshot {
    let percent = if total == 0 {
        0.0
    } else {
        ((current as f64 / total as f64) * 1000.0).round() / 10.0
    };

    ProgressSnapshot {
        current: Some(current),
        total: Some(total),
        percent: Some(percent.min(99.0)),
    }
}

fn run_optimizer(
    ctx: &Context,
    progress_callback: Option<&Py<PyAny>>,
) -> Result<NativeResponse, String> {
    let islands = ctx.config.island_count.max(1);

    // Генерируем независимые под-сиды из основного сида детерминированно
    let mut seed_rng = StdRng::seed_from_u64(ctx.seed);
    let island_seeds: Vec<u64> = (0..islands).map(|_| seed_rng.gen::<u64>()).collect();
    let total_generations = islands.saturating_mul(ctx.config.generation_count);

    emit_progress_event(
        progress_callback,
        "optimizing",
        format!("Rust MOO initialized {islands} search islands"),
        Some(generation_progress_snapshot(0, total_generations)),
    )?;

    // Гетерогенные острова: каждый остров получает свой профиль весов.
    // Профили циклически переиспользуются, если островов больше, чем профилей.
    let profiles = default_island_profiles();
    let per_island_ctx: Vec<Context> = (0..islands)
        .map(|i| ctx_with_profile(ctx, profiles[i % profiles.len()]))
        .collect();

    // Параллельно запускаем все острова. Каждый оптимизируется по своим весам,
    // но после завершения мы пересчитываем objectives по каноническим весам,
    // чтобы глобальный архив сравнивал решения в одной системе координат.
    let mut island_states: Vec<IslandState> = per_island_ctx
        .into_iter()
        .zip(island_seeds.into_iter())
        .map(|(local_ctx, seed)| init_island_state(local_ctx, seed))
        .collect::<Result<Vec<_>, _>>()?;

    while island_states.iter().any(|state| !state.stopped) {
        island_states
            .par_iter_mut()
            .try_for_each(|state| run_island_epoch(state, MIGRATION_INTERVAL_GENS))?;

        let completed_generations = island_states
            .iter()
            .map(|state| state.completed_generations)
            .sum::<usize>();
        let active_islands = island_states.iter().filter(|state| !state.stopped).count();
        let archive_candidates = island_states
            .iter()
            .map(|state| state.archive.len())
            .sum::<usize>();

        emit_progress_event(
            progress_callback,
            "optimizing",
            format!(
                "Rust MOO searched {completed_generations}/{total_generations} island generations; {active_islands} islands still active, archive candidates {archive_candidates}"
            ),
            Some(generation_progress_snapshot(
                completed_generations,
                total_generations,
            )),
        )?;

        if islands > 1 {
            let migrants_by_island: Vec<Vec<(Objectives, Solution)>> = island_states
                .iter()
                .map(|state| {
                    archive_select_items(
                        &state.archive,
                        MIGRATION_TOP_K.min(state.archive.len()),
                        &state.ctx,
                    )
                })
                .collect();

            for target_idx in 0..island_states.len() {
                if island_states[target_idx].stopped {
                    continue;
                }
                let mut incoming = Vec::new();
                let mut seen = HashSet::new();
                for (source_idx, migrants) in migrants_by_island.iter().enumerate() {
                    if source_idx == target_idx {
                        continue;
                    }
                    for item in migrants {
                        let sig = signature(&item.1, ctx);
                        if seen.insert(sig) {
                            incoming.push(item.clone());
                        }
                    }
                }
                inject_migrants(&mut island_states[target_idx], &incoming);
            }
        }
    }

    let completed_generations = island_states
        .iter()
        .map(|state| state.completed_generations)
        .sum::<usize>();
    emit_progress_event(
        progress_callback,
        "optimizing",
        format!(
            "Rust MOO search complete after {completed_generations} island generations; preparing Pareto archive"
        ),
        Some(ProgressSnapshot {
            percent: Some(99.0),
            ..ProgressSnapshot::default()
        }),
    )?;

    let island_results: Vec<Vec<(Objectives, Solution)>> = island_states
        .iter_mut()
        .map(|state| {
            finalize_island_state(state);
            state
                .archive
                .iter()
                .map(|(_, sol)| {
                    let obj = calculate_objectives(sol, ctx);
                    (obj, sol.clone())
                })
                .collect()
        })
        .collect();
    let mut repair_diagnostics = RepairDiagnostics::default();
    for state in &island_states {
        repair_diagnostics.merge(&state.repair_diagnostics);
    }

    // Сливаем архивы в один глобальный
    let mut global_archive: Vec<(Objectives, Solution)> = Vec::new();
    let mut global_sigs: HashSet<u64> = HashSet::new();
    for arch in island_results {
        for item in arch {
            archive_update(&mut global_archive, &mut global_sigs, item, ctx);
        }
    }
    if global_archive.is_empty() {
        return Err("empty global archive".into());
    }

    // Полируем ВЕСЬ глобальный архив — каждое решение до фиксированной точки.
    // Полированные варианты обновляют архив, если оказываются недоминируемыми.
    let polished: Vec<(Objectives, Solution)> = global_archive
        .par_iter()
        .map(|(_, sol)| {
            let pol = polish_pareto(sol, ctx, ctx.config.polish_max_passes);
            let pol_obj = calculate_objectives(&pol, ctx);
            (pol_obj, pol)
        })
        .collect();

    let mut final_archive: Vec<(Objectives, Solution)> = Vec::new();
    let mut final_sigs: HashSet<u64> = HashSet::new();
    for item in global_archive.drain(..) {
        archive_update(&mut final_archive, &mut final_sigs, item, ctx);
    }
    for item in polished {
        archive_update(&mut final_archive, &mut final_sigs, item, ctx);
    }

    // Ранжирование по композитному качеству: нормируем balance и comfort по min-max
    // в пределах финального архива и складываем — чем меньше, тем лучше.
    // Это даёт полный порядок на Парето-фронте (которого при чистом лексикографическом
    // сравнении не существует) и ставит лучшие решения в начало, худшие — в конец.
    let variant_limit = ctx
        .config
        .max_result_variants
        .max(1)
        .min(final_archive.len());
    let objs: Vec<Objectives> = final_archive.iter().map(|(o, _)| *o).collect();
    let normed = normalize_objectives(&objs);
    let scores: Vec<f64> = normed.iter().map(|o| o.balance + o.comfort).collect();
    let signatures: Vec<u64> = final_archive
        .iter()
        .map(|(_, sol)| signature(sol, ctx))
        .collect();
    let mut score_order: Vec<usize> = (0..final_archive.len()).collect();
    score_order.sort_by(|&left, &right| {
        scores[left]
            .partial_cmp(&scores[right])
            .unwrap_or(Ordering::Equal)
            // Тай-брейки: сырой balance, затем сырой comfort, затем сигнатура
            .then_with(|| {
                final_archive[left]
                    .0
                    .balance
                    .partial_cmp(&final_archive[right].0.balance)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| {
                final_archive[left]
                    .0
                    .comfort
                    .partial_cmp(&final_archive[right].0.comfort)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| signatures[left].cmp(&signatures[right]))
    });
    let selected_indices: Vec<usize> = if final_archive.len() > variant_limit {
        let primary_idx = score_order[0];
        let mut selected = Vec::with_capacity(variant_limit);
        selected.push(primary_idx);
        for idx in archive_selection_order(&final_archive, ctx) {
            if idx != primary_idx {
                selected.push(idx);
                if selected.len() >= variant_limit {
                    break;
                }
            }
        }
        let mut tail = selected[1..].to_vec();
        tail.sort_by(|&left, &right| {
            scores[left]
                .partial_cmp(&scores[right])
                .unwrap_or(Ordering::Equal)
                .then_with(|| {
                    final_archive[left]
                        .0
                        .balance
                        .partial_cmp(&final_archive[right].0.balance)
                        .unwrap_or(Ordering::Equal)
                })
                .then_with(|| {
                    final_archive[left]
                        .0
                        .comfort
                        .partial_cmp(&final_archive[right].0.comfort)
                        .unwrap_or(Ordering::Equal)
                })
                .then_with(|| signatures[left].cmp(&signatures[right]))
        });
        let mut ordered = Vec::with_capacity(variant_limit);
        ordered.push(primary_idx);
        ordered.extend(tail);
        ordered
    } else {
        score_order.into_iter().take(variant_limit).collect()
    };
    // Переупорядочиваем res согласно order, не ломая элементы
    let mut selected: Vec<(Objectives, Solution, f64, Objectives)> =
        Vec::with_capacity(selected_indices.len());
    let mut taken: Vec<Option<(Objectives, Solution)>> =
        final_archive.into_iter().map(Some).collect();
    for idx in selected_indices {
        if let Some(item) = taken[idx].take() {
            selected.push((item.0, item.1, scores[idx], normed[idx]));
        }
    }
    let variants = selected
        .into_iter()
        .map(|(obj, sol, score, norm)| {
            // #6: канонический порядок отображения — team_1 = самая сильная по total_rating,
            // team_N = самая слабая. Устраняет "прыжки" команд между вариантами в UI,
            // даёт side-by-side сравнимость. На фитнес не влияет (симметрия уже сколлапсирована
            // в signature для дедупа архива).
            let mut indexed_teams: Vec<(TeamState, f64)> = sol
                .into_iter()
                .map(|t| {
                    let stats = calculate_team_stats(ctx, &t);
                    (t, stats.total_rating)
                })
                .collect();
            indexed_teams.sort_by(|a, b| {
                b.1.partial_cmp(&a.1)
                    .unwrap_or(Ordering::Equal)
                    .then_with(|| a.0.id.cmp(&b.0.id))
            });
            let teams = indexed_teams
                .into_iter()
                .enumerate()
                .map(|(idx, (t, _))| TeamResponse {
                    id: idx + 1,
                    roster: t
                        .roster
                        .into_iter()
                        .enumerate()
                        .map(|(r, ps)| {
                            (
                                ctx.roles[r].clone(),
                                ps.into_iter()
                                    .map(|p| ctx.players[p].uuid.clone())
                                    .collect(),
                            )
                        })
                        .collect(),
                })
                .collect();
            VariantResponse {
                teams,
                balance: obj.balance,
                comfort: obj.comfort,
                balance_norm: norm.balance,
                comfort_norm: norm.comfort,
                score,
            }
        })
        .collect();
    Ok(NativeResponse {
        variants,
        repair_diagnostics,
    })
}

#[pyfunction]
#[pyo3(signature = (request_json, progress_callback=None))]
fn run_moo_optimizer(request_json: &str, progress_callback: Option<Py<PyAny>>) -> PyResult<String> {
    let req = serde_json::from_str::<NativeRequest>(request_json)
        .map_err(|e| PyValueError::new_err(format!("invalid payload: {e}")))?;
    let ctx = Context::from_request(req)
        .map_err(|e| PyValueError::new_err(format!("invalid data: {e}")))?;
    let resp = run_optimizer(&ctx, progress_callback.as_ref())
        .map_err(|e| PyValueError::new_err(format!("optimizer failed: {e}")))?;
    serde_json::to_string(&resp)
        .map_err(|e| PyValueError::new_err(format!("serialize failed: {e}")))
}

#[cfg(test)]
mod tests {
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
            intra_team_variance_weight: 0.8,
            max_role_discomfort_weight: 2.0,
            role_line_balance_weight: 1.0,
            role_spread_weight: 1.0,
            sub_role_collision_weight: 1.5,
            use_captains: false,
            tank_impact_weight: 1.4,
            dps_impact_weight: 1.0,
            support_impact_weight: 1.1,
            tank_gap_weight: 2.0,
            tank_std_weight: 1.5,
            effective_total_std_weight: 1.2,
            intra_team_std_weight: 0.7,
            internal_role_spread_weight: 0.3,
            convergence_patience: 0,
            convergence_epsilon: 0.005,
            mutation_rate_min: 0.15,
            mutation_rate_max: 0.65,
            island_count: 4,
            polish_max_passes: 50,
            greedy_seed_count: 3,
            stagnation_kick_patience: 15,
            crossover_rate: 0.85,
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
}

#[pymodule]
fn moo_core(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_moo_optimizer, m)?)?;
    Ok(())
}
