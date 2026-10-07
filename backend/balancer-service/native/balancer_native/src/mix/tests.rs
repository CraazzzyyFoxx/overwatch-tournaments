use std::collections::BTreeSet;
use std::path::Path;

use serde_json::{json, Value};

use super::*;

type Seating = BTreeSet<BTreeSet<(String, String)>>;

fn seating(teams: &[TeamResponse]) -> Seating {
    teams
        .iter()
        .map(|team| {
            team.roster
                .iter()
                .flat_map(|(role, uuids)| uuids.iter().map(move |uuid| (uuid.clone(), role.clone())))
                .collect()
        })
        .collect()
}

fn expected_seating(teams: &Value) -> Seating {
    teams
        .as_array()
        .unwrap()
        .iter()
        .map(|team| {
            team.as_array()
                .unwrap()
                .iter()
                .map(|seat| {
                    (
                        seat[0].as_str().unwrap().to_string(),
                        seat[1].as_str().unwrap().to_string(),
                    )
                })
                .collect()
        })
        .collect()
}

fn close(actual: f32, expected: f64) -> bool {
    (actual as f64 - expected).abs() <= 2e-3 + 1e-5 * expected.abs()
}

fn request(value: Value) -> MixRequest {
    serde_json::from_value(value).expect("fixture request must deserialize")
}

/// Parity with the C++ engine it replaces: the fixtures hold its output
/// (mirrors collapsed, whole tie groups kept) for the same requests, captured
/// before the C++ source was deleted.
#[test]
fn matches_cpp_reference_rankings() {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/mix");
    let mut checked = 0;
    for entry in std::fs::read_dir(&dir).expect("fixture dir") {
        let path = entry.unwrap().path();
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        let fixture: Value = serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
        let wanted = fixture["request"]["config"]["max_result_variants"].as_u64().unwrap() as usize;
        let expected = &fixture["expected"];
        let outcome = run(request(fixture["request"].clone()), None);

        if let Some(error) = expected["error"].as_str() {
            let err = outcome.expect_err(&format!("{name}: C++ failed, Rust must too"));
            assert!(err.contains(error), "{name}: {err:?} should contain {error:?}");
            checked += 1;
            continue;
        }

        let variants = outcome.unwrap_or_else(|e| panic!("{name}: {e}")).variants;
        let reference = expected["results"].as_array().unwrap();
        assert_eq!(variants.len(), wanted.min(reference.len()), "{name}: variant count");

        let mut seen = BTreeSet::new();
        for (rank, variant) in variants.iter().enumerate() {
            let m = variant.metrics;
            assert!(
                close(m.total, reference[rank]["total"].as_f64().unwrap()),
                "{name}: rank {rank} total {} != C++ {}",
                m.total,
                reference[rank]["total"]
            );
            let key = seating(&variant.teams);
            assert!(seen.insert(key.clone()), "{name}: seating returned twice (mirror)");
            let twin = reference
                .iter()
                .find(|r| expected_seating(&r["teams"]) == key)
                .unwrap_or_else(|| panic!("{name}: rank {rank} seating is not in the C++ top results"));
            for (field, actual) in [
                ("fairness", m.fairness),
                ("uniformity", m.uniformity),
                ("role_fairness", m.role_fairness),
                ("role_points", m.role_points),
            ] {
                assert!(
                    close(actual, twin[field].as_f64().unwrap()),
                    "{name}: rank {rank} {field} {actual} != C++ {}",
                    twin[field]
                );
            }
        }
        checked += 1;
    }
    assert!(checked >= 9, "expected the full fixture set, checked {checked}");
}

fn lobby(config: Value) -> Value {
    let players: Vec<Value> = (0..4)
        .map(|i| {
            json!({
                "uuid": format!("p{i}"),
                "name": format!("p{i}"),
                "ratings": {"Tank": 1000 + i * 300, "Damage": 1500},
                "preferences": ["Tank", "Damage"],
                "subclasses": {},
                "is_captain": false,
                "is_flex": false,
                "seed_role": null,
            })
        })
        .collect();
    json!({
        "players": players,
        "num_teams": 2,
        "seed": 0,
        "roles": [{"name": "Tank", "slots": 1, "weight": 1.0},
                  {"name": "Damage", "slots": 1, "weight": 1.0}],
        "config": config,
    })
}

#[test]
fn same_output_whatever_the_thread_count() {
    let run_with = |threads: usize| {
        let pool = rayon::ThreadPoolBuilder::new().num_threads(threads).build().unwrap();
        let fixture: Value = serde_json::from_str(
            &std::fs::read_to_string(
                Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/mix/4v4_equal_ratings_ties.json"),
            )
            .unwrap(),
        )
        .unwrap();
        let response = pool.install(|| run(request(fixture["request"].clone()), None)).unwrap();
        serde_json::to_string(&response).unwrap()
    };
    assert_eq!(run_with(1), run_with(8));
}

#[test]
fn balance_limit_is_optional_and_enforced_when_set() {
    let unbounded = run(request(lobby(json!({"max_result_variants": 3}))), None).unwrap();
    let best = unbounded.variants[0].metrics.total;
    assert!(best > 0.0);

    let err = run(
        request(lobby(json!({"max_result_variants": 3, "balance_limit": best / 2.0}))),
        None,
    )
    .expect_err("nothing scores under half the optimum");
    assert!(err.contains("balance limit"), "{err}");

    let limited = run(
        request(lobby(json!({"max_result_variants": 3, "balance_limit": best}))),
        None,
    )
    .unwrap();
    assert!(limited.variants.iter().all(|v| v.metrics.total <= best));
}

#[test]
fn rejects_anything_but_two_teams() {
    let mut value = lobby(json!({"max_result_variants": 3}));
    value["num_teams"] = json!(4);
    value["roles"] = json!([{"name": "Tank", "slots": 1, "weight": 1.0}]);
    let err = run(request(value), None).expect_err("4 teams");
    assert!(err.contains("exactly 2 teams"), "{err}");
}
