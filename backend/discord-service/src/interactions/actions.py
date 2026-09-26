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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES
from shared.services.notifications import NOTIFICATION_GROUPS

__all__ = ("ACTIONS", "Action", "custom_id", "is_ours", "parse_custom_id")

_PREFIX = "owt"
_CUSTOM_ID = re.compile(rf"^{_PREFIX}:(?P<action>[a-z_.]+):(?P<target>[A-Za-z0-9_-]{{1,40}})$")


def _invite(target: str, values: Sequence[str]) -> dict[str, Any]:
    # A body field, not a path parameter: the site sends it the same way
    # (``POST /registration-teams/invites/accept``), so the handler cannot tell.
    return {"payload": {"invite_id": int(target)}}


def _tournament(target: str, values: Sequence[str]) -> dict[str, Any]:
    # ``{tournament_id}`` is a path parameter, which the gateway copies to the body by name.
    return {"tournament_id": int(target)}


def _nothing(target: str, values: Sequence[str]) -> dict[str, Any]:
    return {}


def _everything(target: str) -> bool:
    return target == "all"


def _parse_roles(values: Sequence[str]) -> list[str] | None:
    """The role order a select carried; ``None`` for "every role I have a rank in".

    Discord does not keep the order the options were clicked in, so the order
    rides the value itself (``tank,support``). A value naming something that is
    not one of the three roles, or naming one twice, is not one the bot minted:
    it is refused here rather than sent on to be answered with a 422.
    """
    value = (values[0] if values else "").strip()
    if value == "all":
        return None
    roles = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not roles or len(set(roles)) != len(roles) or any(role not in REGISTRATION_ROLE_CODES for role in roles):
        raise ValueError(f"not a role order this bot minted: {value!r}")
    return roles


def _mix(target: str, values: Sequence[str]) -> dict[str, Any]:
    # ``{game_id}`` is a path parameter, which the gateway copies to the body
    # by name; the bot knows no workspace, so the mix row supplies it.
    return {"custom_game_id": int(target)}


def _mix_roles(target: str, values: Sequence[str]) -> dict[str, Any]:
    return {"custom_game_id": int(target), "payload": {"roles": _parse_roles(values)}}


def _mix_flex(target: str, values: Sequence[str]) -> dict[str, Any]:
    # A button carries no values, so the wanted state rides the target: ``42-on``.
    game_id, _, wanted = target.rpartition("-")
    return {"custom_game_id": int(game_id), "payload": {"is_flex": wanted == "on"}}


def _flex_target(target: str) -> bool:
    game_id, _, wanted = target.rpartition("-")
    return wanted in ("on", "off") and game_id.isdigit()


@dataclass(frozen=True, slots=True)
class Action:
    """One button's platform call.

    ``subject`` is ``None`` for a button the bot answers alone (it only shows
    the next button, so it needs neither an account nor a call). ``request``
    turns the target -- and, for a select, the values Discord sent with the
    click -- into the RPC body next to ``identity``; ``accepts`` is checked
    before anything is called, so a malformed target is refused here rather
    than as a 422 from the service. A value the bot never minted is refused
    the same way: ``request`` raises ``ValueError`` and no RPC is made.
    ``settles`` names the card buttons that stop making sense once this
    succeeded -- they are taken off the DM it was clicked in (never off a
    channel post, which is everyone's).
    """

    subject: str | None
    request: Callable[[str, Sequence[str]], dict[str, Any]] = _nothing
    accepts: Callable[[str], bool] = str.isdigit
    settles: frozenset[str] = field(default_factory=frozenset)


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
        lambda _all, _values: {"payload": {"discord_dm": dict.fromkeys(NOTIFICATION_GROUPS, False)}},
        accepts=_everything,
    ),
    # Self-signup for a pickup mix. The gate is the mix's own policy, so a
    # stale card button answers "signup closed" rather than doing anything.
    "mix.join": Action("rpc.balancer.custom.self_join", _mix),
    "mix.leave": Action("rpc.balancer.custom.self_leave", _mix),
    "mix.roles": Action("rpc.balancer.custom.self_get", _mix),
    "mix.roles_set": Action("rpc.balancer.custom.self_update", _mix_roles),
    "mix.flex": Action("rpc.balancer.custom.self_update", _mix_flex, accepts=_flex_target),
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
