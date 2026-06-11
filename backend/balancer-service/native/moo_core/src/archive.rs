use std::cmp::Ordering;
use std::collections::hash_map::DefaultHasher;
use std::collections::HashSet;
use std::hash::{Hash, Hasher};

use crate::*;

pub(crate) fn archive_capacity_limit(ctx: &Context) -> usize {
    ctx.config
        .max_result_variants
        .max(DEFAULT_ARCHIVE_LIMIT)
        .min(MAX_ARCHIVE_LIMIT)
}

/// Скор "близость к идеальной точке" в нормированном пространстве (меньше —
/// лучше). В отличие от суммы norm_b + norm_c, расстояние различает точки и
/// на двухточечном фронте: сумма там тождественно равна 1.0 и порядок решали
/// тай-брейки (в продакшене это проявлялось как composite_score=1.0 у
/// показанного варианта).
pub(crate) fn knee_scores(objectives: &[Objectives]) -> Vec<f64> {
    let normed = normalize_objectives(objectives);
    normed
        .iter()
        .map(|o| (o.balance * o.balance + o.comfort * o.comfort).sqrt())
        .collect()
}

/// Вырожденный фронт: по одной из осей все точки практически совпадают —
/// нормированный скор превращается в шум тай-брейков.
pub(crate) fn objective_spans_degenerate(objectives: &[Objectives]) -> bool {
    let mut b_min = f64::INFINITY;
    let mut b_max = f64::NEG_INFINITY;
    let mut c_min = f64::INFINITY;
    let mut c_max = f64::NEG_INFINITY;
    for o in objectives {
        b_min = b_min.min(o.balance);
        b_max = b_max.max(o.balance);
        c_min = c_min.min(o.comfort);
        c_max = c_max.max(o.comfort);
    }
    let b_scale = b_max.abs().max(b_min.abs()).max(1.0);
    let c_scale = c_max.abs().max(c_min.abs()).max(1.0);
    (b_max - b_min) <= b_scale * 1e-9 || (c_max - c_min) <= c_scale * 1e-9
}

