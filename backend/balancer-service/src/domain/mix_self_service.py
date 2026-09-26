"""Who may seat themselves in a mix, leave it, and re-order their own roles.

Pure and session-free by the same argument as the tournament's
``self_edit_policy``: the read path calls it while serializing one player's
panel and the write path calls it again to enforce, and both must get the same
answer from the same inputs.

The order of the checks IS the contract -- the first failure is the reason the
client renders, so a terminal mix reports ``mix_closed`` rather than sending an
unlinked player off to link an account for a cancelled session.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ("MAX_ROSTER", "MixSelfPolicy", "mix_self_policy")

#: Same ceiling the host's own roster write enforces
#: (``CustomGameRosterUpdate.member_ids``), so self-signup cannot grow a lineup
#: past a size the host could not have built by hand.
MAX_ROSTER = 100

#: A mix in one of these is history: nothing about its lineup is writable.
_TERMINAL = frozenset({"completed", "cancelled"})


@dataclass(frozen=True, slots=True)
class MixSelfPolicy:
    can_join: bool
    can_leave: bool
    can_edit_roles: bool
    #: Machine code for the client to translate; ``None`` while joining is open.
    join_blocker: str | None
    #: Same, for editing one's own roles.
    edit_blocker: str | None


def mix_self_policy(
    *,
    status: str,
    self_signup: str,
    self_role_edit: bool,
    on_roster: bool,
    missing_links: frozenset[str],
    has_player: bool,
    self_join_denied: bool,
    roster_size: int,
) -> MixSelfPolicy:
    """The caller's own rights over one mix.

    ``missing_links`` is a subset of ``{"discord", "battlenet"}``;
    ``has_player`` says whether the account resolves to a ``players.user`` row;
    ``self_join_denied`` is the negative-RBAC overlay on ``custom_game.self_join``.
    """
    if status in _TERMINAL:
        return MixSelfPolicy(False, False, False, "mix_closed", "mix_closed")

    # Leaving is deliberately unconditional past the terminal check: somebody
    # who unlinked Battle.net after joining must not be stuck in the lineup.
    can_leave = on_roster

    identity_blocker: str | None = None
    if "discord" in missing_links:
        identity_blocker = "discord_not_linked"
    elif "battlenet" in missing_links:
        identity_blocker = "battlenet_not_linked"
    elif not has_player:
        identity_blocker = "player_not_linked"
    elif self_join_denied:
        identity_blocker = "self_join_denied"
    if identity_blocker is not None:
        return MixSelfPolicy(False, can_leave, False, identity_blocker, identity_blocker)

    if on_roster:
        join_blocker: str | None = "already_joined"
    elif self_signup == "closed":
        join_blocker = "signup_closed"
    elif roster_size >= MAX_ROSTER:
        join_blocker = "roster_full"
    else:
        join_blocker = None

    if not on_roster:
        edit_blocker: str | None = "not_on_roster"
    elif not self_role_edit:
        edit_blocker = "role_edit_off"
    else:
        edit_blocker = None

    return MixSelfPolicy(join_blocker is None, can_leave, edit_blocker is None, join_blocker, edit_blocker)
