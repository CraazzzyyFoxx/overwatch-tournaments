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

from shared.disciplines import DISCIPLINES
from shared.services.notifications import NOTIFICATION_GROUPS

__all__ = (
    "ACTIONS",
    "ALL_ROLES",
    "SEAT_SLOTS",
    "VOICE_TIMEOUT",
    "Action",
    "NO_ROLE",
    "custom_id",
    "is_ours",
    "parse_custom_id",
    "parse_seat_set_target",
    "parse_setup_target",
    "parse_voice_target",
    "registration_target",
    "role_letters",
    "seat_set_target",
    "seat_slots",
    "setup_target",
    "voice_target",
)

_PREFIX = "owt"
_CUSTOM_ID = re.compile(rf"^{_PREFIX}:(?P<action>[a-z_.]+):(?P<target>[A-Za-z0-9_-]{{1,40}})$")


def _invite(target: str, fields: Mapping[str, str]) -> dict[str, Any]:
    # A body field, not a path parameter: the site sends it the same way
    # (``POST /registration-teams/invites/accept``), so the handler cannot tell.
    return {"payload": {"invite_id": int(target)}}


_REGISTRATION_TARGET = re.compile(r"^(?P<tournament>\d+)-(?P<node>\d+)$")


def registration_target(tournament_id: Any, registration_node_id: Any) -> str:
    """``<tournament id>-<registration node id>``: the entry routes need both (``?registration_node_id=``)."""
    return f"{tournament_id}-{registration_node_id}"


def _registration_accepts(target: str) -> bool:
    return _REGISTRATION_TARGET.match(target) is not None


def _registration(target: str, fields: Mapping[str, str]) -> dict[str, Any]:
    # ``{tournament_id}`` is a path parameter, which the gateway copies to the body by name; the node is a
    # query parameter, which the RPC reads from ``query`` as a list of strings.
    match = _REGISTRATION_TARGET.match(target)
    if match is None:
        raise ValueError(target)
    return {"tournament_id": int(match["tournament"]), "query": {"registration_node_id": [match["node"]]}}


def _nothing(target: str, fields: Mapping[str, str]) -> dict[str, Any]:
    return {}


def _everything(target: str) -> bool:
    return target == "all"


#: The seat modal's own vocabulary, shared with the panel that opens it
#: (``cards.seat_modal``): "every role I have a rank in" and "this slot is empty".
ALL_ROLES = "all"
NO_ROLE = "none"
#: The seat form asks for at most this many roles, in order (spec §12.1 R3-1); a longer order is set on the site.
SEAT_SLOTS = 3

_SETUP_TARGET = re.compile(r"^(?P<game>\d+)-(?P<discipline>[a-z0-9_]+)-(?P<order>[a-z]{1,3})-(?P<flex>[01])$")
_SEAT_SET_TARGET = re.compile(r"^(?P<game>\d+)-(?P<discipline>[a-z0-9_]+)$")


def role_letters(discipline: str) -> dict[str, str] | None:
    """``{role code: its first letter}`` for a game the seat form serves, else ``None``.

    The form serves a game with more than one rated role whose codes start with different letters, none of them
    the ``a`` ("every ranked role") or ``x`` ("none yet") a target already spends (spec §12.1 R3-1): ``tank`` ->
    ``t``, ``mid`` -> ``m``. A one-role game (Deadlock) has no form at all.
    """
    spec = DISCIPLINES.get(discipline)
    if spec is None:
        return None
    letters = {role.code: role.code[0] for role in spec.rated_dimension.roles}
    used = set(letters.values())
    return letters if len(letters) > 1 and len(used) == len(letters) and not used & {"a", "x"} else None


def seat_slots(discipline: str) -> int:
    """How many ordered role slots ``discipline``'s seat form has: its role count, at most :data:`SEAT_SLOTS`."""
    return min(SEAT_SLOTS, len(DISCIPLINES[discipline].rated_dimension.roles))


