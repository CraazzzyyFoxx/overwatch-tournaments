"""The one shape of "what roles does a player have, and at what rank".

Every surface that used to derive this for itself -- the admin registration
list, the ``ready``/``incomplete`` verdict, the balancer algorithm's input, the
draft pool, the draft board, feasibility, autopick and the draft's team export
-- now reads these value objects, produced once by
:mod:`shared.services.roster`. Nothing recomputes them, and nothing stores a
second copy: the single exception is the frozen ``(role, rank)`` a completed
draft pick records, which is a historical fact rather than a derivation.

The invariant that replaces five near-identical predicates:

    a role is playable  <=>  the registration marks it active
                             AND the rank resolver found a number for it

``is_active`` alone was never enough (a sheet row whose rank did not parse is
active with no number) and a raw ``rank_value`` alone was never enough (an
empty one *inherits* from the workspace canon or the latest Overwatch
snapshot). Both halves live here, together, once.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from shared.core.enums import HeroClass
from shared.domain.member_rank import RankSource

__all__ = (
    "FLEX_ROLE_MODES",
    "FlexRoleMode",
    "HeroRef",
    "PlayerRoster",
    "RosterRole",
    "flex_role_mode",
)

#: ``registration_form.built_in_fields_json.flex_role.mode``.
#:
#: ``optional``   -- the registrant names the roles they play (default)
#: ``all_roles``  -- every role is playable; the registrant still names a priority
#: ``forced``     -- every role is playable AND primary, the choice is made for them
FlexRoleMode = str
FLEX_ROLE_MODES: tuple[str, ...] = ("optional", "all_roles", "forced")


def flex_role_mode(form: Any | None) -> str:
    """The tournament's flex mode, normalized. An unreadable form is ``optional``.

    THE reader of ``flex_role.mode``: tournament-service used to own one copy for
    the write path and balancer-service another for the draft, synchronized only
    by parity tests (see the deleted ``rules.all_roles_required``).

    ``enabled: false`` bans the flex field outright and therefore wins over any
    ``mode`` left behind in the JSON -- a form cannot force every role playable
    through a field it does not show.
    """
    if form is None:
        return "optional"
    config = (getattr(form, "built_in_fields_json", None) or {}).get("flex_role")
    if not isinstance(config, Mapping):
        return "optional"
    if str(config.get("enabled", True)).strip().lower() in ("false", "0"):
        return "optional"
    mode = config.get("mode")
    return mode if mode in ("all_roles", "forced") else "optional"


@dataclass(frozen=True, slots=True)
class HeroRef:
    """One of a role's "top heroes", ready for both the FK and the wire."""

    id: int | None
    slug: str
    image_path: str | None


@dataclass(frozen=True, slots=True)
class RosterRole:
    role: HeroClass
    #: Resolved rank: the registration's own number, else the workspace canon,
    #: else the latest Overwatch snapshot (``TOURNAMENT_ORDER``). ``None`` means
    #: no layer had one, which is exactly what makes the role unplayable.
    rank: int | None
    source: RankSource
    is_primary: bool
    priority: int
    subrole: str | None
    top_heroes: tuple[HeroRef, ...] = ()

    @property
    def is_playable(self) -> bool:
        # ``> 0``, not ``is not None``: the balancer loader drops ``rank <= 0``
        # (``player_loader.parse_player_node``), so a zero here would be a player
        # the draft can pick and the balance run silently loses.
        return self.rank is not None and self.rank > 0


