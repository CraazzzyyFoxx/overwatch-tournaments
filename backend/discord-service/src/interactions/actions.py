"""The fixed list of platform calls a card button may make, and how a button names one.

A button's ``custom_id`` is ``owt:<action>:<target>`` -- what to do and on which
object, never on whose behalf. The clicker is ``interaction.user``, which
Discord signs; the bot acts only for the account that linked that Discord user
(``rpc.identity.discord_identity``), and the target RPC then authorizes exactly
as it does for the site. So a button can do no more than its clicker could by
opening the page, and a forged ``custom_id`` can at most ask for something the
clicker was already allowed to do.

A list rather than a generic "call this RPC" bridge on purpose: every entry is
a user-facing RPC with a known request shape, and adding one is a reviewed line
here plus a button in the card renderer (``app-service`` ``notification_render``).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES
from shared.services.notifications import NOTIFICATION_GROUPS

__all__ = (
    "ACTIONS",
    "ALL_ROLES",
    "VOICE_TIMEOUT",
    "Action",
    "NO_ROLE",
    "custom_id",
    "is_ours",
    "parse_custom_id",
    "parse_setup_target",
    "setup_target",
    "voice_target",
)

_PREFIX = "owt"
_CUSTOM_ID = re.compile(rf"^{_PREFIX}:(?P<action>[a-z_.]+):(?P<target>[A-Za-z0-9_-]{{1,40}})$")


def _invite(target: str, fields: Mapping[str, str]) -> dict[str, Any]:
    # A body field, not a path parameter: the site sends it the same way
    # (``POST /registration-teams/invites/accept``), so the handler cannot tell.
    return {"payload": {"invite_id": int(target)}}


def _tournament(target: str, fields: Mapping[str, str]) -> dict[str, Any]:
    # ``{tournament_id}`` is a path parameter, which the gateway copies to the body by name.
    return {"tournament_id": int(target)}


def _nothing(target: str, fields: Mapping[str, str]) -> dict[str, Any]:
    return {}


def _everything(target: str) -> bool:
    return target == "all"


#: The seat modal's own vocabulary, shared with the panel that opens it
#: (``cards.seat_modal``): "every role I have a rank in" and "this slot is empty".
ALL_ROLES = "all"
NO_ROLE = "none"

#: ``tank`` -> ``t``: the three codes start with three different letters, so the
#: role order fits a ``mix.setup`` target as plain letters (``42-ts-1``).
_ROLE_LETTER: dict[str, str] = {role: role[0] for role in REGISTRATION_ROLE_CODES}
_LETTER_ROLE: dict[str, str] = {letter: role for role, letter in _ROLE_LETTER.items()}
_SETUP_TARGET = re.compile(r"^(?P<game>\d+)-(?P<order>[a-z]{1,3})-(?P<flex>[01])$")


def setup_target(game_id: Any, roles: Sequence[str] | None, is_flex: bool) -> str:
    """``<game id>-<order>-<flex>``: what the seat modal must open pre-filled with.

    ``mix.setup`` is answered by the bot alone, so the target is the whole
    state the modal needs -- no lookup between the click and the form, which
    matters because a modal must be the *first* answer to a click.
    ``a`` is "every role I have a rank in" (``roles`` is ``None``) and ``x`` is
    "none picked yet"; neither is a letter any role owns.
    """
    if roles is None:
        order = "a"
    else:
        order = "".join(_ROLE_LETTER[role] for role in roles if role in _ROLE_LETTER) or "x"
    return f"{game_id}-{order}-{'1' if is_flex else '0'}"


def parse_setup_target(target: str) -> tuple[int, list[str] | None, bool]:
    """``(game id, roles, is_flex)`` from a ``mix.setup`` target; raises on anything else."""
    match = _SETUP_TARGET.match(target)
    if match is None or not _setup_order(match["order"]):
        raise ValueError(f"not a seat setup target: {target!r}")
    order = match["order"]
    roles = None if order == "a" else [] if order == "x" else [_LETTER_ROLE[letter] for letter in order]
    return int(match["game"]), roles, match["flex"] == "1"


def _setup_order(order: str) -> bool:
    if order in ("a", "x"):
        return True
    return len(set(order)) == len(order) and all(letter in _LETTER_ROLE for letter in order)


def _setup(target: str) -> bool:
    match = _SETUP_TARGET.match(target)
    return match is not None and _setup_order(match["order"])


def _mix(target: str, fields: Mapping[str, str]) -> dict[str, Any]:
    # ``{game_id}`` is a path parameter, which the gateway copies to the body
    # by name; the bot knows no workspace, so the mix row supplies it.
    return {"custom_game_id": int(target)}


def _mix_seat_set(target: str, fields: Mapping[str, str]) -> dict[str, Any]:
    """The seat modal's answer as a ``self_update`` body.

    The three role slots are an ordered pick, so the order *is* the priority;
    a role named twice (two slots, same radio) is kept once, at its first
    place. ``all`` in the first slot means "every role I have a rank in" and
    the rest of the form stops mattering. Anything else in a slot is a value
    this bot never minted: refused here, before any platform call.
    """
    picks = [fields.get(f"role{slot}", "").strip() for slot in (1, 2, 3)]
    if picks[0] == ALL_ROLES:
        roles: list[str] | None = None
    else:
        roles = []
        for pick in picks:
            if pick in ("", NO_ROLE):
                continue
            if pick not in REGISTRATION_ROLE_CODES:
                raise ValueError(f"not a role this bot minted: {pick!r}")
            if pick not in roles:
                roles.append(pick)
    return {"custom_game_id": int(target), "payload": {"roles": roles, "is_flex": fields.get("flex") == "1"}}


#: The voice buttons and ``/mix move|return``: ``<game>-<lobby index>`` or ``<game>-all``.
_VOICE_TARGET = re.compile(r"^(?P<game>\d+)-(?P<lobby>[0-5]|all)$")
#: Moving people waits on Discord's per-member rate limit (balancer allows itself 30 s).
VOICE_TIMEOUT = 40.0


def voice_target(game_id: Any, lobby_index: int | None) -> str:
    return f"{game_id}-{'all' if lobby_index is None else lobby_index}"


def _voice_accepts(target: str) -> bool:
    return _VOICE_TARGET.match(target) is not None


def _voice(target: str, fields: Mapping[str, str]) -> dict[str, Any]:
    match = _VOICE_TARGET.match(target)
    if match is None:
        raise ValueError(f"not a voice target: {target!r}")
    lobby = match["lobby"]
    return {"custom_game_id": int(match["game"]), "payload": {"lobby_index": None if lobby == "all" else int(lobby)}}


@dataclass(frozen=True, slots=True)
class Action:
    """One button's platform call.

    ``subject`` is ``None`` for a button the bot answers alone (it only shows
    the next form or button, so it needs neither an account nor a call).
    ``request`` turns the target -- and, for a modal, the fields Discord sent
    with the submit, keyed by their component ``custom_id`` -- into the RPC
    body next to ``identity``; ``accepts`` is checked before anything is
    called, so a malformed target is refused here rather than as a 422 from
    the service. A field value the bot never minted is refused the same way:
    ``request`` raises ``ValueError`` and no RPC is made.
    ``settles`` names the card buttons that stop making sense once this
    succeeded -- they are taken off the DM it was clicked in (never off a
    channel post, which is everyone's). ``timeout`` overrides the dispatcher's
    for a call that legitimately takes seconds.
    """

    subject: str | None
    request: Callable[[str, Mapping[str, str]], dict[str, Any]] = _nothing
    accepts: Callable[[str], bool] = str.isdigit
    settles: frozenset[str] = field(default_factory=frozenset)
    timeout: float | None = None


_INVITE_BUTTONS = frozenset({"invite.accept", "invite.decline"})

# The card contract (``shared.schemas.events.DiscordAction``) and this table are
# one list written twice; ``tests/test_interactions.py`` keeps them equal,
# because a button the renderer may emit must never be one the bot cannot answer.
ACTIONS: dict[str, Action] = {
    "invite.accept": Action("rpc.tournament.regteam_accept", _invite, settles=_INVITE_BUTTONS),
    "invite.decline": Action("rpc.tournament.regteam_decline", _invite, settles=_INVITE_BUTTONS),
    "check_in": Action("rpc.tournament.reg_pub_check_in", _tournament, settles=frozenset({"check_in"})),
    "registration.view": Action("rpc.tournament.reg_pub_get_me", _tournament),
    # The DM card's small button: opens, for the reader alone, the one that
    # switches every Discord DM off, so the card itself carries no such switch.
    "notifications.menu": Action(None, accepts=_everything),
    "notifications.mute": Action(
        "rpc.app.notification_preferences_update",
        # Every group, not the card's: the reader asked for Discord to go quiet.
        # In-app notifications are not affected, and settings turn DMs back on.
        lambda _all, _fields: {"payload": {"discord_dm": dict.fromkeys(NOTIFICATION_GROUPS, False)}},
        accepts=_everything,
    ),
    # Self-signup for a pickup mix. The gate is the mix's own policy, so a
    # stale card button answers "signup closed" rather than doing anything.
    "mix.join": Action("rpc.balancer.custom.self_join", _mix),
    "mix.leave": Action("rpc.balancer.custom.self_leave", _mix),
    "mix.roles": Action("rpc.balancer.custom.self_get", _mix),
    # Answered by the bot alone: the click opens the seat modal, and the modal
    # it opens is spelled out by the target (``cards.seat_modal``).
    "mix.setup": Action(None, accepts=_setup),
    "mix.seat_set": Action("rpc.balancer.custom.self_update", _mix_seat_set),
    # The host's voice controls: the lineup card's buttons and ``/mix move|return``.
    # The RPC re-checks host-or-co-host, so a player clicking gets a refusal.
    "voice.move": Action("rpc.balancer.custom.voice_move", _voice, accepts=_voice_accepts, timeout=VOICE_TIMEOUT),
    "voice.return": Action("rpc.balancer.custom.voice_return", _voice, accepts=_voice_accepts, timeout=VOICE_TIMEOUT),
}


def custom_id(action: str, target: str) -> str:
    return f"{_PREFIX}:{action}:{target}"


def is_ours(value: str | None) -> bool:
    """A button this bot minted, whether or not it still means anything."""
    return isinstance(value, str) and value.startswith(f"{_PREFIX}:")


def parse_custom_id(value: str | None) -> tuple[str, str] | None:
    """``(action, target)`` for a button the bot can answer, else ``None``."""
    match = _CUSTOM_ID.match(value) if isinstance(value, str) else None
    if match is None:
        return None
    action = ACTIONS.get(match["action"])
    if action is None or not action.accepts(match["target"]):
        return None
    return match["action"], match["target"]
