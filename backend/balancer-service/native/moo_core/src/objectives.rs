use serde::Serialize;
use std::cmp::Ordering;

use crate::*;

pub(crate) fn sample_stdev_from_sums(sum_x: f64, sum_x2: f64, count: usize) -> f64 {
    if count < 2 {
        return 0.0;
    }
    let variance = (sum_x2 - (sum_x * sum_x) / count as f64) / (count as f64 - 1.0);
    if variance <= 0.0 {
        return 0.0;
    }
    variance.sqrt()
}

/// Маржинальный (tax-bracket) штраф за разрыв тоталов: непрерывная выпуклая
/// кусочно-линейная функция. Прежняя версия умножала ВСЁ значение на
/// множитель текущей ступени — скачок p(50)=100 → p(50.01)=250 создавал обрывы
/// в ландшафте фитнеса, блокирующие локальный поиск возле порогов.
pub(crate) fn calculate_gap_penalty(max_team_gap: f64) -> f64 {
    // Ставки 1/3/8/18/40 откалиброваны так, чтобы в опорных точках величина
    // совпадала со старой мультипликативной формой (100→500, 200→2300≈2400,
    // 500→14300≈15000) — давление на разрыв сохранено, обрывы убраны.
    let gap = max_team_gap.max(0.0);
    gap.min(25.0)
        + (gap - 25.0).clamp(0.0, 25.0) * 3.0
        + (gap - 50.0).clamp(0.0, 50.0) * 8.0
        + (gap - 100.0).clamp(0.0, 100.0) * 18.0
        + (gap - 200.0).max(0.0) * 40.0
}

/// Маржинальный штраф за разрыв танк-линии (ставки 1×/3×/8×/20×), см.
/// calculate_gap_penalty.
pub(crate) fn tank_gap_penalty(gap: f64) -> f64 {
    let gap = gap.max(0.0);
    gap.min(50.0)
        + (gap - 50.0).clamp(0.0, 50.0) * 3.0
        + (gap - 100.0).clamp(0.0, 100.0) * 8.0
        + (gap - 200.0).max(0.0) * 20.0
}

