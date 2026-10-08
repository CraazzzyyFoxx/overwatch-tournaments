//! Mix engine: exhaustive search over every player/role split of exactly two
//! equal teams, so it returns the true optimum rather than a GA
//! approximation. Port of the mixtura-dev/mixtura-balancer C++ core (MIT,
//! commit e48ec2bb): same four quality terms in `f32`, same pruning.
//!
//! Differences from the C++ original: each split is enumerated once (player 0
//! always sits on team 1) instead of once per mirror, the balance limit is
//! optional, and ties are ranked by enumeration order so the output does not
//! depend on the thread count.

use pyo3::prelude::*;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use std::collections::{BTreeMap, BinaryHeap};

use crate::common::*;

fn one() -> f32 {
    1.0
}
fn default_priority_imbalance_weight() -> f32 {
    0.2
}
fn default_priority_imbalance_threshold() -> i32 {
    1
}
fn default_max_priority() -> i32 {
    3
}

/// The bitmask split representation caps the lobby at 32 players; the
/// search is intractable long before that anyway.
const MAX_PLAYERS: usize = 32;

/// Unknown keys are rejected: nothing else checks that Python sends the names
/// this struct reads, and a misspelled weight would silently fall back to 1.0.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct MixConfig {
    max_result_variants: usize,
    /// |team strength gap| term (upstream `alpha`).
    #[serde(default = "one")]
    fairness_weight: f32,
    /// Per-role strength gap term (upstream `beta`).
    #[serde(default = "one")]
    role_fairness_weight: f32,
    /// Lost preference points term (upstream `gamma`).
    #[serde(default = "one")]
    role_priority_weight: f32,
    /// Extra lost points per point of imbalance between the teams (upstream `xi`).
    #[serde(default = "default_priority_imbalance_weight")]
    priority_imbalance_weight: f32,
    /// The imbalance must exceed this before it is penalized.
    #[serde(default = "default_priority_imbalance_threshold")]
    priority_imbalance_threshold: i32,
    /// Power-mean exponents of the fairness/uniformity/role-fairness terms
    /// (upstream `p`/`q`/`g`).
    #[serde(default = "one")]
    fairness_power: f32,
    #[serde(default = "one")]
    uniformity_power: f32,
    #[serde(default = "one")]
    role_fairness_power: f32,
    #[serde(default = "default_max_priority")]
    max_priority: i32,
    /// Drop candidates scoring above this. `None`: no limit, the best split
    /// always comes back.
    #[serde(default)]
    balance_limit: Option<f32>,
}

/// Per-role knobs the mix engine reads, flattened into the role entry.
#[derive(Debug, Clone, Copy, Deserialize)]
pub(crate) struct MixRoleSettings {
    /// Multiplier of this role's gap inside the role-fairness term.
    weight: f32,
}

pub(crate) type MixRequest = Request<MixConfig, MixRoleSettings>;

#[derive(Debug, Clone, Copy, Default, Serialize)]
struct MixMetrics {
    fairness: f32,
    uniformity: f32,
    role_fairness: f32,
    role_points: f32,
    total: f32,
}

#[derive(Debug, Serialize)]
pub(crate) struct MixResponse {
    variants: Vec<VariantResponse<MixMetrics>>,
}

struct Engine {
    roles: Vec<String>,
    team_size: usize,
    uuids: Vec<String>,
    /// Every per-seat role sequence that fills each role exactly to capacity,
    /// flattened with stride `team_size`.
    role_masks: Vec<u8>,
    /// Per player, per role.
    ratings: Vec<Vec<i32>>,
    playable: Vec<Vec<bool>>,
    priority: Vec<Vec<i32>>,
    role_weight: Vec<f32>,
    cfg: MixConfig,
}

/// Rank key: lower total first, then enumeration order — a total order, so
/// the result is the same however the splits were divided between threads.
#[derive(Debug, Clone, Copy)]
struct Candidate {
    metrics: MixMetrics,
    split: usize,
    mask1: usize,
    mask2: usize,
}

impl Candidate {
    fn key(&self) -> (usize, usize, usize) {
        (self.split, self.mask1, self.mask2)
    }
}