def setup_target(game_id: Any, discipline: str, roles: Sequence[str] | None, is_flex: bool) -> str:
    """``<game id>-<discipline>-<order>-<flex>``: what the seat modal must open pre-filled with.

    ``mix.setup`` is answered by the bot alone, so the target is the whole
    state the modal needs -- no lookup between the click and the form, which
    matters because a modal must be the *first* answer to a click. ``a`` is
    "every role I have a rank in" (``roles`` is ``None``) and ``x`` is "none
    picked yet"; only the first :func:`seat_slots` roles travel, the form has
    no more slots. Raises for a game the form does not serve.
    """
    letters = role_letters(discipline)
    if letters is None:
        raise ValueError(f"no seat form for {discipline!r}")
    if roles is None:
        order = "a"
    else:
        order = "".join(letters[role] for role in roles if role in letters)[: seat_slots(discipline)] or "x"
    return f"{game_id}-{discipline}-{order}-{'1' if is_flex else '0'}"


def parse_setup_target(target: str) -> tuple[int, str, list[str] | None, bool]:
    """``(game id, discipline, roles, is_flex)`` from a ``mix.setup`` target; raises on anything else."""
    match = _SETUP_TARGET.match(target)
    letters = role_letters(match["discipline"]) if match is not None else None
    if match is None or letters is None or not _setup_order(match["order"], letters):
        raise ValueError(f"not a seat setup target: {target!r}")
    order = match["order"]
    by_letter = {letter: role for role, letter in letters.items()}
    roles = None if order == "a" else [] if order == "x" else [by_letter[letter] for letter in order]
    return int(match["game"]), match["discipline"], roles, match["flex"] == "1"


def _setup_order(order: str, letters: Mapping[str, str]) -> bool:
    if order in ("a", "x"):
        return True
    return len(set(order)) == len(order) and set(order) <= set(letters.values())


def _setup(target: str) -> bool:
    try:
        parse_setup_target(target)
    except ValueError:
        return False
    return True


def seat_set_target(game_id: Any, discipline: str) -> str:
    """``<game id>-<discipline>``: the seat form's own id, so its submit knows the game's roles without a lookup."""
    return f"{game_id}-{discipline}"


def parse_seat_set_target(target: str) -> tuple[int, str]:
    """``(game id, discipline)`` from a seat form's id; raises for a game the form does not serve."""
    match = _SEAT_SET_TARGET.match(target)
    if match is None or role_letters(match["discipline"]) is None:
        raise ValueError(f"not a seat form target: {target!r}")
    return int(match["game"]), match["discipline"]


def _seat_set(target: str) -> bool:
    try:
        parse_seat_set_target(target)
    except ValueError:
        return False
    return True


def _mix(target: str, fields: Mapping[str, str]) -> dict[str, Any]:
    # ``{game_id}`` is a path parameter, which the gateway copies to the body
    # by name; the bot knows no workspace, so the mix row supplies it.
    return {"custom_game_id": int(target)}


def _mix_seat_set(target: str, fields: Mapping[str, str]) -> dict[str, Any]:
    """The seat modal's answer as a ``self_update`` body.

    The role slots are an ordered pick, so the order *is* the priority; a
    role named twice (two slots, same radio) is kept once, at its first
    place. ``all`` in the first slot means "every role I have a rank in" and
    the rest of the form stops mattering. Anything else in a slot is a value
    this bot never minted for this game: refused here, before any platform
    call. ``is_flex`` is sent only for a game that has Full flex.
    """
    game_id, discipline = parse_seat_set_target(target)
    spec = DISCIPLINES[discipline]
    codes = [role.code for role in spec.rated_dimension.roles]
    picks = [fields.get(f"role{slot}", "").strip() for slot in range(1, seat_slots(discipline) + 1)]
    if picks[0] == ALL_ROLES:
        roles: list[str] | None = None
    else:
        roles = []
        for pick in picks:
            if pick in ("", NO_ROLE):
                continue
            if pick not in codes:
                raise ValueError(f"not a role this bot minted: {pick!r}")
            if pick not in roles:
                roles.append(pick)
    payload: dict[str, Any] = {
        "roles": [{"dimension": spec.rated_dimension.code, "role": code} for code in roles]
        if roles is not None
        else None
    }
    if spec.flex:
        payload["is_flex"] = fields.get("flex") == "1"
    return {"custom_game_id": game_id, "payload": payload}


