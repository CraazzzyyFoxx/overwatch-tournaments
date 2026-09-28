"""Ruleset v2 document: pydantic shapes + the resolved-step record.

The field names are the wire contract shared with the frontend
(``PickBanRuleset*`` in ``frontend/src/types/tournament.types.ts``) and with
``pick_ban_config.ruleset_json`` / ``pick_ban_session.resolved_sequence_json``.
Design: ``docs/plans/2026-09-28-pick-ban-constructor.md`` §1, §3.

Shape validation only. Everything semantic (ids unique, generator/mode
agreement, condition trees, constraint params) lives in :mod:`.validate`, so a
single ``validate_ruleset`` call is the one place that decides whether a
ruleset may be saved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Condition = dict[str, Any]

StepAction = Literal["ban", "pick", "protect", "decider"]
Actors = Literal["first", "second", "both", "home", "away", "winner_prev", "loser_prev", "system"]
TimeoutPolicy = Literal["random_fill", "lock_draft", "wait"]
StepTarget = Literal["opponent_player"]
Generator = Literal["bracket", "slot_veto"]
Side = Literal["home", "away"]
ResolvedSide = Literal["home", "away", "system"]

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
    actors: Actors
    #: Items per acting side.
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
    ruleset bound to a concrete round: actors resolved to sides, inherited
    timer/min/on_timeout filled in, ``index`` global in the session."""

    model_config = ConfigDict(extra="forbid")

    index: int
    #: ``None`` in flat mode (a single-round map veto).
    round: int | None
    phase_id: str
    step_id: str
    action: StepAction
    #: ``["system"]`` for engine-resolved steps.
    sides: list[ResolvedSide]
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

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ResolvedStep:
        return cls.model_validate(data)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @property
    def acting_sides(self) -> list[Side]:
        """The step's captain sides (``system`` dropped)."""
        return [side for side in self.sides if side != "system"]

    @property
    def is_system(self) -> bool:
        return self.sides == ["system"]


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


def resolved_steps_from_json(data: list[dict[str, Any]]) -> list[ResolvedStep]:
    return [ResolvedStep.from_json(row) for row in data]