impl Ord for Candidate {
    fn cmp(&self, other: &Self) -> Ordering {
        self.metrics
            .total
            .total_cmp(&other.metrics.total)
            .then_with(|| self.key().cmp(&other.key()))
    }
}

impl PartialOrd for Candidate {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl PartialEq for Candidate {
    fn eq(&self, other: &Self) -> bool {
        self.cmp(other) == Ordering::Equal
    }
}

impl Eq for Candidate {}

/// Per-thread search state: the best `limit` candidates seen (worst on top
/// for O(1) rejection) plus whether any split was seatable at all.
struct Worker {
    best: BinaryHeap<Candidate>,
    limit: usize,
    any_mask_valid: bool,
    any_within_limit: bool,
}

impl Worker {
    fn new(limit: usize) -> Self {
        Self {
            best: BinaryHeap::with_capacity(limit + 1),
            limit,
            any_mask_valid: false,
            any_within_limit: false,
        }
    }

    fn threshold(&self, balance_limit: f32) -> f32 {
        match self.best.peek() {
            Some(worst) if self.best.len() >= self.limit => balance_limit.min(worst.metrics.total),
            _ => balance_limit,
        }
    }

    fn offer(&mut self, candidate: Candidate) {
        if self.best.len() < self.limit {
            self.best.push(candidate);
        } else if self.best.peek().is_some_and(|worst| candidate < *worst) {
            self.best.pop();
            self.best.push(candidate);
        }
    }

    fn merge(mut self, other: Self) -> Self {
        self.any_mask_valid |= other.any_mask_valid;
        self.any_within_limit |= other.any_within_limit;
        for candidate in other.best {
            self.offer(candidate);
        }
        self
    }
}

impl Engine {
    fn new(request: MixRequest) -> Result<Self, String> {
        let RoleLayout {
            roles,
            capacities,
            flex: _,
            settings,
        } = RoleLayout::from_request(&request)?;
        if request.num_teams != 2 {
            return Err(format!(
                "mix engine supports exactly 2 teams, got {}",
                request.num_teams
            ));
        }
        if request.players.len() > MAX_PLAYERS {
            return Err(format!(
                "too many players for an exhaustive mix search: {} (max {MAX_PLAYERS})",
                request.players.len()
            ));
        }
        let cfg = request.config;
        let team_size: usize = capacities.iter().sum();

        let mut role_masks = Vec::new();
        let mut current = vec![0u8; team_size];
        let mut remaining = capacities;
        generate_role_masks(0, &mut current, &mut remaining, &mut role_masks);

        let players = request.players;
        let per_role = |f: &dyn Fn(&PlayerSpec, &str) -> i32| -> Vec<Vec<i32>> {
            players
                .iter()
                .map(|p| roles.iter().map(|role| f(p, role)).collect())
                .collect()
        };
        let ratings = per_role(&|p, role| p.ratings.get(role).copied().unwrap_or_default());
        let priority = per_role(&|p, role| p.role_priority(role, cfg.max_priority));
        let playable = players
            .iter()
            .map(|p| roles.iter().map(|role| p.can_play(role)).collect())
            .collect();
        let role_weight = settings.iter().map(|s| s.weight).collect();

        Ok(Self {
            uuids: players.into_iter().map(|p| p.uuid).collect(),
            roles,
            team_size,
            role_masks,
            ratings,
            playable,
            priority,
            role_weight,
            cfg,
        })
    }

    fn role_mask(&self, idx: usize) -> &[u8] {
        &self.role_masks[idx * self.team_size..(idx + 1) * self.team_size]
    }

    fn role_mask_count(&self) -> usize {
        self.role_masks.len() / self.team_size
    }

    /// Every team-1 bitmask of the lobby with player 0 on it: one per
    /// unordered split (Gosper's hack over all `team_size`-subsets).
    fn splits(&self) -> Vec<u32> {
        let limit = 1u64 << self.uuids.len();
        let mut mask: u64 = (1u64 << self.team_size) - 1;
        let mut out = Vec::new();
        while mask < limit {
            if mask & 1 == 1 {
                out.push(mask as u32);
            }
            let c = mask & mask.wrapping_neg();
            let r = mask + c;
            mask = (((r ^ mask) >> 2) / c) | r;
        }
        out
    }

