use std::collections::HashMap;

use super::*;

impl Context {
    pub(crate) fn from_request(request: NativeRequest) -> Result<Self, String> {
        let RoleLayout {
            roles,
            capacities,
            flex,
            settings: role_settings,
        } = RoleLayout::from_request(&request)?;

        let role_index: HashMap<&str, usize> = roles
            .iter()
            .enumerate()
            .map(|(index, role)| (role.as_str(), index))
            .collect();

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

        let low_rank_threshold = request.config.low_rank_threshold;
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

            for (role_idx, role) in roles.iter().enumerate() {
                ratings.push(player.ratings.get(role).copied().unwrap_or_default());
                can_play.push(player.can_play(role));
                subclasses.push(player.subclasses.get(role).cloned());
                discomfort.push(player.role_discomfort(role, flex[role_idx]));
            }

            // Низкоранговость — свойство человека: максимум по ВСЕМ его
            // рейтингам (включая роли вне маски), а не по назначенной роли.
            let is_low_rank = low_rank_threshold > 0.0
                && player
                    .ratings
                    .values()
                    .copied()
                    .max()
                    .unwrap_or(0) as f64
                    <= low_rank_threshold;

            // Основная роль игрока. Слот без роли (flex) — слот, а не роль:
            // даже если клиент прислал его в preferences, основной ролью он не
            // становится.
            let first_preference = player
                .preferences
                .iter()
                .filter_map(|role| role_index.get(role.as_str()).copied())
                .find(|&role_idx| !flex[role_idx]);

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
                is_low_rank,
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
            role_settings,
            num_teams: request.num_teams,
            seed: request.seed,
            players,
            config: request.config,
        })
    }
}
