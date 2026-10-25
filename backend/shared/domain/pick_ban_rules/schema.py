"""Ruleset v2 document: pydantic shapes + the resolved-step record.

The field names are the wire contract shared with the frontend
(``PickBanRuleset*`` in ``frontend/src/types/tournament.types.ts``) and with
``pick_ban_config.ruleset_json`` / ``pick_ban_session.resolved_sequence_json``.

Shape validation only. Everything semantic (ids unique, generator/mode
agreement, condition trees, constraint params) lives in :mod:`.validate`, so a
single ``validate_ruleset`` call is the one place that decides whether a
ruleset may be saved.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

Condition = dict[str, Any]

StepAction = Literal["ban", "pick", "protect", "decider", "side_pick", "assign"]
#: Who answers a member step (spec §11.6 R4-1): ``next`` -- the acting team's next member in pick order, ``each`` --
#: every member of every acting team at once, ``any`` -- whichever of the acting team's members still without a hero
#: this round the pick is made for (bound like ``next`` until then, so the clock's stand-in is the first of them left).
MemberMode = Literal["next", "each", "any"]
TimeoutPolicy = Literal["random_fill", "lock_draft", "wait"]
StepTarget = Literal["opponent_player"]
Generator = Literal["bracket", "slot_veto"]

#: Who takes a step, before the encounter is known. ``slot:<n>`` names
#: a seat of the card, ``side:<code>`` the participation that chose that side
#: in an earlier ``side_pick``. ``home``/``away`` are accepted when read off a
#: stored document and resolve to slots 1 and 2; nothing writes them.
ACTORS_PATTERN = re.compile(
    r"^(first|second|both|system|winner_prev|loser_prev|home|away|slot:[1-9][0-9]*|side:[a-z0-9_-]{1,16})$"
)

#: ``home``/``away`` and the slots they resolve to.
LEGACY_ACTOR_SLOTS: Mapping[str, int] = {"home": 1, "away": 2}

#: One resolved actor: the id of the participation that acts, or ``None`` when
#: the engine itself resolves the step.
ResolvedActor = int | None

Severity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class Issue:
    """One validation finding. ``path`` is a JSON-ish path into the ruleset
    (``phases[1].steps[0].count``); ``code`` is a stable snake_case key the
    frontend may translate, ``message`` the English fallback."""

    path: str
    code: str
    severity: Severity
    message: str

    def to_json(self) -> dict[str, Any]:
        return {"path": self.path, "code": self.code, "severity": self.severity, "message": self.message}


class RulesetError(ValueError):
    """Raised by :func:`parse_ruleset` when the document is not even shaped
    like a ruleset. Carries the same ``Issue`` list validation returns."""

    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{issue.path}: {issue.message}" for issue in issues) or "invalid ruleset")


class DisputeRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    #: How many times a revealed step may be reopened unilaterally.
    max: int = 0


class Constraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    params: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"type": self.type, "params": dict(self.params)}


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    action: StepAction
    #: One of :data:`ACTORS_PATTERN`.
    actors: str
    #: Items per acting participation.
    count: int = 1
    #: Items required to lock; ``None`` = ``count``.
    min: int | None = None
    #: Drafts stay private until every acting side locked.
    blind: bool = False
    target: StepTarget | None = None
    #: Ban only: maps the ban stays active (1 = this map only); ``None`` = rest of series.
    lifetime: int | None = None
    #: ``None`` = inherit ``Ruleset.timer_seconds``.
    timer_seconds: int | None = None
    #: ``None`` = inherit ``Ruleset.on_timeout``.
    on_timeout: TimeoutPolicy | None = None
    dispute: DisputeRule = Field(default_factory=DisputeRule)
    eligible: Condition = Field(default_factory=dict)
    constraints: list[Constraint] = Field(default_factory=list)
    #: A mix room's hero pick made by a member rather than the team (``None``); see :data:`MemberMode`. Stored only
    #: when set, so a team-only ruleset stays byte-identical for readers that predate it.
    member: MemberMode | None = Field(default=None, exclude_if=lambda value: value is None)
    #: A member step only the team's captain (or a host) answers, for any teammate -- a member without a captain on
    #: the lineup still answers for themselves. Stored only when set, like ``member``.
    captains_only: bool = Field(default=False, exclude_if=lambda value: not value)

    @field_validator("actors")
    @classmethod
    def _known_actors(cls, value: str) -> str:
        if not ACTORS_PATTERN.match(value):
            raise ValueError(f"unknown actors {value!r}")
        return value


class Phase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str | None = None
    #: Context ``round``; ``{}`` = always.
    when: Condition = Field(default_factory=dict)
    #: Context ``pool``; candidates failing it never enter the round.
    pool_filter: Condition = Field(default_factory=dict)
    #: Map kind only; when set, ``steps`` must be empty.
    generator: Generator | None = None
    steps: list[Step] = Field(default_factory=list)


class Ruleset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[2] = 2
    timer_seconds: int | None = None
    on_timeout: TimeoutPolicy = "random_fill"
    phases: list[Phase] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ResolvedStep(BaseModel):
    """One step of ``pick_ban_session.resolved_sequence_json`` — a step of the
    ruleset bound to a concrete round: actors resolved to the PARTICIPATIONS
    that take it, inherited timer/min/on_timeout filled in, ``index`` global in
    the session.

    One actor token cannot be bound when the round is resolved: ``side:<code>``
    names whoever a ``side_pick`` EARLIER IN THE SAME ROUND will hand that side
    to, and that is not known until the step is played. Such a step is written
    with no actors and keeps its token in ``actors_token``; the runtime binds it
    the moment the side exists (:func:`runtime.bind_side_actors`), and
    :func:`runtime.current_step` stops on it until then, so an unbound step can
    never be skipped past.
    """

    model_config = ConfigDict(extra="forbid")

    index: int
    #: ``None`` in flat mode (a single-round map veto).
    round: int | None
    phase_id: str
    step_id: str
    action: StepAction
    #: Participation ids, in acting order; ``[None]`` for an engine-resolved
    #: step, and ``[]`` while ``actors_token`` is still waiting on its side.
    actors: list[ResolvedActor]
    #: The ruleset token this step's actors are resolved from. Kept after the
    #: binding, not cleared: an undo of the ``side_pick`` that assigned the side
    #: has to be able to un-bind the step again, and a cleared token would have
    #: thrown that away. ``None`` for every step bound at round-open.
    actors_token: str | None = None
    count: int
    min: int
    blind: bool
    target: StepTarget | None
    lifetime: int | None
    timer_seconds: int | None
    on_timeout: TimeoutPolicy
    dispute: DisputeRule
    eligible: Condition
    constraints: list[Constraint]
    #: Like ``member_seats``, stored only when set: a team-only session stays byte-identical for older readers.
    member: MemberMode | None = Field(default=None, exclude_if=lambda value: value is None)
    #: ``(participation, encounter.team_member id)`` per member a member step owes an answer from, in pick order --
    #: bound with the actors (:func:`compile.bind_members`). Empty for a team step and while the actors wait on a side.
    member_seats: list[tuple[int, int]] = Field(default_factory=list, exclude_if=lambda value: not value)
    #: See :attr:`Step.captains_only`; stored only when set.
    captains_only: bool = Field(default=False, exclude_if=lambda value: not value)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ResolvedStep:
        return cls.model_validate(data)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @property
    def acting_actors(self) -> list[int]:
        """The participations that owe this step an answer (the engine dropped)."""
        return [actor for actor in self.actors if actor is not None]

    @property
    def answers(self) -> list[tuple[int | None, int | None]]:
        """Who owes this step an answer: ``(participation, member)`` per member of a member step, else
        ``(participation, None)`` per actor -- ``(None, None)`` for the engine. Every submission lookup walks this."""
        if self.member is not None:
            return list(self.member_seats)
        return [(actor, None) for actor in self.actors]

    @property
    def is_system(self) -> bool:
        return self.actors == [None]

    @property
    def is_unbound(self) -> bool:
        """Whether this step still owes its actors a ``side_pick`` result."""
        return not self.actors and self.actors_token is not None

    @property
    def is_bound_to_side(self) -> bool:
        """Whether this step's actors came from a ``side_pick`` -- and so have
        to be taken back if that pick is undone."""
        return bool(self.actors) and (self.actors_token or "").startswith("side:")

    def unbound(self) -> ResolvedStep:
        """This step with its actors -- and the members bound from them -- taken back: what an undo of the
        ``side_pick`` that assigned its side leaves behind."""
        return self.model_copy(update={"actors": [], "member_seats": []})


def format_path(loc: tuple[Any, ...]) -> str:
    """``("phases", 1, "steps", 0, "count")`` -> ``phases[1].steps[0].count``."""
    path = ""
    for part in loc:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path


def parse_ruleset(data: Any) -> Ruleset:
    """Parse a ruleset document. Raises :class:`RulesetError` with one issue
    per pydantic error (path + ``schema_invalid``)."""
    if not isinstance(data, dict):
        raise RulesetError([Issue("", "schema_invalid", "error", "ruleset must be an object")])
    try:
        return Ruleset.model_validate(data)
    except ValidationError as exc:
        issues = [
            Issue(format_path(error["loc"]), "schema_invalid", "error", str(error.get("msg", "invalid value")))
            for error in exc.errors()
        ]
        raise RulesetError(issues) from exc


def resolved_steps_from_json(
    data: list[dict[str, Any]], *, actors_by_slot: Mapping[int, int] | None = None
) -> list[ResolvedStep]:
    """The session's stored sequence as engine objects.

    A stored sequence may hold ``sides: ["home"|"away"|"system"]`` instead of
    participation ids; ``actors_by_slot`` (``slot -> participation``) turns
    those into their seats. Such a row whose slot is not seated raises: the
    room cannot be read at all in that state, and resolving it to "the engine
    acts" would silently hand a captain's step to the clock.
    """
    return [ResolvedStep.from_json(_actors(row, actors_by_slot)) for row in data]


def _actors(row: dict[str, Any], actors_by_slot: Mapping[int, int] | None) -> dict[str, Any]:
    if "sides" not in row:
        return row
    translated: list[ResolvedActor] = []
    for side in row["sides"]:
        if side == "system":
            translated.append(None)
            continue
        slot = LEGACY_ACTOR_SLOTS.get(str(side))
        actor = (actors_by_slot or {}).get(slot) if slot is not None else None
        if actor is None:
            raise ValueError(f"stored pick-ban step names {side!r}, which no participation covers")
        translated.append(actor)
    return {**{key: value for key, value in row.items() if key != "sides"}, "actors": translated}