    fn members(&self, team1: u32) -> (Vec<usize>, Vec<usize>) {
        (0..self.uuids.len()).partition(|&p| team1 >> p & 1 == 1)
    }

    fn valid_masks(&self, team: &[usize]) -> Vec<usize> {
        (0..self.role_mask_count())
            .filter(|&mi| {
                self.role_mask(mi)
                    .iter()
                    .zip(team)
                    .all(|(&r, &p)| self.playable[p][r as usize])
            })
            .collect()
    }

    fn seat_ratings(&self, team: &[usize], mask: &[u8], out: &mut [i32]) {
        for ((slot, &p), &r) in out.iter_mut().zip(team).zip(mask) {
            *slot = self.ratings[p][r as usize];
        }
    }

    fn fairness(&self, r1: &[i32], r2: &[i32]) -> f32 {
        let p = self.cfg.fairness_power;
        let sum1 = r1.iter().fold(0.0f32, |acc, &r| acc + (r as f32).powf(p));
        let sum2 = r2.iter().fold(0.0f32, |acc, &r| acc + (r as f32).powf(p));
        self.cfg.fairness_weight * (sum1.powf(1.0 / p) - sum2.powf(1.0 / p)).abs()
    }

    fn uniformity(&self, r1: &[i32], r2: &[i32]) -> f32 {
        let total = r1.len() + r2.len();
        let mean = r1.iter().chain(r2).fold(0.0f32, |acc, &r| acc + r as f32) / total as f32;
        let q = self.cfg.uniformity_power;
        let dev = |team: &[i32]| -> f32 {
            let sum = team
                .iter()
                .fold(0.0f32, |acc, &r| acc + (r as f32 - mean).abs().powf(q));
            (sum / team.len() as f32).powf(1.0 / q)
        };
        (dev(r1) - dev(r2)).abs()
    }

    fn role_fairness(&self, r1: &[i32], r2: &[i32], m1: &[u8], m2: &[u8]) -> f32 {
        let num_roles = self.roles.len();
        let mut sums = vec![0i32; num_roles * 2];
        for i in 0..self.team_size {
            sums[m1[i] as usize] += r1[i];
            sums[num_roles + m2[i] as usize] += r2[i];
        }
        let g = self.cfg.role_fairness_power;
        let weighted_sum = (0..num_roles).fold(0.0f32, |acc, role| {
            let diff = (sums[role] - sums[num_roles + role]).abs() as f32;
            acc + (diff * self.role_weight[role]).powf(g)
        });
        self.cfg.role_fairness_weight * (weighted_sum / num_roles as f32).powf(1.0 / g)
    }

    fn role_points(&self, t1: &[usize], t2: &[usize], m1: &[u8], m2: &[u8]) -> f32 {
        let max = self.cfg.max_priority;
        let lost = |team: &[usize], mask: &[u8]| -> i32 {
            team.iter()
                .zip(mask)
                .map(|(&p, &r)| max - self.priority[p][r as usize])
                .sum()
        };
        let (lost1, lost2) = (lost(t1, m1), lost(t2, m2));
        let mut total = lost1 + lost2;
        let imbalance = (lost1 - lost2).abs();
        if imbalance > self.cfg.priority_imbalance_threshold {
            total += (self.cfg.priority_imbalance_weight * imbalance as f32) as i32;
        }
        self.cfg.role_priority_weight * total as f32
    }

