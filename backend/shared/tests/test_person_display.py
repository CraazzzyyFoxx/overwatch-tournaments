"""The name a game surface shows for a person: precedence, tag split, Steam persona, visibility."""

from types import SimpleNamespace

from shared.schemas.identity import PersonDisplayRead
from shared.services.person_display import pick_game_handle


def _display(**kwargs) -> tuple[str, str | None, str | None]:
    shown = PersonDisplayRead.build(**kwargs)
    return shown.name, shown.tag, shown.snapshot


def test_workspace_name_beats_handle_snapshot_and_canonical():
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


def _account(id, provider, username, *, primary=False, scopes=(), persona=None):
    return SimpleNamespace(
        id=id,
        provider=provider,
        username=username,
        display_name=persona,
        is_primary=primary,
        visibilities=[SimpleNamespace(workspace_id=scope) for scope in scopes],
    )


def test_pick_skips_hidden_accounts_and_prefers_primary():
    accounts = [
        _account(1, "battlenet", "Hidden#1", primary=True),
        _account(2, "battlenet", "Second#2", scopes=[None]),
        _account(3, "battlenet", "Third#3", scopes=[None]),
        _account(4, "riot", "Other#EUW", primary=True, scopes=[None]),
    ]
    assert pick_game_handle(accounts, "battlenet", 5) == "Second#2"


def test_pick_honours_workspace_scope():
    accounts = [_account(1, "riot", "Local#EUW", scopes=[7])]
    assert pick_game_handle(accounts, "riot", 7) == "Local#EUW"
    assert pick_game_handle(accounts, "riot", 8) is None
    assert pick_game_handle(accounts, "riot", None) is None


def test_pick_shows_the_steam_persona_not_the_account_id():
    accounts = [_account(1, "steam", "123456", primary=True, scopes=[None], persona="Persona")]
    assert pick_game_handle(accounts, "steam", None) == "Persona"
