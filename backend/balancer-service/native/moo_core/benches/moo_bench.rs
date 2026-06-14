use criterion::{black_box, criterion_group, criterion_main, Criterion};
use moo_core::bench_api as api;

/// Полный пересчёт objectives на 40 командах (горячий путь polish).
fn bench_objectives(c: &mut Criterion) {
    let ctx = api::synthetic_context(40, 7);
    let sol = api::snake_seed(&ctx);
    c.bench_function("objectives_200p_40t", |b| {
        b.iter(|| api::objectives(black_box(&ctx), black_box(&sol)))
    });
}

/// Локальный поиск на крупной фикстуре — доминирующая стадия прогона.
/// Snake-сид уже близок к локальному оптимуму, поэтому polish доходит до
/// фиксированной точки и платит за полные сканы с reject'ами — именно этот
/// путь доминирует в продакшене (polish_max_passes=50 на каждом решении архива).
fn bench_polish(c: &mut Criterion) {
    let ctx = api::synthetic_context(40, 7);
    let sol = api::snake_seed(&ctx);
    let mut group = c.benchmark_group("polish");
    group.sample_size(10);
    group.bench_function("polish_200p_40t_50pass", |b| {
        b.iter(|| api::polish(black_box(&ctx), black_box(&sol), 50))
    });
    group.finish();
}

/// Шторм вставок в архив: измеряет путь archive_update → prune.
fn bench_archive(c: &mut Criterion) {
    let ctx = api::synthetic_context(8, 7);
    let candidates = api::make_candidates(&ctx, 500, 5);
    c.bench_function("archive_storm_500", |b| {
        b.iter(|| api::archive_storm(black_box(&ctx), black_box(&candidates)))
    });
}

/// Полный прогон оптимизатора на малой фикстуре (как regression-тест).
fn bench_full_run(c: &mut Criterion) {
    let ctx = api::synthetic_context(4, 7);
    let mut group = c.benchmark_group("full");
    group.sample_size(10);
    group.bench_function("run_optimizer_20p_4t", |b| {
        b.iter(|| api::run_full(black_box(&ctx)))
    });
    group.finish();
}

criterion_group!(
    benches,
    bench_objectives,
    bench_polish,
    bench_archive,
    bench_full_run
);
criterion_main!(benches);
