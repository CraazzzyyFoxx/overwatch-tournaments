//! Primitives both engines share: the request envelope, roster validation,
//! how a player rates a role, progress events and the response's team shape.
//! Each engine owns only its `config` and its per-variant `metrics`.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap, HashSet};

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct PlayerSpec {
    pub(crate) uuid: String,
    #[allow(dead_code)]
    pub(crate) name: String,
    pub(crate) ratings: HashMap<String, i32>,
    pub(crate) preferences: Vec<String>,
    pub(crate) subclasses: HashMap<String, String>,
    pub(crate) is_captain: bool,
    pub(crate) is_flex: bool,
    pub(crate) seed_role: Option<String>,
}

impl PlayerSpec {
    /// A rating for the role is what makes it playable; its value may be 0.
    pub(crate) fn can_play(&self, role: &str) -> bool {
        self.ratings.contains_key(role)
    }

    fn preference_position(&self, role: &str) -> Option<usize> {
        self.preferences.iter().position(|preference| preference == role)
    }

    /// Pain of seating the player on `role` (lower is better): 0 for a flex
    /// player or a role-less slot, 100 per step down the preference list,
    /// 1000 for a playable role they did not list, 5000 for one they cannot play.
    pub(crate) fn role_discomfort(&self, role: &str, is_flex_slot: bool) -> i32 {
        let playable = self.can_play(role);
        if playable && (self.is_flex || is_flex_slot) {
            0
        } else if let Some(position) = self.preference_position(role) {
            (position as i32) * 100
        } else if playable {
            1000
        } else {
            5000
        }
    }

    /// Preference points for `role` in `1..=max_priority` (higher is better):
    /// a flex player is equally happy anywhere, everyone else loses a point
    /// per step down their preference list, floored at 1.
    pub(crate) fn role_priority(&self, role: &str, max_priority: i32) -> i32 {
        if self.is_flex {
            return max_priority;
        }
        match self.preference_position(role) {
            Some(position) => (max_priority - position as i32).max(1),
            None => 1,
        }
    }
}

/// One roster role on the wire: its name, how many seats it has, whether it is
/// a role-less (flex) slot and the engine's own per-role settings, flattened
/// into the same object.
#[derive(Debug, Clone, Deserialize)]
pub(crate) struct RoleSpec<R> {
    pub(crate) name: String,
    pub(crate) slots: usize,
    #[serde(default)]
    pub(crate) flex: bool,
    #[serde(flatten)]
    pub(crate) settings: R,
}

#[derive(Debug, Deserialize)]
pub(crate) struct Request<C, R> {
    pub(crate) players: Vec<PlayerSpec>,
    pub(crate) num_teams: usize,
    pub(crate) seed: u64,
    pub(crate) roles: Vec<RoleSpec<R>>,
    pub(crate) config: C,
}

/// The roster shape every team fills: the request's active roles, sorted by
/// name, with their seat counts, flex flags and settings in that same order.
#[derive(Debug, Clone)]
pub(crate) struct RoleLayout<R> {
    pub(crate) roles: Vec<String>,
    pub(crate) capacities: Vec<usize>,
    pub(crate) flex: Vec<bool>,
    pub(crate) settings: Vec<R>,
}

impl<R: Clone> RoleLayout<R> {
    /// Validates what both engines need before they search: unique, non-empty
    /// roles, at least two teams, exactly one player per seat, unique uuids.
    pub(crate) fn from_request<C>(request: &Request<C, R>) -> Result<Self, String> {
        let mut seen_roles: HashSet<&str> = HashSet::with_capacity(request.roles.len());
        for role in &request.roles {
            if !seen_roles.insert(role.name.as_str()) {
                return Err(format!("duplicate role: {}", role.name));
            }
        }
        let mut active: Vec<&RoleSpec<R>> =
            request.roles.iter().filter(|role| role.slots > 0).collect();
        active.sort_by(|a, b| a.name.cmp(&b.name));
        if active.is_empty() {
            return Err("role_mask cannot be empty".to_string());
        }
        let roles: Vec<String> = active.iter().map(|role| role.name.clone()).collect();
        let capacities: Vec<usize> = active.iter().map(|role| role.slots).collect();

        // Без проверки избыток игроков молча выпадает из результата, а недобор
        // падает криптовой ошибкой глубоко в поиске.
        if request.num_teams < 2 {
            return Err(format!("num_teams must be >= 2, got {}", request.num_teams));
        }
        let slots_per_team: usize = capacities.iter().sum();
        let total_slots = slots_per_team * request.num_teams;
        if total_slots != request.players.len() {
            return Err(format!(
                "player count must equal total roster slots: {} players != {} slots ({} teams x {} slots per team)",
                request.players.len(),
                total_slots,
                request.num_teams,
                slots_per_team
            ));
        }
        let mut seen_uuids: HashSet<&str> = HashSet::with_capacity(request.players.len());
        for player in &request.players {
            if !seen_uuids.insert(player.uuid.as_str()) {
                return Err(format!("duplicate player uuid: {}", player.uuid));
            }
        }
        Ok(Self {
            roles,
            capacities,
            flex: active.iter().map(|role| role.flex).collect(),
            settings: active.iter().map(|role| role.settings.clone()).collect(),
        })
    }
}