    fn search_split(&self, worker: &mut Worker, split: usize, team1: u32, balance_limit: f32) {
        let (t1, t2) = self.members(team1);
        let valid1 = self.valid_masks(&t1);
        let valid2 = self.valid_masks(&t2);
        if valid1.is_empty() || valid2.is_empty() {
            return;
        }
        worker.any_mask_valid = true;

        let mut r1 = vec![0i32; self.team_size];
        let mut r2 = vec![0i32; self.team_size];
        let mut threshold = worker.threshold(balance_limit);
        for &mi1 in &valid1 {
            let m1 = self.role_mask(mi1);
            self.seat_ratings(&t1, m1, &mut r1);
            for &mi2 in &valid2 {
                let m2 = self.role_mask(mi2);
                self.seat_ratings(&t2, m2, &mut r2);

                // Cheapest term first; every term is non-negative, so any
                // partial sum above the threshold rules the candidate out.
                let fairness = self.fairness(&r1, &r2);
                if fairness > threshold {
                    continue;
                }
                let role_fairness = self.role_fairness(&r1, &r2, m1, m2);
                let mut partial = fairness + role_fairness;
                if partial > threshold {
                    continue;
                }
                let uniformity = self.uniformity(&r1, &r2);
                partial += uniformity;
                if partial > threshold {
                    continue;
                }
                let role_points = self.role_points(&t1, &t2, m1, m2);
                let total = fairness + role_fairness + role_points + uniformity;
                if total > threshold {
                    continue;
                }
                worker.any_within_limit = true;
                worker.offer(Candidate {
                    metrics: MixMetrics {
                        fairness,
                        uniformity,
                        role_fairness,
                        role_points,
                        total,
                    },
                    split,
                    mask1: mi1,
                    mask2: mi2,
                });
                threshold = worker.threshold(balance_limit);
            }
        }
    }

    fn team_response(&self, id: usize, team: &[usize], mask: &[u8]) -> TeamResponse {
        let mut roster: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for (&p, &r) in team.iter().zip(mask) {
            roster
                .entry(self.roles[r as usize].clone())
                .or_default()
                .push(self.uuids[p].clone());
        }
        TeamResponse { id, roster }
    }
}

fn generate_role_masks(pos: usize, current: &mut [u8], remaining: &mut [usize], out: &mut Vec<u8>) {
    if pos == current.len() {
        out.extend_from_slice(current);
        return;
    }
    for role in 0..remaining.len() {
        if remaining[role] > 0 {
            remaining[role] -= 1;
            current[pos] = role as u8;
            generate_role_masks(pos + 1, current, remaining, out);
            remaining[role] += 1;
        }
    }
}

pub(crate) fn run(
    request: MixRequest,
    progress_callback: Option<&Py<PyAny>>,
) -> Result<MixResponse, String> {
    let engine = Engine::new(request)?;
    let wanted = engine.cfg.max_result_variants.max(1);
    let balance_limit = engine.cfg.balance_limit.unwrap_or(f32::INFINITY);
    let splits = engine.splits();

    emit_progress_event(
        progress_callback,
        "optimizing",
        format!("Mix exhaustive search over {} team splits", splits.len()),
        Some(ProgressSnapshot {
            current: Some(0),
            total: Some(splits.len()),
            percent: Some(0.0),
        }),
    )?;

    let result = splits
        .par_iter()
        .enumerate()
        .fold(
            || Worker::new(wanted),
            |mut worker, (idx, &team1)| {
                engine.search_split(&mut worker, idx, team1, balance_limit);
                worker
            },
        )
        .reduce(|| Worker::new(wanted), Worker::merge);

    if !result.any_mask_valid {
        return Err("Not enough players for each role".to_string());
    }
    if !result.any_within_limit {
        return Err("Can't shuffle players within balance limit".to_string());
    }

    let variants = result
        .best
        .into_sorted_vec()
        .into_iter()
        .map(|candidate| {
            let (t1, t2) = engine.members(splits[candidate.split]);
            VariantResponse {
                teams: vec![
                    engine.team_response(1, &t1, engine.role_mask(candidate.mask1)),
                    engine.team_response(2, &t2, engine.role_mask(candidate.mask2)),
                ],
                metrics: candidate.metrics,
            }
        })
        .collect();

    emit_progress_event(
        progress_callback,
        "optimizing",
        "Mix exhaustive search complete".to_string(),
        Some(ProgressSnapshot {
            current: Some(splits.len()),
            total: Some(splits.len()),
            percent: Some(99.0),
        }),
    )?;

    Ok(MixResponse { variants })
}

#[cfg(test)]
mod tests;
