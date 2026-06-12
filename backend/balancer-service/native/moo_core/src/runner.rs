use pyo3::prelude::*;
use pyo3::types::PyDict;
use rand::prelude::*;
use rayon::prelude::*;
use std::cmp::Ordering;
use std::collections::HashSet;

use crate::*;

#[derive(Debug, Clone, Copy, Default)]
pub(crate) struct ProgressSnapshot {
    current: Option<usize>,
    total: Option<usize>,
    percent: Option<f64>,
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

    Python::with_gil(|py| -> PyResult<()> {
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

pub(crate) fn generation_progress_snapshot(current: usize, total: usize) -> ProgressSnapshot {
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

pub(crate) fn run_optimizer(
    ctx: &Context,
    progress_callback: Option<&Py<PyAny>>,
) -> Result<NativeResponse, String> {
    let islands = ctx.config.island_count.max(1);

    // Генерируем независимые под-сиды из основного сида детерминированно
    let mut seed_rng = MooRng::seed_from_u64(ctx.seed);
    let island_seeds: Vec<u64> = (0..islands).map(|_| seed_rng.random::<u64>()).collect();
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
        .enumerate()
        .map(|(island_index, (local_ctx, seed))| init_island_state(local_ctx, seed, island_index))
        .collect::<Result<Vec<_>, _>>()?;

    // Дедлайн по wall-clock: при истечении прекращаем эволюцию и polish,
    // возвращая лучшее из уже накопленного архива (валидный, но менее
    // отполированный результат). По умолчанию лимита нет.
    let deadline = ctx
        .config
        .time_limit_ms
        .map(|ms| std::time::Instant::now() + std::time::Duration::from_millis(ms));
    let deadline_passed = || deadline.is_some_and(|d| std::time::Instant::now() >= d);

    while island_states.iter().any(|state| !state.stopped) {
        if deadline_passed() {
            emit_progress_event(
                progress_callback,
                "optimizing",
                "Rust MOO time limit reached; finalizing current archive".to_string(),
                None,
            )?;
            break;
        }
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
            let migrants_by_island: Vec<Vec<ArchiveEntry>> = island_states
                .iter()
                .map(|state| {
                    archive_select_items(&state.archive, MIGRATION_TOP_K.min(state.archive.len()))
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
                        if seen.insert(item.sig) {
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

    let island_results: Vec<Vec<ArchiveEntry>> = island_states
        .iter_mut()
        .map(|state| {
            finalize_island_state(state);
            state
                .archive
                .iter()
                .map(|entry| {
                    // Переоценка каноническими весами; сигнатура из кэша.
                    let obj = calculate_objectives(&entry.sol, ctx);
                    entry.rescored(obj)
                })
                .collect()
        })
        .collect();
    let mut repair_diagnostics = RepairDiagnostics::default();
    for state in &island_states {
        repair_diagnostics.merge(&state.repair_diagnostics);
    }

    // Сливаем архивы в один глобальный
    let mut global_archive: Vec<ArchiveEntry> = Vec::new();
    let mut global_sigs: HashSet<u64> = HashSet::new();
    for arch in island_results {
        for item in arch {
            archive_update(&mut global_archive, &mut global_sigs, item, ctx);
        }
    }
    if global_archive.is_empty() {
        return Err("empty global archive".into());
    }

    // Полируем глобальный архив чанками: между чанками — progress-событие
    // (это окно отмены: ошибка callback прерывает прогон, раньше во время
    // polish отмена была невозможна) и проверка дедлайна. Недополированный
    // хвост остаётся в финальном архиве как есть — результат валиден.
    const POLISH_CHUNK: usize = 16;
    let total_to_polish = global_archive.len();
    let mut polished: Vec<ArchiveEntry> = Vec::with_capacity(total_to_polish);
    for (chunk_index, chunk) in global_archive.chunks(POLISH_CHUNK).enumerate() {
        if deadline_passed() {
            break;
        }
        emit_progress_event(
            progress_callback,
            "polishing",
            format!(
                "Rust MOO polishing archive solutions {}/{total_to_polish}",
                (chunk_index * POLISH_CHUNK).min(total_to_polish)
            ),
            Some(ProgressSnapshot {
                percent: Some(99.0),
                ..ProgressSnapshot::default()
            }),
        )?;
        let chunk_polished: Vec<ArchiveEntry> = chunk
            .par_iter()
            .map(|entry| {
                let pol = polish_pareto(&entry.sol, ctx, ctx.config.polish_max_passes);
                let pol_obj = calculate_objectives(&pol, ctx);
                ArchiveEntry::new(pol_obj, pol)
            })
            .collect();
        polished.extend(chunk_polished);
    }

    let mut final_archive: Vec<ArchiveEntry> = Vec::new();
    let mut final_sigs: HashSet<u64> = HashSet::new();
    for item in global_archive.drain(..) {
        archive_update(&mut final_archive, &mut final_sigs, item, ctx);
    }
    for item in polished {
        archive_update(&mut final_archive, &mut final_sigs, item, ctx);
    }

    // Ранжирование по близости к идеальной точке (knee_scores) с
    // лексикографическим фолбэком на вырожденных фронтах — даёт полный
    // устойчивый порядок: лучшие решения в начале, primary не определяется
    // шумом тай-брейков на двухточечных архивах.
    let variant_limit = ctx
        .config
        .max_result_variants
        .max(1)
        .min(final_archive.len());
    let objs: Vec<Objectives> = final_archive.iter().map(|entry| entry.obj).collect();
    let normed = normalize_objectives(&objs);
    let signatures: Vec<u64> = final_archive.iter().map(|entry| entry.sig).collect();
    let tilt = ctx.config.rank_comfort_tilt;
    let scores = knee_scores(&objs, 1.0 - tilt, tilt);
    let score_order = knee_order(&objs, &signatures, &scores);
    // rank_pos[i] = позиция i в knee-порядке; используется для сортировки хвоста
    let mut rank_pos = vec![0usize; score_order.len()];
    for (pos, &idx) in score_order.iter().enumerate() {
        rank_pos[idx] = pos;
    }
    let selected_indices: Vec<usize> = if final_archive.len() > variant_limit {
        let primary_idx = score_order[0];
        let mut selected = Vec::with_capacity(variant_limit);
        selected.push(primary_idx);
        for idx in archive_selection_order(&final_archive) {
            if idx != primary_idx {
                selected.push(idx);
                if selected.len() >= variant_limit {
                    break;
                }
            }
        }
        let mut tail = selected[1..].to_vec();
        tail.sort_by_key(|&idx| rank_pos[idx]);
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
    let mut taken: Vec<Option<ArchiveEntry>> = final_archive.into_iter().map(Some).collect();
    for idx in selected_indices {
        if let Some(item) = taken[idx].take() {
            selected.push((item.obj, item.sol, scores[idx], normed[idx]));
        }
    }
    let variants = selected
        .into_iter()
        .map(|(obj, sol, score, norm)| {
            let breakdown = calculate_objective_breakdown(&sol, ctx);
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
                breakdown,
            }
        })
        .collect();
    Ok(NativeResponse {
        variants,
        repair_diagnostics,
    })
}
