//! Tournament engine: multi-objective (balance × comfort) island GA for any
//! number of teams, returning a ranked Pareto front.

use pyo3::prelude::*;
use rand::prelude::*;
use rand_chacha::ChaCha12Rng;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

pub(crate) use crate::common::*;

type Solution = Vec<TeamState>;

/// Закреплённый генератор: ChaCha12 — тот же алгоритм, что у `rand::rngs::StdRng`
/// в rand 0.8, но с документированной стабильностью потока между версиями rand.
/// Контракт детерминизма (same seed → same output) не должен зависеть от апгрейдов rand.
type MooRng = ChaCha12Rng;

// --- MOO Config Defaults ---
fn default_eff_total_std_weight() -> f64 {
    1.2
}
fn default_intra_team_std_weight() -> f64 {
    2.8
}
fn default_internal_role_spread_weight() -> f64 {
    1.2
}
fn default_team_max_pain_weight() -> f64 {
    1.0
}
fn default_low_rank_collision_weight() -> f64 {
    250.0
}
fn default_rank_comfort_tilt() -> f64 {
    0.5
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
fn default_team_crossover_share() -> f64 {
    0.5
}

const DEFAULT_ARCHIVE_LIMIT: usize = 96;
const MAX_ARCHIVE_LIMIT: usize = 200;
const ARCHIVE_ELITE_COUNT: usize = 3;
const ARCHIVE_SCORE_KEEP: usize = 5;
const MIGRATION_INTERVAL_GENS: usize = 20;
const MIGRATION_TOP_K: usize = 3;

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ConfigSpec {
    population_size: usize,
    generation_count: usize,
    mutation_rate: f64,
    mutation_strength: usize,
    max_result_variants: usize,
    average_mmr_balance_weight: f64,
    team_total_balance_weight: f64,
    max_team_gap_weight: f64,
    role_discomfort_weight: f64,
    max_role_discomfort_weight: f64,
    /// Средний по командам максимум боли — «хвостовой» comfort-член.
    #[serde(default = "default_team_max_pain_weight")]
    team_max_pain_weight: f64,
    role_line_balance_weight: f64,
    sub_role_collision_weight: f64,
    /// Порог «низкорангового» игрока в канонической шкале рейтингов
    /// (rating_scale_ceiling, обычно 3500). 0 = механика выключена.
    /// Игрок низкоранговый, если максимум его рейтингов ≤ порога.
    #[serde(default)]
    low_rank_threshold: f64,
    /// Штраф за каждую пару низкоранговых игроков в одной команде;
    /// нормируется на число команд, входит в balance-объектив.
    #[serde(default = "default_low_rank_collision_weight")]
    low_rank_collision_weight: f64,
    use_captains: bool,
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
    /// Доля team-preserving crossover среди скрещиваний (остальное —
    /// role-line). Принимается по wire опционально; в Python UI пока не
    /// выставляется.
    #[serde(default = "default_team_crossover_share")]
    team_crossover_share: f64,
    /// Жёсткий бюджет времени на оптимизацию (мс). None — без лимита.
    /// ВНИМАНИЕ: ограничение по wall-clock жертвует воспроизводимостью
    /// (same seed может дать другой результат при другой нагрузке CPU).
    #[serde(default)]
    time_limit_ms: Option<u64>,
    /// Сдвиг ранга баланс↔комфорт при упорядочивании вариантов (0.5 = текущее
    /// 50/50). Влияет ТОЛЬКО на финальный ранг/primary/отображаемый score, не на
    /// objective-поиск. Старые сохранённые конфиги без поля → 0.5.
    #[serde(default = "default_rank_comfort_tilt")]
    rank_comfort_tilt: f64,
}

/// Per-role knobs the GA reads. No defaults: the single source of truth is
/// Python's `AlgorithmConfig.role_settings`, and a silently defaulted weight
/// here would be a second one.
#[derive(Debug, Clone, Copy, Deserialize)]
pub(crate) struct MooRoleSettings {
    /// Множитель вклада роли в «эффективный тотал» команды.
    pub(crate) impact: f64,
    /// Штраф за наибольший разрыв между соседними (по силе) линиями роли.
    pub(crate) line_gap_weight: f64,
    /// Штраф за разброс силы линии роли между командами.
    pub(crate) line_std_weight: f64,
}

pub(crate) type NativeRequest = Request<ConfigSpec, MooRoleSettings>;

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
    is_low_rank: bool,
}

