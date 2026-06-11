use rand::prelude::*;

use crate::*;

pub(crate) fn solution_is_complete(solution: &Solution, context: &Context) -> bool {
    solution.iter().all(|team| {
        team.roster
            .iter()
            .enumerate()
            .all(|(r_idx, r)| r.len() == context.capacities[r_idx])
    })
}

pub(crate) fn create_empty_solution(context: &Context) -> Solution {
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
pub(crate) fn create_snake_draft_solution(context: &Context) -> Solution {
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

        // Залоченные капитаны — строго на свою команду; остальные (без лока) —
        // по кругу с retry по всем командам (раньше незалоченный капитан при
        // занятом слоте молча выпадал и доезжал только через repair).
        let mut t = 0usize;
        for p in captains {
            if let Some(ct) = context.players[p].captain_team {
                if ct < teams.len() && teams[ct].roster[r].len() < context.capacities[r] {
                    teams[ct].roster[r].push(p);
                    continue;
                }
            }
            for _ in 0..context.num_teams {
                let target = t % context.num_teams;
                t += 1;
                if teams[target].roster[r].len() < context.capacities[r] {
                    teams[target].roster[r].push(p);
                    break;
                }
            }
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
pub(crate) fn create_comfort_greedy_solution(context: &Context) -> Solution {
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

pub(crate) fn create_random_solution(context: &Context, rng: &mut MooRng) -> Solution {
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
