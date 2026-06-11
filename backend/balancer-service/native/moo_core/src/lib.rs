use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rand::prelude::*;
use rand_chacha::ChaCha12Rng;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap, HashSet};

type Solution = Vec<TeamState>;

/// Закреплённый генератор: ChaCha12 — тот же алгоритм, что у `rand::rngs::StdRng`
/// в rand 0.8, но с документированной стабильностью потока между версиями rand.
/// Контракт детерминизма (same seed → same output) не должен зависеть от апгрейдов rand.
type MooRng = ChaCha12Rng;

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
    1.0
}
fn default_tank_std_weight() -> f64 {
    1.5
}
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
    max_role_discomfort_weight: f64,
    /// Средний по командам максимум боли — «хвостовой» comfort-член.
    #[serde(default = "default_team_max_pain_weight")]
    team_max_pain_weight: f64,
    role_line_balance_weight: f64,
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

/// Решение с кэшированной канонической сигнатурой. Сигнатура — чистая функция
/// решения; кэш избавляет от её пересчёта в prune/selection/migration/ranking
/// (раньше — O(n log n) пересчётов внутри компараторов сортировки).
#[derive(Debug, Clone)]
struct ArchiveEntry {
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
    breakdown: ObjectiveBreakdown,
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

#[pyfunction]
#[pyo3(signature = (request_json, progress_callback=None))]
fn run_moo_optimizer(
    py: Python<'_>,
    request_json: &str,
    progress_callback: Option<Py<PyAny>>,
) -> PyResult<String> {
    // GIL отпускается на всё время оптимизации — иначе event loop сервиса
    // замирает на минуты. emit_progress_event берёт GIL заново на каждое событие.
    py.allow_threads(|| {
        let req = serde_json::from_str::<NativeRequest>(request_json)
            .map_err(|e| PyValueError::new_err(format!("invalid payload: {e}")))?;
        let ctx = Context::from_request(req)
            .map_err(|e| PyValueError::new_err(format!("invalid data: {e}")))?;
        let resp = run_optimizer(&ctx, progress_callback.as_ref())
            .map_err(|e| PyValueError::new_err(format!("optimizer failed: {e}")))?;
        serde_json::to_string(&resp)
            .map_err(|e| PyValueError::new_err(format!("serialize failed: {e}")))
    })
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

#[pymodule]
fn moo_core(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_moo_optimizer, m)?)?;
    Ok(())
}