#[derive(Debug, Serialize)]
pub(crate) struct TeamResponse {
    pub(crate) id: usize,
    pub(crate) roster: BTreeMap<String, Vec<String>>,
}

#[derive(Debug, Serialize)]
pub(crate) struct VariantResponse<M> {
    pub(crate) teams: Vec<TeamResponse>,
    pub(crate) metrics: M,
}

#[derive(Debug, Clone, Copy, Default)]
pub(crate) struct ProgressSnapshot {
    pub(crate) current: Option<usize>,
    pub(crate) total: Option<usize>,
    pub(crate) percent: Option<f64>,
}

pub(crate) fn emit_progress_event(
    progress_callback: Option<&Py<PyAny>>,
    stage: &str,
    message: String,
    progress: Option<ProgressSnapshot>,
) -> Result<(), String> {
    let Some(callback) = progress_callback else {
        return Ok(());
    };

    Python::attach(|py| -> PyResult<()> {
        let payload = PyDict::new(py);
        payload.set_item("status", "running")?;
        payload.set_item("stage", stage)?;
        payload.set_item("message", message)?;
        payload.set_item("level", "info")?;

        if let Some(progress) = progress {
            let progress_payload = PyDict::new(py);
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

/// JSON in, JSON out, with the GIL released for the whole solve — otherwise
/// the service's event loop freezes for its duration. Progress events
/// re-acquire it per event.
pub(crate) fn run_json<Req, Resp>(
    py: Python<'_>,
    request_json: &str,
    solve: impl FnOnce(Req) -> Result<Resp, String> + Send,
) -> PyResult<String>
where
    Req: DeserializeOwned,
    Resp: Serialize,
{
    py.detach(|| {
        let request = serde_json::from_str::<Req>(request_json)
            .map_err(|e| PyValueError::new_err(format!("invalid payload: {e}")))?;
        let response = solve(request).map_err(PyValueError::new_err)?;
        serde_json::to_string(&response)
            .map_err(|e| PyValueError::new_err(format!("serialize failed: {e}")))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn player(preferences: &[&str], rated: &[&str], is_flex: bool) -> PlayerSpec {
        PlayerSpec {
            uuid: "p".into(),
            name: "p".into(),
            ratings: rated.iter().map(|r| (r.to_string(), 2000)).collect(),
            preferences: preferences.iter().map(|r| r.to_string()).collect(),
            subclasses: HashMap::new(),
            is_captain: false,
            is_flex,
            seed_role: None,
        }
    }

    #[test]
    fn role_priority_follows_preference_order_floored_at_one() {
        let p = player(&["Tank", "Damage", "Support", "Flex"], &["Tank", "Damage", "Support"], false);
        assert_eq!(p.role_priority("Tank", 3), 3);
        assert_eq!(p.role_priority("Damage", 3), 2);
        assert_eq!(p.role_priority("Support", 3), 1);
        assert_eq!(p.role_priority("Flex", 3), 1, "past max_priority deep: floored");
        assert_eq!(p.role_priority("Unlisted", 3), 1);
    }

    #[test]
    fn flex_player_is_equally_happy_everywhere() {
        let p = player(&["Tank"], &["Tank", "Damage"], true);
        assert_eq!(p.role_priority("Damage", 3), 3);
        assert_eq!(p.role_discomfort("Damage", false), 0);
    }

    #[test]
    fn role_discomfort_ladders_by_preference_then_playability() {
        let p = player(&["Tank", "Damage"], &["Tank", "Damage", "Support"], false);
        assert_eq!(p.role_discomfort("Tank", false), 0);
        assert_eq!(p.role_discomfort("Damage", false), 100);
        assert_eq!(p.role_discomfort("Support", false), 1000);
        assert_eq!(p.role_discomfort("Healer", false), 5000);
        assert_eq!(p.role_discomfort("Support", true), 0, "role-less slot");
    }
}
