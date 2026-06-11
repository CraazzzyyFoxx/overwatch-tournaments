use std::collections::{HashMap, HashSet};

use crate::*;

impl Context {
    pub(crate) fn from_request(request: NativeRequest) -> Result<Self, String> {
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

        // Валидация входа: без неё избыток игроков молча выпадает из результата
        // (ensure_feasibility закрывает только вакансии), а недобор падает
        // криптовой ошибкой "Incomplete initial solution" глубоко в инициализации.
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
        let cfg = &request.config;
        if cfg.population_size == 0 {
            return Err("population_size must be >= 1".to_string());
        }
        if !(0.0..=1.0).contains(&cfg.mutation_rate) {
            return Err(format!(
                "mutation_rate must be in [0, 1], got {}",
                cfg.mutation_rate
            ));
        }
        if !(0.0..=1.0).contains(&cfg.crossover_rate) {
            return Err(format!(
                "crossover_rate must be in [0, 1], got {}",
                cfg.crossover_rate
            ));
        }
        if cfg.mutation_rate_min > cfg.mutation_rate_max {
            return Err(format!(
                "mutation_rate_min ({}) must be <= mutation_rate_max ({})",
                cfg.mutation_rate_min, cfg.mutation_rate_max
            ));
        }

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