#[derive(Debug, Clone)]
pub(crate) struct Context {
    roles: Vec<String>,
    capacities: Vec<usize>,
    role_settings: Vec<MooRoleSettings>,
    num_teams: usize,
    seed: u64,
    players: Vec<PlayerData>,
    config: ConfigSpec,
}

#[derive(Debug, Clone)]
pub(crate) struct TeamState {
    id: usize,
    roster: Vec<Vec<usize>>,
}

#[derive(Debug, Clone)]
pub(crate) struct TeamStats {
    mmr: f64,
    total_rating: f64,
    discomfort: f64,
    intra_std: f64,
    max_pain: i32,
    subrole_collisions: i32,
    low_rank_pairs: i32,
    role_totals: Vec<f64>,
    role_counts: Vec<usize>,
    internal_role_spread: f64,
}

#[derive(Debug, Clone, Copy, Serialize)]
pub(crate) struct Objectives {
    balance: f64,
    comfort: f64,
}

/// Решение с кэшированной канонической сигнатурой. Сигнатура — чистая функция
/// решения; кэш избавляет от её пересчёта в prune/selection/migration/ranking
/// (раньше — O(n log n) пересчётов внутри компараторов сортировки).
#[derive(Debug, Clone)]
pub(crate) struct ArchiveEntry {
    obj: Objectives,
    sol: Solution,
    sig: u64,
}

impl ArchiveEntry {
    fn new(obj: Objectives, sol: Solution) -> Self {
        let sig = signature(&sol);
        Self { obj, sol, sig }
    }

    /// Пересчёт objectives без пересчёта сигнатуры (решение не меняется —
    /// используется при переоценке чужими/каноническими весами).
    fn rescored(&self, obj: Objectives) -> Self {
        Self {
            obj,
            sol: self.sol.clone(),
            sig: self.sig,
        }
    }
}

#[derive(Debug, Serialize)]
struct MooMetrics {
    balance: f64,
    comfort: f64,
    balance_norm: f64,
    comfort_norm: f64,
    score: f64,
    breakdown: ObjectiveBreakdown,
}

#[derive(Debug, Serialize)]
pub(crate) struct NativeResponse {
    variants: Vec<VariantResponse<MooMetrics>>,
    repair_diagnostics: RepairDiagnostics,
}

#[derive(Debug, Clone, Copy, Default, Serialize)]
pub(crate) struct RepairDiagnostics {
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
pub(crate) struct RepairNeed {
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

mod archive;
mod context;
mod island;
mod objectives;
mod operators;
mod polish;
mod repair;
mod runner;
mod seeding;

pub(crate) use archive::*;
pub(crate) use island::*;
pub(crate) use objectives::*;
pub(crate) use operators::*;
pub(crate) use polish::*;
pub(crate) use repair::*;
pub(crate) use runner::*;
pub(crate) use seeding::*;

pub(crate) fn run(
    request: NativeRequest,
    progress_callback: Option<&Py<PyAny>>,
) -> Result<NativeResponse, String> {
    let ctx = Context::from_request(request).map_err(|e| format!("invalid data: {e}"))?;
    run_optimizer(&ctx, progress_callback).map_err(|e| format!("optimizer failed: {e}"))
}

/// Внутренняя обвязка для criterion-бенчей (benches/moo_bench.rs) и
/// quality-harness. НЕ публичный API крейта: типы непрозрачны, сигнатуры
/// могут меняться без предупреждения.
#[doc(hidden)]
pub mod bench_api;

/// Quality-harness: многосидовые прогоны на фикстурах разных размеров с
/// операционными метриками верхнего варианта. Используется как A/B-гейт при
/// изменениях objective-функции: медианы метрик не должны регрессировать >5%.
/// Запуск с выводом: cargo test harness -- --nocapture (40t — за --ignored).
#[cfg(test)]
mod quality_harness;

#[cfg(test)]
mod tests;
