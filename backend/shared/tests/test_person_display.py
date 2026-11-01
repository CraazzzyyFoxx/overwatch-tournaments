"""The name a game surface shows for a person: precedence, tag split, Steam persona, visibility."""

from types import SimpleNamespace

from shared.schemas.identity import PersonDisplayRead
from shared.services.person_display import pick_game_handle


def _display(**kwargs) -> tuple[str, str | None, str | None]:
    shown = PersonDisplayRead.build(**kwargs)
    return shown.name, shown.tag, shown.snapshot


def test_a_verified_handle_beats_the_workspace_name():
    assert _display(
        canonical="Canon#1", provider="riot", handle="Riot#EUW", handle_verified=True, workspace_name="Org Pick"
    ) == ("Riot", "#EUW", None)


def test_workspace_name_beats_an_unverified_handle_snapshot_and_canonical():
    assert _display(
        canonical="Canon#1", provider="riot", handle="Riot#EUW", workspace_name="Org Pick", snapshot="Old#1"
    ) == ("Org Pick", None, "Old#1")


def test_handle_beats_snapshot_and_splits_its_tag():
    assert _display(
        canonical="Canon#1", provider="riot", handle="Name With Space#EUW", snapshot="Name With Space#EUW"
    ) == (
        "Name With Space",
        "#EUW",
        None,
    )


def test_snapshot_then_canonical_fill_in_for_a_missing_handle():
    assert _display(canonical="Canon#1", provider="battlenet", snapshot="Then#2") == ("Then", "#2", None)
    assert _display(canonical="Canon#1", provider="battlenet") == ("Canon", "#1", None)


def test_steam_persona_keeps_its_hash():
    assert _display(canonical="Canon#1", provider="steam", handle="xX#1Xx") == ("xX#1Xx", None, None)


def test_snapshot_is_reported_only_when_it_differs():
    assert _display(canonical="C", provider="battlenet", handle="New#1", snapshot="new#1")[2] is None
    assert _display(canonical="C", provider="battlenet", handle="New#1", snapshot="Old#9")[2] == "Old#9"


def test_steam_persona_keeps_its_hash_only_when_shown():
    assert _display(canonical="C", provider="steam", handle="xX#1Xx", handle_verified=True, workspace_name="A#B") == (
        "xX#1Xx",
        None,
        None,
    )
    assert _display(canonical="C", provider="steam", handle="xX#1Xx", workspace_name="A#B") == ("A", "#B", None)


def _account(id, provider, username, *, primary=False, verified=False, scopes=(), persona=None):
    return SimpleNamespace(
        id=id,
        provider=provider,
        username=username,
        display_name=persona,
        is_primary=primary,
        is_verified=verified,
        visibilities=[SimpleNamespace(workspace_id=scope) for scope in scopes],
    )


def test_pick_skips_hidden_accounts_and_prefers_primary():
    accounts = [
        _account(1, "battlenet", "Hidden#1", primary=True, verified=True),
        _account(2, "battlenet", "Second#2", scopes=[None]),
        _account(3, "battlenet", "Third#3", scopes=[None]),
        _account(4, "riot", "Other#EUW", primary=True, verified=True, scopes=[None]),
    ]
    assert pick_game_handle(accounts, "battlenet", 5) == ("Second#2", False)


def test_pick_prefers_a_verified_account_over_the_primary():
    accounts = [
        _account(1, "riot", "Primary#EUW", primary=True, scopes=[None]),
        _account(2, "riot", "Proven#EUW", verified=True, scopes=[None]),
    ]
    assert pick_game_handle(accounts, "riot", None) == ("Proven#EUW", True)


def test_pick_honours_workspace_scope():
    accounts = [_account(1, "riot", "Local#EUW", scopes=[7])]
    assert pick_game_handle(accounts, "riot", 7) == ("Local#EUW", False)
    assert pick_game_handle(accounts, "riot", 8) == (None, False)
    assert pick_game_handle(accounts, "riot", None) == (None, False)


def test_pick_shows_the_steam_persona_and_skips_an_account_without_one():
    accounts = [
        _account(1, "steam", "111", primary=True, verified=True, scopes=[None]),
        _account(2, "steam", "123456", scopes=[None], persona="Persona"),
    ]
    assert pick_game_handle(accounts, "steam", None) == ("Persona", False)
