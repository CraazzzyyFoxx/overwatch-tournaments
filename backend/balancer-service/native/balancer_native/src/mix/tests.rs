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

/// Twelve one-role players rated 1000, 1100, ... 2100 (`p00`..`p11`), split
/// 6v6 into three duo lanes.
fn laned_lobby(rules: Value) -> Value {
    let players: Vec<Value> = (0..12)
        .map(|i| {
            json!({
                "uuid": format!("p{i:02}"),
                "name": format!("p{i:02}"),
                "ratings": {"agent": 1000 + i * 100},
                "preferences": ["agent"],
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
        "roles": [{"name": "agent", "slots": 6, "weight": 1.0}],
        "config": {"max_result_variants": 3, "mix_rules": rules},
    })
}

fn lane_rule() -> Value {
    json!([{"kind": "lane_matchup", "layout": [2, 2, 2], "weight": 1.0, "cohesion_weight": 0.5}])
}

fn rank(uuid: &str) -> usize {
    uuid[1..].parse().unwrap()
}

#[test]
fn lanes_face_opponents_of_the_same_tier() {
    let response = run(request(laned_lobby(lane_rule())), None).unwrap();
    let best = &response.variants[0];
    let lanes = &best.rules["lane_matchup"];
    assert_eq!(lanes.teams.len(), 2);
    let mut tiers: Vec<Vec<usize>> = (0..3)
        .map(|lane| {
            let mut tier: Vec<usize> = lanes.teams.iter().flat_map(|team| team[lane].iter().map(|u| rank(u))).collect();
            tier.sort_unstable();
            tier
        })
        .collect();
    tiers.sort();
    // Each lane and its opponents are four neighbours on the ladder: the
    // strongest four share a lane matchup, then the next four, then the rest.
    assert_eq!(tiers, vec![vec![0, 1, 2, 3], vec![4, 5, 6, 7], vec![8, 9, 10, 11]]);
    for team in &lanes.teams {
        for lane in team {
            assert!(rank(&lane[0]) > rank(&lane[1]), "a lane lists its stronger seat first: {lane:?}");
        }
    }
    let base = best.metrics.fairness + best.metrics.uniformity + best.metrics.role_fairness + best.metrics.role_points;
    assert!(close(best.metrics.total, (base + lanes.penalty) as f64), "total includes the lane penalty");
}

#[test]
fn no_rules_reports_no_rule_results() {
    let response = run(request(laned_lobby(json!([]))), None).unwrap();
    assert!(response.variants.iter().all(|v| v.rules.is_empty()));
    assert!(!serde_json::to_string(&response).unwrap().contains("\"rules\""));
}

#[test]
fn evaluate_scores_a_seating_like_the_search() {
    let response = run(request(laned_lobby(lane_rule())), None).unwrap();
    let best = &response.variants[0];
    let lobby = laned_lobby(lane_rule());
    let evaluated = evaluate(
        serde_json::from_value(json!({
            "request": lobby,
            "teams": best.teams.iter().map(|team| &team.roster).collect::<Vec<_>>(),
        }))
        .unwrap(),
    )
    .unwrap();
    let (searched, scored) = (&best.rules["lane_matchup"], &evaluated.rules["lane_matchup"]);
    assert_eq!(searched.penalty, scored.penalty);
    assert_eq!(searched.teams, scored.teams);
}

#[test]
fn evaluate_rejects_a_player_seated_twice() {
    let teams = json!([
        {"agent": ["p00", "p01", "p02", "p03", "p04", "p05"]},
        {"agent": ["p00", "p07", "p08", "p09", "p10", "p11"]},
    ]);
    let err = evaluate(serde_json::from_value(json!({"request": laned_lobby(lane_rule()), "teams": teams})).unwrap())
        .expect_err("p00 twice");
    assert!(err.contains("seated twice"), "{err}");
}

#[test]
fn rejects_a_layout_that_does_not_seat_the_team() {
    let rules = json!([{"kind": "lane_matchup", "layout": [2, 2], "weight": 1.0, "cohesion_weight": 0.0}]);
    let err = run(request(laned_lobby(rules)), None).expect_err("4 lane seats for 6 players");
    assert!(err.contains("does not seat a team of 6"), "{err}");
}

#[test]
fn refuses_a_layout_with_too_many_seatings_before_building_them() {
    let mut lobby = laned_lobby(json!([{
        "kind": "lane_matchup", "layout": vec![1; 12], "weight": 1.0, "cohesion_weight": 0.0,
    }]));
    let players: Vec<Value> = (0..24)
        .map(|i| {
            let mut player = lobby["players"][0].clone();
            player["uuid"] = json!(format!("q{i:02}"));
            player
        })
        .collect();
    lobby["players"] = json!(players);
    lobby["roles"] = json!([{"name": "agent", "slots": 12, "weight": 1.0}]);
    let err = run(request(lobby), None).expect_err("12! seatings per team");
    assert!(err.contains("too many seatings"), "{err}");
}

#[test]
fn rejects_unknown_rule_kinds_and_fields() {
    for rules in [
        json!([{"kind": "keep_together", "weight": 1.0}]),
        json!([{"kind": "lane_matchup", "layout": [2, 2, 2], "weight": 1.0, "cohesion_weight": 0.0, "typo": 1}]),
    ] {
        let parsed: Result<MixRequest, _> = serde_json::from_value(laned_lobby(rules.clone()));
        assert!(parsed.is_err(), "{rules} must not parse");
    }
}
