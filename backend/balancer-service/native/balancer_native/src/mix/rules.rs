//! Soft rules of the mix engine: penalties added to a candidate's total after
//! the four base terms, declared per request in `config.mix_rules`.
//!
//! Invariants every rule keeps: the penalty is non-negative (the search prunes
//! on partial sums) and homogeneous of degree 1 in rating (Python rescales it
//! back from the canonical rating scale like the other rating-unit terms).
//! A rule may also group each team's seats (lanes); that grouping is computed
//! only for the variants returned, never kept per candidate.

use serde::{Deserialize, Serialize};

/// A rule as the request declares it.
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub(crate) enum RuleSpec {
    LaneMatchup(LaneMatchupSpec),
}

/// Lanes of `layout[k]` seats per team; lane `k` of team 1 faces lane `k` of
/// team 2. `weight` prices opponents of unequal strength (seat by seat, each
/// lane sorted strongest first), `cohesion_weight` prices a lane whose own
/// players differ in strength.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LaneMatchupSpec {
    layout: Vec<usize>,
    weight: f32,
    cohesion_weight: f32,
}

/// Seat-to-lane assignments per team beyond this make the per-candidate
/// pairing search (assignments squared) too slow for an interactive balance.
const MAX_LANE_ASSIGNMENTS: usize = 1000;

/// What a rule reports for one returned variant.
#[derive(Debug, Clone, Serialize)]
pub(crate) struct RuleResult {
    pub(crate) penalty: f32,
    /// Per team, per group, the seat indices of that team, strongest first.
    #[serde(skip)]
    pub(crate) groups: [Vec<Vec<usize>>; 2],
    /// `groups` resolved to player uuids by the engine.
    pub(crate) teams: Vec<Vec<Vec<String>>>,
}

pub(crate) enum Rule {
    LaneMatchup(LaneMatchup),
}

pub(crate) struct LaneMatchup {
    weight: f32,
    cohesion_weight: f32,
    /// Start of each lane inside a team's lane-ordered rating vector.
    offsets: Vec<usize>,
    team_size: usize,
    /// Every seat -> lane assignment, flattened with stride `team_size`.
    assignments: Vec<u8>,
}

/// Reused buffers so a candidate's rule evaluation allocates nothing.
#[derive(Default)]
pub(crate) struct RuleScratch {
    sorted1: Vec<i32>,
    sorted2: Vec<i32>,
    cohesion1: Vec<i32>,
    cohesion2: Vec<i32>,
}

impl Rule {
    pub(crate) fn compile(spec: RuleSpec, team_size: usize) -> Result<Self, String> {
        match spec {
            RuleSpec::LaneMatchup(spec) => {
                LaneMatchup::compile(spec, team_size).map(Rule::LaneMatchup)
            }
        }
    }

    pub(crate) fn kind(&self) -> &'static str {
        match self {
            Rule::LaneMatchup(_) => "lane_matchup",
        }
    }

    /// The rule's penalty for these seat ratings: exact when it is at most
    /// `budget`, otherwise any value above `budget`.
    pub(crate) fn penalty(
        &self,
        r1: &[i32],
        r2: &[i32],
        budget: f32,
        scratch: &mut RuleScratch,
    ) -> f32 {
        match self {
            Rule::LaneMatchup(rule) => rule.best(r1, r2, budget, scratch).0,
        }
    }

    pub(crate) fn result(&self, r1: &[i32], r2: &[i32], scratch: &mut RuleScratch) -> RuleResult {
        match self {
            Rule::LaneMatchup(rule) => rule.result(r1, r2, scratch),
        }
    }
}

impl LaneMatchup {
    fn compile(spec: LaneMatchupSpec, team_size: usize) -> Result<Self, String> {
        let LaneMatchupSpec {
            layout,
            weight,
            cohesion_weight,
        } = spec;
        if !(weight.is_finite()
            && weight >= 0.0
            && cohesion_weight.is_finite()
            && cohesion_weight >= 0.0)
        {
            return Err("lane_matchup weights must be finite and non-negative".to_string());
        }
        if layout.is_empty() || layout.contains(&0) || layout.len() > u8::MAX as usize {
            return Err(format!(
                "lane_matchup layout must list positive lane sizes, got {layout:?}"
            ));
        }
        if layout.iter().sum::<usize>() != team_size {
            return Err(format!(
                "lane_matchup layout {layout:?} does not seat a team of {team_size}"
            ));
        }
        // Count the seatings (team_size! / Π size!) before building them, so a
        // layout of many tiny lanes is refused instead of exhausting memory.
        let mut seatings: usize = 1;
        let mut placed = 0;
        for &size in &layout {
            for k in 1..=size {
                placed += 1;
                seatings = seatings * placed / k;
                if seatings > MAX_LANE_ASSIGNMENTS {
                    return Err(format!(
                        "lane_matchup layout {layout:?} has too many seatings to search"
                    ));
                }
            }
        }
        let mut assignments = Vec::new();
        let mut current = vec![0u8; team_size];
        let mut remaining = layout.clone();
        super::generate_role_masks(0, &mut current, &mut remaining, &mut assignments);
        let offsets = layout
            .iter()
            .scan(0, |start, &size| {
                let lane_start = *start;
                *start += size;
                Some(lane_start)
            })
            .collect();
        Ok(Self {
            weight,
            cohesion_weight,
            offsets,
            team_size,
            assignments,
        })
    }