/// Полный порядок "лучшие первыми": по knee-скору, а на вырожденных фронтах
/// (< 4 точек или нулевой спан) — лексикографически по сырым (balance,
/// comfort), чтобы выбор primary-варианта не зависел от шума нормализации.
pub(crate) fn knee_order(
    objectives: &[Objectives],
    signatures: &[u64],
    scores: &[f64],
) -> Vec<usize> {
    let degenerate = objectives.len() < 4 || objective_spans_degenerate(objectives);
    let mut order: Vec<usize> = (0..objectives.len()).collect();
    order.sort_by(|&left, &right| {
        let primary = if degenerate {
            Ordering::Equal
        } else {
            scores[left]
                .partial_cmp(&scores[right])
                .unwrap_or(Ordering::Equal)
        };
        primary
            .then_with(|| {
                objectives[left]
                    .balance
                    .partial_cmp(&objectives[right].balance)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| {
                objectives[left]
                    .comfort
                    .partial_cmp(&objectives[right].comfort)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| signatures[left].cmp(&signatures[right]))
    });
    order
}

pub(crate) fn best_balance_index(objectives: &[Objectives], signatures: &[u64]) -> usize {
    (0..objectives.len())
        .min_by(|&left, &right| {
            objectives[left]
                .balance
                .partial_cmp(&objectives[right].balance)
                .unwrap_or(Ordering::Equal)
                .then_with(|| {
                    objectives[left]
                        .comfort
                        .partial_cmp(&objectives[right].comfort)
                        .unwrap_or(Ordering::Equal)
                })
                .then_with(|| signatures[left].cmp(&signatures[right]))
        })
        .unwrap_or(0)
}

pub(crate) fn best_comfort_index(objectives: &[Objectives], signatures: &[u64]) -> usize {
    (0..objectives.len())
        .min_by(|&left, &right| {
            objectives[left]
                .comfort
                .partial_cmp(&objectives[right].comfort)
                .unwrap_or(Ordering::Equal)
                .then_with(|| {
                    objectives[left]
                        .balance
                        .partial_cmp(&objectives[right].balance)
                        .unwrap_or(Ordering::Equal)
                })
                .then_with(|| signatures[left].cmp(&signatures[right]))
        })
        .unwrap_or(0)
}

pub(crate) fn archive_selection_order(archive: &[ArchiveEntry]) -> Vec<usize> {
    if archive.is_empty() {
        return Vec::new();
    }

    let objectives: Vec<Objectives> = archive.iter().map(|entry| entry.obj).collect();
    let front: Vec<usize> = (0..archive.len()).collect();
    let crowding = crowding_distance(&front, &objectives);
    let signatures: Vec<u64> = archive.iter().map(|entry| entry.sig).collect();
    let scores = knee_scores(&objectives);
    let score_ranked = knee_order(&objectives, &signatures, &scores);

    let best_balance_idx = best_balance_index(&objectives, &signatures);
    let best_comfort_idx = best_comfort_index(&objectives, &signatures);

    let mut anchor_seen = HashSet::new();
    let mut order = Vec::with_capacity(archive.len());
    for idx in score_ranked
        .iter()
        .copied()
        .take(ARCHIVE_SCORE_KEEP.min(score_ranked.len()))
        .chain([best_balance_idx, best_comfort_idx].into_iter())
    {
        if anchor_seen.insert(idx) {
            order.push(idx);
        }
    }

    let mut crowding_ranked: Vec<usize> = (0..archive.len()).collect();
    crowding_ranked.sort_by(|&left, &right| {
        crowding[right]
            .partial_cmp(&crowding[left])
            .unwrap_or(Ordering::Equal)
            .then_with(|| {
                scores[left]
                    .partial_cmp(&scores[right])
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| {
                objectives[left]
                    .balance
                    .partial_cmp(&objectives[right].balance)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| {
                objectives[left]
                    .comfort
                    .partial_cmp(&objectives[right].comfort)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| signatures[left].cmp(&signatures[right]))
    });

    for idx in crowding_ranked {
        if anchor_seen.insert(idx) {
            order.push(idx);
        }
    }
    order
}

pub(crate) fn archive_select_items(archive: &[ArchiveEntry], count: usize) -> Vec<ArchiveEntry> {
    archive_selection_order(archive)
        .into_iter()
        .take(count.min(archive.len()))
        .map(|idx| archive[idx].clone())
        .collect()
}

/// Элиты для инжекции в next-gen: колено + якоря best-balance и best-comfort.
/// Прежняя версия брала топ-K по скаляру — все элиты кучковались у колена и
/// не создавали давления к краям фронта внутри острова.
pub(crate) fn archive_select_elites(archive: &[ArchiveEntry], count: usize) -> Vec<ArchiveEntry> {
    if archive.is_empty() || count == 0 {
        return Vec::new();
    }

    let objectives: Vec<Objectives> = archive.iter().map(|entry| entry.obj).collect();
    let signatures: Vec<u64> = archive.iter().map(|entry| entry.sig).collect();
    let scores = knee_scores(&objectives);
    let ranked = knee_order(&objectives, &signatures, &scores);
    let anchors = [
        ranked[0],
        best_balance_index(&objectives, &signatures),
        best_comfort_index(&objectives, &signatures),
    ];

    let mut seen = HashSet::new();
    let mut picked = Vec::with_capacity(count.min(archive.len()));
    for idx in anchors.into_iter().chain(ranked.into_iter()) {
        if picked.len() >= count {
            break;
        }
        if seen.insert(idx) {
            picked.push(archive[idx].clone());
        }
    }
    picked
}

pub(crate) fn prune_archive(
    archive: &mut Vec<ArchiveEntry>,
    archive_sigs: &mut HashSet<u64>,
    ctx: &Context,
) {
    let limit = archive_capacity_limit(ctx);
    if archive.len() <= limit {
        return;
    }

    let retained = archive_select_items(archive, limit);
    let retained_sigs: HashSet<u64> = retained.iter().map(|entry| entry.sig).collect();
    *archive = retained;
    *archive_sigs = retained_sigs;
}

/// Обновить внешний Парето-архив кандидатом. Возвращает true если кандидат
/// попал в архив. Удаляет все доминируемые им элементы. Дедуп по сигнатуре.
pub(crate) fn archive_update(
    archive: &mut Vec<ArchiveEntry>,
    archive_sigs: &mut HashSet<u64>,
    candidate: ArchiveEntry,
    ctx: &Context,
) -> bool {
    debug_assert_eq!(candidate.sig, signature(&candidate.sol));
    if archive_sigs.contains(&candidate.sig) {
        return false;
    }
    for entry in archive.iter() {
        if dominates(&entry.obj, &candidate.obj) {
            return false;
        }
    }
    // Удаляем всех, кого кандидат доминирует
    let mut i = 0;
    while i < archive.len() {
        if dominates(&candidate.obj, &archive[i].obj) {
            archive_sigs.remove(&archive[i].sig);
            archive.swap_remove(i);
        } else {
            i += 1;
        }
    }
    archive_sigs.insert(candidate.sig);
    archive.push(candidate);
    prune_archive(archive, archive_sigs, ctx);
    true
}

/// Канонический хэш решения, инвариантный к перестановке команд.
/// Для каждой команды строится отсортированный набор (role_idx, player_idx),
/// хэш команды независим от её team.id; затем сортируются хэши команд.
pub(crate) fn signature(sol: &Solution) -> u64 {
    let mut team_hashes: Vec<u64> = Vec::with_capacity(sol.len());
    for t in sol {
        let mut entries: Vec<(usize, usize)> = Vec::new();
        for (r, rs) in t.roster.iter().enumerate() {
            for &p in rs {
                entries.push((r, p));
            }
        }
        entries.sort_unstable();
        let mut h = DefaultHasher::new();
        entries.hash(&mut h);
        team_hashes.push(h.finish());
    }
    team_hashes.sort_unstable();
    let mut h = DefaultHasher::new();
    team_hashes.hash(&mut h);
    h.finish()
}
