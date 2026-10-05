from shared.domain.objectiveless_maps import AcceptedGame, LoggedMap, Series, resolve_scores

HOME, AWAY = 10, 20
CONTROL, ESCORT, PUSH, CLASH = 1, 2, 3, 4
OBJECTIVELESS = {PUSH, CLASH}


def series(home: int, away: int, *, completed: bool = True) -> Series:
    return Series(home_team_id=HOME, away_team_id=AWAY, completed=completed, home_score=home, away_score=away)


def logged(match_id: int, map_id: int, score: tuple[int, int] = (0, 0), *, flipped: bool = False) -> LoggedMap:
    """``flipped``: the log lists the encounter's away team first."""
    return LoggedMap(
        match_id=match_id,
        map_id=map_id,
        home_team_id=AWAY if flipped else HOME,
        home_score=score[0],
        away_score=score[1],
        objectiveless=map_id in OBJECTIVELESS,
    )


def test_accepted_game_decides_the_map_in_the_logs_orientation() -> None:
    scores = resolve_scores(
        series(0, 0, completed=False),
        [logged(1, PUSH, flipped=True)],
        [AcceptedGame(map_id=PUSH, home_score=1, away_score=0)],
    )
    assert scores == {1: (0, 1)}


def test_last_unknown_map_goes_to_the_side_still_owed_a_win() -> None:
    # Control: home wins. Escort, logged away-first as 3:1: away wins. 1:2 -> Push is away's.
    maps = [logged(1, CONTROL, (2, 0)), logged(2, ESCORT, (3, 1), flipped=True), logged(3, PUSH, flipped=True)]
    assert resolve_scores(series(1, 2), maps, []) == {3: (1, 0)}


def test_wins_that_do_not_add_up_decide_nothing() -> None:
    maps = [logged(1, CONTROL, (2, 0)), logged(2, PUSH)]
    # 2:1 needs three decisive maps; one decisive log is missing.
    assert resolve_scores(series(2, 1), maps, []) == {2: (0, 0)}
    # Away is owed nothing and home already has its one win: Push was a draw or a log is wrong.
    assert resolve_scores(series(1, 0), maps, []) == {2: (0, 0)}


def test_several_unknown_maps_are_decided_only_when_one_side_takes_them_all() -> None:
    maps = [logged(1, CONTROL, (2, 0)), logged(2, PUSH), logged(3, CLASH)]
    assert resolve_scores(series(3, 0), maps, []) == {2: (1, 0), 3: (1, 0)}
    assert resolve_scores(series(2, 1), maps, []) == {2: (0, 0), 3: (0, 0)}


def test_accepted_game_count_must_match_the_logs() -> None:
    # Wins add up (2:0), but three games were played: a drawn map has no log.
    maps = [logged(1, CONTROL, (2, 0)), logged(2, PUSH)]
    games = [AcceptedGame(map_id=None, home_score=1, away_score=0)] * 2 + [
        AcceptedGame(map_id=None, home_score=0, away_score=0)
    ]
    assert resolve_scores(series(2, 0), maps, games) == {2: (0, 0)}
    assert resolve_scores(series(2, 0), maps, games[:2]) == {2: (1, 0)}


def test_open_series_is_never_decided_by_exclusion() -> None:
    assert resolve_scores(series(2, 0, completed=False), [logged(1, CONTROL, (2, 0)), logged(2, PUSH)], []) == {
        2: (0, 0)
    }


def test_map_played_twice_is_decided_by_neither_game() -> None:
    games = [
        AcceptedGame(map_id=PUSH, home_score=1, away_score=0),
        AcceptedGame(map_id=PUSH, home_score=0, away_score=1),
    ]
    assert resolve_scores(series(1, 1, completed=False), [logged(1, PUSH)], games) == {1: (0, 0)}