pub(crate) fn calculate_team_stats(context: &Context, team: &TeamState) -> TeamStats {
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
    // Один Vec на вызов вместо HashMap на каждую роль: ростеры крошечные (1-2
    // игрока), линейный поиск дешевле хэширования; сумма пар порядконезависима.
    let mut subclass_counts: Vec<(&str, usize)> = Vec::new();

    for (role_index, roster) in team.roster.iter().enumerate() {
        if roster.is_empty() {
            continue;
        }

        let mut role_sum_rating = 0.0;
        subclass_counts.clear();

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
                if let Some(entry) = subclass_counts
                    .iter_mut()
                    .find(|(name, _)| *name == subclass)
                {
                    entry.1 += 1;
                } else {
                    subclass_counts.push((subclass, 1));
                }
            }
        }

        sum_rating += role_sum_rating;
        role_totals[role_index] = role_sum_rating;
        role_counts[role_index] = roster.len();

        let role_avg = role_sum_rating / roster.len() as f64;
        role_avg_sum += role_avg;
        role_avg_sum2 += role_avg * role_avg;
        role_avg_count += 1;

        for &(_, occurrences) in &subclass_counts {
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

/// Переиспользуемые буферы для горячего пути polish: устраняют аллокации
/// на каждую пробную перестановку. Арифметика и порядок обхода идентичны
/// одноразовой версии — результат бит-в-бит совпадает.
#[derive(Debug, Default)]
pub(crate) struct ObjectiveScratch {
    role_line_avgs: Vec<Vec<f64>>,
    tank_ratings: Vec<f64>,
    effective_totals: Vec<f64>,
}

impl ObjectiveScratch {
    fn reset(&mut self, num_roles: usize, team_count: usize) {
        if self.role_line_avgs.len() != num_roles {
            self.role_line_avgs.resize_with(num_roles, Vec::new);
        }
        for averages in &mut self.role_line_avgs {
            averages.clear();
            averages.reserve(team_count);
        }
        self.tank_ratings.clear();
        self.tank_ratings.reserve(team_count);
        self.effective_totals.clear();
        self.effective_totals.reserve(team_count);
    }
}

/// Поэлементная разбивка objective: сырые (до весов) значения каждого члена
/// плюс взвешенные итоги. Инвариант: balance/comfort == Σ(raw × вес из конфига)
/// — закреплено unit-тестом. Отдаётся в ответе по каждому варианту, чтобы
/// диагностика «какой член доминирует» была одной строкой, а не расследованием.
#[derive(Debug, Clone, Copy, Default, Serialize)]
pub(crate) struct ObjectiveBreakdown {
    pub(crate) total_rating_std: f64,
    pub(crate) gap_penalty: f64,
    pub(crate) mmr_std: f64,
    pub(crate) role_line_std: f64,
    pub(crate) intra_team_std_avg: f64,
    pub(crate) internal_role_spread_avg: f64,
    pub(crate) tank_adjacent_gap_penalty: f64,
    pub(crate) tank_std: f64,
    pub(crate) effective_total_std: f64,
    pub(crate) avg_discomfort: f64,
    pub(crate) global_max_pain: f64,
    pub(crate) avg_team_max_pain: f64,
    pub(crate) avg_subrole_collisions: f64,
    pub(crate) balance: f64,
    pub(crate) comfort: f64,
}

pub(crate) fn calculate_objectives_from_stats(stats: &[TeamStats], ctx: &Context) -> Objectives {
    let mut scratch = ObjectiveScratch::default();
    calculate_objectives_with_scratch(stats, ctx, &mut scratch)
}

pub(crate) fn calculate_objectives_with_scratch(
    stats: &[TeamStats],
    ctx: &Context,
    scratch: &mut ObjectiveScratch,
) -> Objectives {
    let breakdown = calculate_breakdown_with_scratch(stats, ctx, scratch);
    Objectives {
        balance: breakdown.balance,
        comfort: breakdown.comfort,
    }
}

pub(crate) fn calculate_objective_breakdown(
    solution: &Solution,
    ctx: &Context,
) -> ObjectiveBreakdown {
    let stats: Vec<TeamStats> = solution
        .iter()
        .map(|t| calculate_team_stats(ctx, t))
        .collect();
    let mut scratch = ObjectiveScratch::default();
    calculate_breakdown_with_scratch(&stats, ctx, &mut scratch)
}

pub(crate) fn calculate_breakdown_with_scratch(
    stats: &[TeamStats],
    ctx: &Context,
    scratch: &mut ObjectiveScratch,
) -> ObjectiveBreakdown {
    if stats.is_empty() {
        return ObjectiveBreakdown {
            balance: f64::INFINITY,
            comfort: f64::INFINITY,
            ..ObjectiveBreakdown::default()
        };
    }
    let team_count = stats.len();
    let mut sum_mmr = 0.0;
    let mut sum_mmr2 = 0.0;
    let mut sum_total = 0.0;
    let mut sum_total2 = 0.0;
    let mut min_team_total = f64::INFINITY;
    let mut max_team_total = f64::NEG_INFINITY;
    scratch.reset(ctx.roles.len(), team_count);
    let ObjectiveScratch {
        role_line_avgs,
        tank_ratings,
        effective_totals,
    } = scratch;
    let mut sum_discomfort = 0.0;
    let mut global_max_pain = 0i32;
    let mut sum_team_max_pain = 0i64;
    let mut sum_subrole_collisions = 0i32;
    let mut sum_intra_std = 0.0;
    let mut sum_internal_role_spread = 0.0;

    for s in stats {
        sum_mmr += s.mmr;
        sum_mmr2 += s.mmr * s.mmr;
        sum_total += s.total_rating;
        sum_total2 += s.total_rating * s.total_rating;
        min_team_total = min_team_total.min(s.total_rating);
        max_team_total = max_team_total.max(s.total_rating);
        sum_discomfort += s.discomfort;
        global_max_pain = global_max_pain.max(s.max_pain);
        sum_team_max_pain += s.max_pain as i64;
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

    // Выборочное СКО линий ролей (раньше — популяционное ÷n; приведено к
    // единому estimator'у со всеми остальными std-членами).
    let mut role_line_penalty = 0.0;
    let mut counted_roles = 0usize;
    for averages in role_line_avgs.iter() {
        if averages.len() < 2 {
            continue;
        }
        let sum: f64 = averages.iter().sum();
        let sum2: f64 = averages.iter().map(|v| v * v).sum();
        role_line_penalty += sample_stdev_from_sums(sum, sum2, averages.len());
        counted_roles += 1;
    }
    if counted_roles > 0 {
        role_line_penalty /= counted_roles as f64;
    }

    // Экстенсивные члены нормируются на команду — иначе веса, настроенные на
    // 4 командах, на 40 командах получают неявный множитель ×10 и подавляют
    // std/max-члены. Дефолтные веса компенсированы ×4 (intra 0.7→2.8,
    // role_spread 0.3→1.2, collisions 1.5→6.0) — на 4 командах поведение прежнее.
    let intra_team_std_avg = sum_intra_std / team_count as f64;
    let internal_role_spread_avg = sum_internal_role_spread / team_count as f64;
    let intra_team_penalty = intra_team_std_avg * ctx.config.intra_team_std_weight;
    let role_spread_penalty = internal_role_spread_avg * ctx.config.internal_role_spread_weight;

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

    // Sorted-adjacent gap вместо max−min: max−min по танк-линии структурно
    // ограничен снизу разбросом ПУЛА танков (при capacity 1 кто-то обязан
    // играть слабейшего танка) и на больших турнирах съедал весь бюджет
    // balance-объектива (66k из 153k на реальном прогоне), ничего не давая
    // поиску. Наибольшая «дыра» между соседними по силе танками — это то, что
    // реально чувствуется в сетке (играешь с соседями по силе) и что поиск
    // действительно может уменьшать.
    let tank_adjacent_gap = if team_count >= 2 {
        tank_ratings.sort_by(|a, b| a.partial_cmp(b).unwrap_or(Ordering::Equal));
        tank_ratings
            .windows(2)
            .map(|w| w[1] - w[0])
            .fold(0.0f64, f64::max)
    } else {
        0.0
    };

    let tank_adjacent_gap_penalty = tank_gap_penalty(tank_adjacent_gap);
    let ow2_tank_penalty = tank_adjacent_gap_penalty * ctx.config.tank_gap_weight
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
    // Хвостовой член: средний по командам максимум боли. Глобальный max видит
    // только одного худшего игрока турнира; средний per-team max различает
    // «одна команда с болью» и «боль в каждой команде».
    let avg_team_max_pain = sum_team_max_pain as f64 / team_count as f64;
    let avg_subrole_collisions = sum_subrole_collisions as f64 / team_count as f64;
    let objective_comfort = avg_discomfort * ctx.config.role_discomfort_weight
        + global_max_pain as f64 * ctx.config.max_role_discomfort_weight
        + avg_team_max_pain * ctx.config.team_max_pain_weight
        + avg_subrole_collisions * ctx.config.sub_role_collision_weight;

    ObjectiveBreakdown {
        total_rating_std,
        gap_penalty,
        mmr_std: inter_team_std,
        role_line_std: role_line_penalty,
        intra_team_std_avg,
        internal_role_spread_avg,
        tank_adjacent_gap_penalty,
        tank_std,
        effective_total_std: eff_total_std,
        avg_discomfort,
        global_max_pain: global_max_pain as f64,
        avg_team_max_pain,
        avg_subrole_collisions,
        balance: objective_balance,
        comfort: objective_comfort,
    }
}

pub(crate) fn calculate_objectives(solution: &Solution, context: &Context) -> Objectives {
    let stats: Vec<TeamStats> = solution
        .iter()
        .map(|t| calculate_team_stats(context, t))
        .collect();
    calculate_objectives_from_stats(&stats, context)
}

pub(crate) fn dominates(left: &Objectives, right: &Objectives) -> bool {
    let better_or_equal = left.balance <= right.balance && left.comfort <= right.comfort;
    let strictly_better = left.balance < right.balance || left.comfort < right.comfort;
    better_or_equal && strictly_better
}

pub(crate) fn fast_non_dominated_sort(objectives: &[Objectives]) -> Vec<Vec<usize>> {
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
pub(crate) fn crowding_distance(front: &[usize], objectives: &[Objectives]) -> Vec<f64> {
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

pub(crate) fn normalize_objectives(objectives: &[Objectives]) -> Vec<Objectives> {
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