    fn count(&self) -> usize {
        self.assignments.len() / self.team_size
    }

    fn assignment(&self, idx: usize) -> &[u8] {
        &self.assignments[idx * self.team_size..(idx + 1) * self.team_size]
    }

    /// Per assignment: the team's ratings in lane order, each lane strongest
    /// first, into `sorted` (stride `team_size`), and the sum of each lane's
    /// strongest-minus-weakest into `cohesion`.
    fn tabulate(&self, ratings: &[i32], sorted: &mut Vec<i32>, cohesion: &mut Vec<i32>) {
        let n = self.team_size;
        sorted.clear();
        sorted.resize(self.count() * n, 0);
        cohesion.clear();
        let mut fill = vec![0usize; self.offsets.len()];
        for idx in 0..self.count() {
            let row = &mut sorted[idx * n..(idx + 1) * n];
            fill.iter_mut().for_each(|f| *f = 0);
            for (&lane, &rating) in self.assignment(idx).iter().zip(ratings) {
                let lane = lane as usize;
                row[self.offsets[lane] + fill[lane]] = rating;
                fill[lane] += 1;
            }
            let mut spread = 0;
            for (lane, &start) in self.offsets.iter().enumerate() {
                let segment = &mut row[start..start + fill[lane]];
                segment.sort_unstable_by(|a, b| b.cmp(a));
                spread += segment[0] - segment[segment.len() - 1];
            }
            cohesion.push(spread);
        }
    }

    /// Cheapest pairing of a team-1 and a team-2 assignment: `(penalty, a1,
    /// a2)`. Ties go to the first pair in enumeration order. A penalty above
    /// `budget` is only a lower bound.
    fn best(
        &self,
        r1: &[i32],
        r2: &[i32],
        budget: f32,
        scratch: &mut RuleScratch,
    ) -> (f32, usize, usize) {
        let RuleScratch {
            sorted1,
            sorted2,
            cohesion1,
            cohesion2,
        } = scratch;
        self.tabulate(r1, sorted1, cohesion1);
        self.tabulate(r2, sorted2, cohesion2);
        let n = self.team_size;
        let mut best = (f32::INFINITY, 0, 0);
        for a1 in 0..self.count() {
            let row1 = &sorted1[a1 * n..(a1 + 1) * n];
            for a2 in 0..self.count() {
                let cohesion = self.cohesion_weight * (cohesion1[a1] + cohesion2[a2]) as f32;
                let bound = best.0.min(budget);
                if cohesion > bound {
                    continue;
                }
                let row2 = &sorted2[a2 * n..(a2 + 1) * n];
                let gap: i32 = row1.iter().zip(row2).map(|(a, b)| (a - b).abs()).sum();
                let penalty = cohesion + self.weight * gap as f32;
                if penalty < best.0 {
                    best = (penalty, a1, a2);
                }
            }
        }
        best
    }

    fn result(&self, r1: &[i32], r2: &[i32], scratch: &mut RuleScratch) -> RuleResult {
        let (penalty, a1, a2) = self.best(r1, r2, f32::INFINITY, scratch);
        let lanes = |ratings: &[i32], assignment: &[u8]| -> Vec<Vec<usize>> {
            let mut lanes = vec![Vec::new(); self.offsets.len()];
            for (seat, &lane) in assignment.iter().enumerate() {
                lanes[lane as usize].push(seat);
            }
            for lane in &mut lanes {
                // Stable: equal ratings keep seat order.
                lane.sort_by(|&a, &b| ratings[b].cmp(&ratings[a]));
            }
            lanes
        };
        RuleResult {
            penalty,
            groups: [
                lanes(r1, self.assignment(a1)),
                lanes(r2, self.assignment(a2)),
            ],
            teams: Vec::new(),
        }
    }
}
