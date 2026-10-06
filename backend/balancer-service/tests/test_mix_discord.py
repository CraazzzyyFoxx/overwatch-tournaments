from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from src.domain.mix_discord import SignupPlayer, lineup_card, signup_card  # noqa: E402

BOARD_URL = "https://owt.example/balancer/mix/42"
NOW = datetime(2026, 10, 6, 18, 0, tzinfo=UTC)


def _document(*rosters: dict[str, list[tuple[str, int]]]) -> dict:
    """A stored lobby document with one option: a team per roster of ``(name, rating)`` seats."""
    players: dict[str, dict] = {}
    teams = []
    for roster in rosters:
        for bucket, seats in roster.items():
            for name, rating in seats:
                players.setdefault(name, {"name": name, "ratings": {}})["ratings"][bucket] = rating
        teams.append({"roster": {bucket: [name for name, _ in seats] for bucket, seats in roster.items()}})
    return {"players": players, "variants": [{"teams": teams}]}


def _lineup(document: dict | None = None, **overrides):
    document = document if document is not None else _document()
    kwargs = {
        "mix_name": "Friday Scrim",
        "match_number": 1,
        "variant": document["variants"][0],
        "players": document["players"],
        "team_names": {},
        "next_map": None,
        "points_per_win": None,
        "board_url": BOARD_URL,
    }
    kwargs.update(overrides)
    return lineup_card(**kwargs)


def _signup(**overrides):
    kwargs = {
        "mix_name": "Friday Scrim",
        "host_name": "Foxx",
        "board_url": BOARD_URL,
        "custom_game_id": 42,
        "self_signup": "pool",
        "status": "draft",
        "lobby_count": 1,
        "players": [],
        "updated_at": NOW,
    }
    kwargs.update(overrides)
    return signup_card(**kwargs)


def _player(roles: list[str] | None = None, name: str = "P", *, benched: bool = False) -> SignupPlayer:
    return SignupPlayer(name=name, roles=roles, benched=benched)


# ── the signup card ────────────────────────────────────────────────────────


def test_an_open_signup_card_names_the_mix_its_host_and_where_a_joiner_lands() -> None:
    card = _signup()

    assert card.text.startswith("## :owt_live: Запись на микс «Friday Scrim»")
    assert ":owt_host: Foxx" in card.text
    assert ":owt_pool: сразу в пул" in card.text
    assert "2 лобби" not in card.text
    assert card.accent_color == 0x14B8A6


def test_a_benched_signup_says_the_bench_and_two_lobbies_say_so_too() -> None:
    card = _signup(self_signup="benched", lobby_count=2)

    assert ":owt_bench: сначала на скамейку" in card.text
    assert ":owt_lobby_a::owt_lobby_b: 2 лобби" in card.text


def test_the_card_counts_the_roster_by_first_role_and_calls_the_rest_any_role() -> None:
    """A row in all_ranked mode named no role: it is not a claim on tank."""
    card = _signup(
        players=[_player(roles) for roles in (["tank"], ["damage", "tank"], ["support"], ["damage"], None, None)]
    )

    assert ":owt_players: **6** записано" in (card.details or "")
    assert ":owt_tank: 1 · :owt_damage: 2 · :owt_support: 1 · любая роль 2" in (card.details or "")


def test_an_open_card_explains_the_two_clicks_and_stamps_when_it_was_rendered() -> None:
    details = _signup().details or ""

    assert "1. Нажмите «Записаться»" in details
    assert "Discord" in details and "Battle.net" in details
    assert f"<t:{int(NOW.timestamp())}:R>" in details


def test_an_open_card_carries_the_three_actions_with_their_emoji_and_the_board_link() -> None:
    card = _signup()

    assert [button.action for button in card.answers] == ["mix.join", "mix.roles", "mix.leave"]
    assert {button.target for button in card.answers} == {"42"}
    assert [button.style for button in card.answers] == ["success", "secondary", "danger"]
    assert [button.emoji for button in card.answers] == ["join", "edit", "leave"]
    assert all(button.disabled is False for button in card.answers)
    [[link]] = card.rows
    assert (link.url, link.emoji) == (BOARD_URL, "link")


def test_a_closed_card_greys_out_joining_but_still_lets_the_seated_leave() -> None:
    """The mix is still live, so whoever is in can check their seat or get out."""
    card = _signup(self_signup="closed", players=[_player(["tank"])])

    assert card.text.startswith("## :owt_lock: Запись на микс «Friday Scrim» закрыта")
    join, seat, leave = card.answers
    assert join.disabled is True
    assert (seat.disabled, leave.disabled) == (False, False)
    assert "Нажмите «Записаться»" not in (card.details or "")
    assert ":owt_players: **1** записано" in (card.details or "")


def test_a_finished_or_cancelled_mix_answers_nothing_at_all() -> None:
    done = _signup(status="completed")
    cancelled = _signup(status="cancelled", self_signup="pool")

    assert done.text.startswith("## :owt_lock: Микс «Friday Scrim» завершён")
    assert cancelled.text.startswith("## :owt_lock: Микс «Friday Scrim» отменён")
    assert done.answers == [] and cancelled.answers == []
    assert done.accent_color == 0x3B82F6
    # Nothing to sign up for, so the mode is not advertised any more.
    assert "сразу в пул" not in cancelled.text
    # The board link survives: the history is still worth reading.
    assert cancelled.rows[0][0].url == BOARD_URL