@dataclass(frozen=True, slots=True)
class PlayerRoster:
    """One registration's identity plus its resolved roles, priority-ordered.

    ``roles`` holds every role the registration declares as active, playable or
    not, because the organizer's ``ready``/``incomplete`` verdict is precisely
    "are all of them ranked". Consumers that only care about what can be drafted
    or balanced go through :attr:`playable_roles` / :meth:`rank_on`.
    """

    registration_id: int
    battle_tag: str | None
    display_name: str | None
    #: ``players.user.id`` via ``workspace_member`` -- ``None`` for a registration
    #: with no member (an admin-created row, or a sheet row never provisioned).
    player_id: int | None
    auth_user_id: int | None
    workspace_member_id: int | None
    roles: tuple[RosterRole, ...]
    #: Full flex: more than one PLAYABLE declared role and every one of them
    #: primary; ``forced`` mode makes it true for anyone with more than one
    #: playable role. Computed by the engine from the same roles as ``roles`` --
    #: never from raw registration rows, which count inactive/unranked ones.
    is_full_flex: bool
    #: Registration answers the draft board and the admin table both read.
    notes: str | None = None
    admin_notes: str | None = None
    custom_fields: Mapping[str, Any] = field(default_factory=dict)
    # ── Registration workflow, carried so a pool export is a full snapshot ──
    # Read straight off the registration row the engine already holds; no
    # consumer of the roster projection is required to look at them, which is
    # why every one has a default.
    status: str | None = None
    balancer_status: str | None = None
    exclude_reason: str | None = None
    checked_in: bool = False
    registration_team_id: int | None = None
    #: Captain-assigned roster slot (``RosterSlotCode``) -- NOT derivable from
    #: ``roles``: ``flex`` is a slot, never a rated role.
    team_slot_code: str | None = None
    is_substitute: bool = False
    # ── Contact/private answers ─────────────────────────────────────────────
    discord_nick: str | None = None
    twitch_nick: str | None = None
    boosty_nick: str | None = None
    stream_pov: bool = False
    smurf_tags: tuple[str, ...] = ()

    # -- roles ---------------------------------------------------------------

    @property
    def playable(self) -> tuple[RosterRole, ...]:
        return tuple(entry for entry in self.roles if entry.is_playable)

    @property
    def playable_roles(self) -> frozenset[HeroClass]:
        return frozenset(entry.role for entry in self.roles if entry.is_playable)

    @property
    def primary(self) -> RosterRole | None:
        """The role this player leads with: their flagged primary, else the first.

        Resolved over playable roles only -- leading with a role nobody can draft
        them on is how a rankless player used to end up labelled ``damage``.
        """
        playable = self.playable
        return next((entry for entry in playable if entry.is_primary), playable[0] if playable else None)

    @property
    def secondary_roles(self) -> tuple[HeroClass, ...]:
        lead = self.primary
        return tuple(entry.role for entry in self.playable if lead is None or entry.role is not lead.role)

    @property
    def sub_role(self) -> str | None:
        lead = self.primary
        return lead.subrole if lead is not None else None

    # -- ranks ---------------------------------------------------------------

    def rank_on(self, role: HeroClass | str | None) -> int | None:
        """The rank this player carries on ``role``; ``None`` for no role at all.

        No fallback to another role's number: a role without a resolved rank is
        not playable, so answering with a neighbour's rank would invent a rating
        the captain then picks on. ``role=None`` is the honest input for a player
        holding no role -- a pool card, or a role-less roster slot -- and answers
        :attr:`best_rank`.
        """
        if role is None:
            return self.best_rank
        wanted = role if isinstance(role, HeroClass) else HeroClass.parse(role)
        return next((entry.rank for entry in self.roles if entry.role is wanted and entry.is_playable), None)

    def source_on(self, role: HeroClass | str | None) -> RankSource:
        if role is None:
            best = max(self.playable, key=lambda entry: entry.rank or 0, default=None)
            return best.source if best is not None else "none"
        wanted = role if isinstance(role, HeroClass) else HeroClass.parse(role)
        return next((entry.source for entry in self.roles if entry.role is wanted and entry.is_playable), "none")

    @property
    def best_rank(self) -> int | None:
        """The player's strongest playable role -- what a role-less roster is worth."""
        return max((entry.rank for entry in self.playable if entry.rank is not None), default=None)

    @property
    def role_ranks(self) -> dict[str, int]:
        """``{slot_code: rank}`` over playable roles. Absent key = not playable."""
        return {entry.role.slot_code: entry.rank for entry in self.playable if entry.rank is not None}

    @property
    def role_sources(self) -> dict[str, RankSource]:
        return {entry.role.slot_code: entry.source for entry in self.playable}

    @property
    def role_top_heroes(self) -> dict[str, list[dict[str, Any]]]:
        return {
            entry.role.slot_code: [
                {"hero_id": hero.id, "slug": hero.slug, "image_path": hero.image_path} for hero in entry.top_heroes
            ]
            for entry in self.playable
            if entry.top_heroes
        }

    # -- verdicts ------------------------------------------------------------

    @property
    def is_ranked_complete(self) -> bool:
        """Every declared role has a rank -- the ``ready`` half of the pool verdict."""
        return bool(self.roles) and all(entry.is_playable for entry in self.roles)

    @property
    def is_draftable(self) -> bool:
        """At least one playable role: below this a player cannot be picked at all."""
        return bool(self.playable)

    def covers(self, role: HeroClass | str | None) -> bool:
        """Whether this player can fill a slot of ``role``; a role-less slot fits anyone."""
        if role is None or role is HeroClass.flex or role == HeroClass.flex.slot_code:
            return self.is_draftable
        wanted = role if isinstance(role, HeroClass) else HeroClass.parse(role)
        return wanted in self.playable_roles