#: The voice buttons and ``/mix move|return``: ``<game>-<lobby index>`` or ``<game>-all``.
_VOICE_TARGET = re.compile(r"^(?P<game>\d+)-(?P<lobby>[0-5]|all)$")
#: Moving people waits on Discord's per-member rate limit (balancer allows itself 30 s).
VOICE_TIMEOUT = 40.0


def voice_target(game_id: Any, lobby_index: int | None) -> str:
    return f"{game_id}-{'all' if lobby_index is None else lobby_index}"


def _voice_accepts(target: str) -> bool:
    return _VOICE_TARGET.match(target) is not None


def parse_voice_target(target: str) -> tuple[int, int | None]:
    """``(game id, lobby index or None for every lobby)``; raises on anything else."""
    match = _VOICE_TARGET.match(target)
    if match is None:
        raise ValueError(f"not a voice target: {target!r}")
    lobby = match["lobby"]
    return int(match["game"]), None if lobby == "all" else int(lobby)


def _voice(target: str, fields: Mapping[str, str]) -> dict[str, Any]:
    game_id, lobby_index = parse_voice_target(target)
    return {"custom_game_id": game_id, "payload": {"lobby_index": lobby_index}}


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

# The card contract (``src.render.card.DiscordAction``) and this table are
# one list written twice; ``tests/test_interactions.py`` keeps them equal,
# because a button the renderer may emit must never be one the bot cannot answer.
ACTIONS: dict[str, Action] = {
    "invite.accept": Action("rpc.tournament.regteam_accept", _invite, settles=_INVITE_BUTTONS),
    "invite.decline": Action("rpc.tournament.regteam_decline", _invite, settles=_INVITE_BUTTONS),
    "check_in": Action(
        "rpc.tournament.reg_pub_check_in",
        _registration,
        accepts=_registration_accepts,
        settles=frozenset({"check_in"}),
    ),
    "registration.view": Action("rpc.tournament.reg_pub_get_me", _registration, accepts=_registration_accepts),
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
    "mix.seat_set": Action("rpc.balancer.custom.self_update", _mix_seat_set, accepts=_seat_set),
    # The signup card's break switch (spec §7.4): two buttons because one shared
    # card cannot know whether its reader is away.
    "mix.away": Action(
        "rpc.balancer.custom.self_away",
        lambda target, _fields: {"custom_game_id": int(target), "payload": {"away": True}},
    ),
    "mix.back": Action(
        "rpc.balancer.custom.self_away",
        lambda target, _fields: {"custom_game_id": int(target), "payload": {"away": False}},
    ),
    # The host's voice controls: the lineup card's buttons and ``/mix move|return``.
    # The first click only asks (answered by the bot alone); the ``*_confirm``
    # button on that private prompt is what moves people. The RPC re-checks
    # host-or-co-host, so a player confirming gets a refusal.
    "voice.move": Action(None, accepts=_voice_accepts),
    "voice.return": Action(None, accepts=_voice_accepts),
    "voice.move_confirm": Action(
        "rpc.balancer.custom.voice_move", _voice, accepts=_voice_accepts, timeout=VOICE_TIMEOUT
    ),
    "voice.return_confirm": Action(
        "rpc.balancer.custom.voice_return", _voice, accepts=_voice_accepts, timeout=VOICE_TIMEOUT
    ),
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