def test_the_card_escapes_a_mix_name_written_as_markdown() -> None:
    """Mix names are user input and the card is Discord markdown: an unescaped
    name reformats (or breaks) the whole post."""
    card = _signup(mix_name="**Friday** _mix_", host_name=None)

    assert "**Friday**" not in card.text
    assert r"\*\*Friday\*\*" in card.text
    assert ":owt_host: —" in card.text


def test_the_card_survives_a_mix_name_at_the_length_cap() -> None:
    """DiscordCard refuses past 4000 characters, and escaping can double a
    name's length -- a 255-character mix name must still produce a card."""
    assert len(_signup(mix_name="*" * 255).text) < 4000


def test_the_card_lists_the_roster_in_order_with_the_bench_apart() -> None:
    """Who is in, as the balancer has them: pool and must-play together, the
    bench on its own line -- and names are user input, so escaped."""
    card = _signup(
        players=[
            _player(name="Ana"),
            _player(name="Bob", benched=True),
            _player(name="_Cid_"),
        ]
    )

    details = card.details or ""
    assert r"**Игроки**: Ana, \_Cid\_" in details
    assert ":owt_bench: **Скамейка**: Bob" in details


def test_an_empty_roster_lists_nobody() -> None:
    details = _signup().details or ""

    assert "Игроки" not in details and "Скамейка" not in details


def test_a_full_roster_of_long_names_is_cut_and_counted_not_refused() -> None:
    """100 seats of escape-doubled names would blow Discord's 4000: the list
    stops at its budget and says how many it left out, leaving room for the
    emoji the bot expands after the card's own length check."""
    card = _signup(players=[_player(name="*" * 32) for _ in range(90)] + [_player(name="x", benched=True)] * 10)

    details = card.details or ""
    assert len(card.text) + len(details) < 3000
    pool_line = next(line for line in details.splitlines() if line.startswith("**Игроки**"))
    shown = pool_line.split(": ", 1)[1].split(" и ещё ")[0].count(", ") + 1
    assert pool_line.endswith(f" и ещё {90 - shown}")
    assert ":owt_bench: **Скамейка**: " + ", ".join(["x"] * 10) in details


# ── the lineup card ────────────────────────────────────────────────────────


def test_the_lineup_headline_names_the_mix_and_the_match_about_to_be_played() -> None:
    assert _lineup(match_number=4).text.startswith("## :owt_vs: Friday Scrim · Игра 4")


def test_a_two_lobby_mix_says_which_lobby_the_lineup_is_for() -> None:
    """Both lobbies post into the same channel, so the card has to say which
    one it describes -- and each counts its own games."""
    assert "Friday Scrim · Лобби B · Игра 3" in _lineup(match_number=3, lobby_label="B").text


def test_the_lineup_carries_the_map_its_gamemode_and_the_points_at_stake() -> None:
    card = _lineup(next_map=("Busan", "Контроль"), points_per_win=25)

    assert ":owt_map: Busan · Контроль" in card.text
    assert ":owt_points: +25 за победу" in card.text


def test_the_lineup_says_so_before_anyone_rolled_a_map() -> None:
    card = _lineup(next_map=("Busan", None), points_per_win=0)

    assert ":owt_map: Busan" in card.text
    assert "за победу" not in card.text
    assert ":owt_map: Карта ещё не выбрана" in _lineup().text


def test_without_an_image_the_card_lists_every_seat_under_its_team() -> None:
    document = _document(
        {"Tank": [("Ana", 3000)], "Damage": [("Bob", 2900), ("Cid", 2800)], "Support": [("Dee", 2700)]},
        {"Tank": [("Eve", 2600)]},
    )
    details = _lineup(document, team_names={1: "Синие"}).details or ""

    assert details.split("\n\n") == [
        "**Команда 1**\n:owt_tank: Ana · 3000\n:owt_damage: Bob · 2900\n:owt_damage: Cid · 2800\n:owt_support: Dee · 2700",
        "**Синие**\n:owt_tank: Eve · 2600",
    ]
    assert _lineup(document).image_url is None


def test_an_unrecognised_bucket_keeps_its_own_key_as_the_label() -> None:
    assert ":owt_" not in (_lineup(_document({"Goalie": [("Ana", 3000)]})).details or "")
    assert "Goalie Ana · 3000" in (_lineup(_document({"Goalie": [("Ana", 3000)]})).details or "")


def test_with_the_hosts_capture_the_picture_is_the_lineup() -> None:
    """The screenshot shows the matchup card itself; repeating it as text below
    would be the same information twice."""
    document = _document({"Tank": [("Ana", 3000)]}, {"Tank": [("Bob", 2900)]})
    card = _lineup(document, image_filename="lineup.png")

    assert card.image_url == "attachment://lineup.png"
    assert card.attachment_name == "lineup.png"
    assert card.details is None


def test_the_card_pings_the_seated_players_it_was_given_ids_for() -> None:
    document = _document({"Tank": [("Ana", 3000)]})

    assert (_lineup(document).details or "").count("<@") == 0
    assert "-# :owt_players: <@111> <@222>" in (_lineup(document, mentions=["111", "222"]).details or "")
    # With a picture the mentions are all the card says.
    assert _lineup(document, image_filename="lineup.png", mentions=["111"]).details == "-# :owt_players: <@111>"
