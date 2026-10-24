"""The Workshop CSV decoder: grammar, boundaries, resolution and placements. Pure: no database, no service.

Numeric parity with the P4 parser is pinned against the frozen capture in ``stats-service/tests/test_ow_decoder_parity.py``.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from loguru import logger

from shared.core.enums import LogStatsName
from shared.disciplines import DISCIPLINES, INGESTORS
from shared.disciplines.ingest import DecodeContext, DecodeError, assemble_ingestors
from shared.disciplines.overwatch import ingest
from shared.disciplines.overwatch import settings as ow_settings
from shared.disciplines.overwatch.enums import log_stats_index_map
from shared.disciplines.spec import DisciplineSpec
from shared.schemas.match_doc import MatchDocError, MatchSource

STAMP = "2026-10-18T12:00:00Z"
RECEIVED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
CTX = DecodeContext(
    discipline="overwatch",
    source=MatchSource(kind="upload", external_id="log-1"),
    hint=None,
    received_at=RECEIVED,
    characters={"Ana": "ana", "Ана": "ana", "Reaper": "reaper"},
    maps={("Control", "Ilios"): "ilios", ("Control", "Илиос"): "ilios", ("Escort", "Ilios"): "ilios-escort"},
    attrs={"ana": {"class": "support"}, "reaper": {"class": "damage"}},
)


def row(kind: str, t: float, *data: object, stamp: str = STAMP) -> str:
    return ",".join([stamp, kind, str(t), *(str(item) for item in data)])


def stat(t: float, round_: int, team: str, player: str, hero: str, **values: float) -> str:
    cells = ["0"] * 33
    for name, value in values.items():
        cells[log_stats_index_map[LogStatsName[name]] - 4] = str(value)
    return row("player_stat", t, round_, team, player, hero, *cells)


def log(*extra: str, start: tuple = ("Ilios", "Control", "Home", "Away"), end: tuple = ("Home", 3, 2)) -> bytes:
    rows = [
        row("match_start", 0, *start),
        row("player_joined", 0, "A", "Home"),
        row("player_joined", 0, "B", "Away"),
        row("round_start", 1, 1),
        *extra,
        row("match_end", 100, *end),
    ]
    return ("\n".join(rows) + "\n").encode()


def facts(doc, *, stat_code: str, segment: int = 0, participant: str | None = None):
    return {
        (f.participant or f.team, f.entity): f.value
        for f in doc.facts
        if f.stat == stat_code and f.segment == segment and (participant is None or f.participant == participant)
    }


def test_wide_player_stat_row_is_not_truncated_or_shifted():
    payload = {name.name: float(index) for index, name in enumerate(log_stats_index_map)}
    doc = ingest.decode(log(stat(60, 1, "Home", "A", "Ana", **payload)), CTX)

    for name, index in log_stats_index_map.items():
        assert facts(doc, stat_code=name.value, participant="A")[("A", "ana")] == float(index - 4), name
    assert max(log_stats_index_map.values()) - 4 == 32


def test_quoted_commas_survive_and_teams_are_home_then_away():
    lines = [
        row("meta", 0, "ignored"),
        row("match_start", 0, "Ilios", "Control", '"Team, A"', '"Team, B"'),
        row("not_a_real_event", 1, "x"),
        row("kill", 12.5, '"Team, A"', "A", "Ana", '"Team, B"', "B", "Reaper", 0, 100, "False", "False"),
        row("match_end", 20, "Team", 1, 0),
    ]
    doc = ingest.decode(("\n".join(lines) + "\n").encode(), CTX)

    assert [team.key for team in doc.teams] == ["home", "away"]
    assert {p.key: p.team for p in doc.participants} == {"A": "home", "B": "away"}
    (kill,) = doc.events
    assert (kill.type, kill.actor, kill.target, kill.entity, kill.related_entity) == ("kill", "A", "B", "ana", "reaper")
    assert kill.data == {
        "fight": 1,
        "ability": None,
        "damage": 100.0,
        "is_critical_hit": False,
        "is_environmental": False,
    }


def test_unknown_rows_are_skipped_loudly_never_silently():
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        text = log(row("not_a_real_event", 1, "x"), row("kill", "soon", "x"), "just,two").decode()
        ingest.decode(text.encode(), CTX)
    finally:
        logger.remove(sink)
    joined = "\n".join(messages)
    assert "unknown event type 'not_a_real_event'" in joined
    assert "invalid time 'soon'" in joined
    assert "malformed row" in joined


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"", "match_log_empty"),
        (b"\n  \n", "match_log_empty"),
        (row("meta", 0, "x").encode(), "match_log_empty"),
        (
            "\n".join([row("match_start", 0, "Ilios", "Control", "Home", "Away"), row("round_start", 1, 1)]).encode(),
            "match_not_finished",
        ),
        (
            "\n".join(
                [row("match_start", 0, "Ilios", "Control", "Same", "Same"), row("match_end", 9, "x", 1, 1)]
            ).encode(),
            "match_log_corrupt",
        ),
        (row("match_end", 9, "Home", 1, 1).encode(), "match_log_corrupt"),
    ],
)
def test_unfinishable_logs_are_refused_with_a_stable_code(raw, code):
    with pytest.raises(DecodeError) as caught:
        ingest.decode(raw, CTX)
    assert caught.value.code == code


@pytest.fixture
def fresh_settings():
    ow_settings.settings.cache_clear()
    yield
    ow_settings.settings.cache_clear()


def test_line_cap_refuses_before_a_dataframe_is_built(monkeypatch, fresh_settings):
    monkeypatch.setenv("MAX_MATCH_LOG_LINES", "3")
    with pytest.raises(DecodeError) as caught:
        ingest.decode(log(), CTX)
    assert caught.value.code == "match_log_too_large"


def test_line_cap_honours_a_dotenv_file_like_every_service_setting(monkeypatch, tmp_path, fresh_settings):
    monkeypatch.delenv("MAX_MATCH_LOG_LINES", raising=False)
    monkeypatch.chdir(tmp_path)
    assert ingest.decode(log(), CTX).map == "ilios"  # default cap: accepted
    ow_settings.settings.cache_clear()
    (tmp_path / ".env").write_text("MAX_MATCH_LOG_LINES=3\n", encoding="utf-8")
    with pytest.raises(DecodeError) as caught:
        ingest.decode(log(), CTX)
    assert caught.value.code == "match_log_too_large"
    assert ow_settings.settings().max_match_log_lines == 3


def test_a_pair_naming_several_maps_is_refused_not_resolved_to_the_first():
    ambiguous = dataclasses.replace(CTX, ambiguous_maps=frozenset({("Control", "Ilios")}))
    with pytest.raises(DecodeError) as caught:
        ingest.decode(log(), ambiguous)
    assert caught.value.code == "ambiguous_map" and caught.value.misses() == {}


def test_a_participant_without_a_declared_team_or_on_both_teams_is_a_hard_error():
    with pytest.raises(DecodeError, match="Player 'C' is on team 'Nobody'") as caught:
        ingest.decode(log(row("player_joined", 1, "C", "Nobody")), CTX)
    assert caught.value.code == "match_log_corrupt"
    with pytest.raises(DecodeError, match="Player 'A' appears on both teams") as caught:
        ingest.decode(log(row("player_joined", 1, "A", "Away")), CTX)
    assert caught.value.code == "match_log_corrupt"


def test_a_map_is_only_that_map_inside_its_mode_and_a_miss_carries_both_names():
    assert ingest.decode(log(start=("Ilios", "Control", "Home", "Away")), CTX).map == "ilios"
    assert ingest.decode(log(start=("Илиос", "Control", "Home", "Away")), CTX).map == "ilios"
    assert ingest.decode(log(start=("Ilios", "Escort", "Home", "Away")), CTX).map == "ilios-escort"
    with pytest.raises(DecodeError) as caught:
        ingest.decode(log(start=("Ilios", "Hybrid", "Home", "Away")), CTX)
    assert caught.value.code == "not_found"
    assert caught.value.misses() == {"map": ("Ilios",), "mode": ("Hybrid",)}


def test_a_hero_resolves_by_alias_and_an_unknown_one_is_handed_on_verbatim():
    doc = ingest.decode(
        log(
            stat(60, 1, "Home", "A", "Ана", Eliminations=2, HeroTimePlayed=60),
            stat(60, 1, "Home", "A", "Brand New Hero", Eliminations=1, HeroTimePlayed=10),
        ),
        CTX,
    )
    entities = {f.entity for f in doc.facts if f.entity}
    assert entities == {"ana", "Brand New Hero"}


def test_an_event_only_participant_has_no_facts_and_no_role():
    doc = ingest.decode(
        log(
            row("offensive_assist", 5, "Home", "Ghost", "Ana"),
            stat(60, 1, "Home", "A", "Ana", Eliminations=1, HeroTimePlayed=60),
        ),
        CTX,
    )
    ghost = next(p for p in doc.participants if p.key == "Ghost")
    assert ghost.team == "home" and ghost.role is None
    assert not [f for f in doc.facts if f.participant == "Ghost"]
    assert [(e.type, e.actor) for e in doc.events] == [("offensive_assist", "Ghost")]
    observed = next(p for p in doc.participants if p.key == "A").role
    assert (observed.dimension, observed.role) == ("player_role", "support")


@pytest.mark.parametrize(
    ("home", "away", "placements"), [(3, 2, (1, 2)), (2, 3, (2, 1)), (2, 2, (1, 1)), (0, 0, (1, 1))]
)
def test_placements_follow_the_observed_scores(home, away, placements):
    doc = ingest.decode(log(end=("x", home, away)), CTX)
    assert tuple(team.placement for team in doc.teams) == placements
    assert facts(doc, stat_code="score") == {("home", None): float(home), ("away", None): float(away)}
    assert ingest.placements(home, away) == placements


def test_an_objectiveless_mode_claims_no_result_from_its_0_0_end():
    ctx = dataclasses.replace(
        CTX, maps={**CTX.maps, ("Push", "Colosseo"): "colosseo"}, objectiveless_modes=frozenset({"Push"})
    )
    doc = ingest.decode(log(start=("Colosseo", "Push", "Home", "Away"), end=("x", 0, 0)), ctx)
    assert [team.placement for team in doc.teams] == [None, None]
    assert facts(doc, stat_code="score") == {("home", None): 0.0, ("away", None): 0.0}
    # Equal scores in any other mode are still a shared first place.
    assert [t.placement for t in ingest.decode(log(end=("x", 0, 0)), CTX).teams] == [1, 1]


def test_played_at_is_the_first_timestamp_or_the_producers_receipt_time():
    assert ingest.decode(log(), CTX).played_at == datetime(2026, 10, 18, 12, tzinfo=UTC)
    naive = log().decode().replace(STAMP, "2026-10-18T12:00:00").encode()
    assert ingest.decode(naive, CTX).played_at == RECEIVED
    assert ingest.decode(log().decode().replace(STAMP, "0").encode(), CTX).played_at == RECEIVED


def test_events_after_the_match_end_are_kept_as_p4_kept_them():
    doc = ingest.decode(log(row("offensive_assist", 500, "Home", "A", "Ana")), CTX)
    assert doc.duration_s == 100.0
    assert [(e.type, e.t) for e in doc.events] == [("offensive_assist", 500.0)]


def test_a_structurally_invalid_result_is_reported_not_returned():
    with pytest.raises(MatchDocError):
        ingest._validated({"protocol": "wrong"})


def test_registry_declares_the_workshop_producers_and_never_a_catch_all():
    assert {key for key in INGESTORS if key[0] == "overwatch"} == {
        ("overwatch", "upload"),
        ("overwatch", "discord"),
        ("overwatch", "manual"),
    }
    # A public document's provenance label is not a decoder selector, and an unlisted pair is never routed anywhere.
    assert ("overwatch", "workshop_csv") not in INGESTORS
    assert ("lol", "upload") not in INGESTORS
    assert DISCIPLINES["overwatch"].derive_match is not None


def test_assembling_ingestors_rejects_a_duplicate_pair():
    one = DisciplineSpec("x", "X", ingestors={"raw": lambda raw, ctx: None})
    twin = DisciplineSpec("x", "X again", ingestors={"raw": lambda raw, ctx: None})
    assert set(assemble_ingestors([one])) == {("x", "raw")}
    with pytest.raises(ValueError, match="duplicate ingestor"):
        assemble_ingestors([one, twin])
