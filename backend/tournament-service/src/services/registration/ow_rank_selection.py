"""Select a registration's OW2 rank from its player's accounts.

A player can own several Battle.net accounts (a main plus declared smurfs), all attached to one
``players.user`` id and therefore to one set of rank snapshots. For the rank-delta highlight we want
the player's *true* rank: the maximum across their accounts, while preferring the main account(s) and
only falling back to smurfs when no main account has data for a role.

The smurf set comes from the registration form (``smurf_tags_json``); the DB has no per-account smurf
flag, so the form is the authoritative source. Functions here are pure (no DB) so they can be unit
tested in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable

from src.services.registration.utils import normalize_battle_tag_key


def select_main_account_ow_ranks(
    accounts_by_tag: dict[str, dict[str, int]],
    smurf_tags: Iterable[str] | None,
) -> dict[str, int]:
    """Per role, the maximum raw OW SR across a user's accounts, preferring non-smurf accounts.

    ``accounts_by_tag`` maps ``battle_tag -> {registration_role: raw_sr}`` for one user (as returned
    by ``fetch_latest_ow_ranks_by_account``). ``smurf_tags`` are the registration's declared smurf
    battle tags. For each role the result is the max raw SR among non-smurf accounts; roles with no
    non-smurf value fall back to the max among smurf accounts. Returns ``{registration_role: raw_sr}``.
    """
    smurf_keys = {
        key for tag in (smurf_tags or []) if (key := normalize_battle_tag_key(tag)) is not None
    }

    main_by_role: dict[str, int] = {}
    smurf_by_role: dict[str, int] = {}
    for battle_tag, ranks_by_role in accounts_by_tag.items():
        target = smurf_by_role if normalize_battle_tag_key(battle_tag) in smurf_keys else main_by_role
        for role, raw_sr in ranks_by_role.items():
            if raw_sr is None:
                continue
            if raw_sr > target.get(role, 0):
                target[role] = raw_sr

    # Prefer main accounts; fall back to smurfs only for roles with no main-account rank.
    selected = dict(main_by_role)
    for role, raw_sr in smurf_by_role.items():
        selected.setdefault(role, raw_sr)
    return selected
