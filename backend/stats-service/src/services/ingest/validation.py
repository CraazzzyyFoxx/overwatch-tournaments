"""Semantic validation of an ``owt.match/1`` document against the authenticated workspace and discipline.

Read-only by contract: it never commits, flushes or writes a diagnostic. A rejection carries every bounded miss and
issue path so the caller (the ingest failure transaction, which owns durability) can persist them *after* the
observation transaction rolled back -- a validation failure must not roll back the evidence of its own rejection.

Scoping rules, each enforced in the query rather than after it:

* entities: this discipline, kind ``map`` for the map, ``mode`` for the mode and ``character`` for fact/event
  entities, ``active``; codes are catalog slugs, never aliases (aliases decode a module's raw names; canonical codes are
  not synonym-normalised). A document without ``mode`` is played in the map's catalog parent mode (if any); a given
  ``mode`` must equal that parent when the map has one (``mode_map_mismatch``);
* stat/event definitions: this discipline and ``active`` (``StatDefRepository.ids`` serves historical reads and does
  not filter ``active``);
* roles: the discipline's rated dimension, module roles plus this workspace's own leaves, ancestry validated;
* hints: tournament/encounter/game must exist in *this* workspace and discipline and agree with one another; the
  failure never says whether the id exists elsewhere.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared import models
from shared.core.social import matches_handle_pattern
from shared.disciplines import DISCIPLINES
from shared.domain.roles import Ontology, RoleNode, UnknownRole
from shared.repository import WorkspaceRepository
from shared.repository.roles import CatalogRoleRepository
from shared.schemas.match_doc import (
    MAX_ISSUES,
    MAX_MATCH_DOC_BYTES,
    IngestIssue,
    MatchDoc,
    MatchDocError,
    parse_match_doc,
)

__all__ = ("DocumentRejected", "IngestIssue", "ValidatedDocument", "load_document", "validate_document")

_roles = CatalogRoleRepository()
_workspaces = WorkspaceRepository()


class DocumentRejected(Exception):
    """The document cannot be ingested. ``code`` classifies the rejection; ``issues`` locate every problem found."""

    def __init__(self, code: str, issues: Iterable[IngestIssue]) -> None:
        self.code = code
        self.issues = tuple(issues)[:MAX_ISSUES]
        first = self.issues[0] if self.issues else None
        super().__init__(f"{code}: {first.message}" if first else code)

    def misses(self) -> dict[str, tuple[str, ...]]:
        """Distinct vocabulary misses by kind (``character|map|mode|stat|event|role``), ready for ``record_miss``."""
        grouped: dict[str, set[str]] = {}
        for issue in self.issues:
            if issue.kind is not None and issue.raw_name is not None:
                grouped.setdefault(issue.kind, set()).add(issue.raw_name)
        return {kind: tuple(sorted(names)) for kind, names in sorted(grouped.items())}


@dataclass(frozen=True, slots=True)
class ValidatedDocument:
    """The document as received plus the native ids its codes resolved to (no row was read for update)."""

    doc: MatchDoc
    workspace_id: int
    discipline: str
    map_id: int
    #: catalog ``mode`` entity: the document's ``mode``, else the map's parent mode; ``None`` when neither exists
    mode_id: int | None
    #: character slug -> catalog.entity id (facts' and events' ``entity``/``related_entity``)
    entity_ids: Mapping[str, int]
    stat_ids: Mapping[str, int]
    event_type_ids: Mapping[str, int]
    #: ``(dimension, role)`` -> catalog.role id of the resolved leaf
    role_ids: Mapping[tuple[str, str], int]


def load_document(raw: bytes, *, max_bytes: int = MAX_MATCH_DOC_BYTES) -> MatchDoc:
    """Strict bytes -> :class:`MatchDoc`; the one place a malformed document becomes a :class:`DocumentRejected`."""
    try:
        return parse_match_doc(raw, max_bytes=max_bytes)
    except MatchDocError as exc:
        raise DocumentRejected("invalid_document", exc.issues) from None


class _Collector:
    """Issues in document order; a vocabulary miss keeps only its first path per ``(kind, raw_name)``."""

    def __init__(self) -> None:
        self.issues: list[IngestIssue] = []
        self._missed: set[tuple[str, str]] = set()

    def add(self, path: list[str | int], code: str, message: str) -> None:
        self.issues.append(IngestIssue(path, code, message))

    def miss(self, path: list[str | int], kind: str, raw_name: str, code: str, message: str) -> None:
        if (kind, raw_name) not in self._missed:
            self._missed.add((kind, raw_name))
            self.issues.append(IngestIssue(path, code, message, kind=kind, raw_name=raw_name))


def _references(doc: MatchDoc) -> list[tuple[str, str, list[str | int]]]:
    """Every vocabulary code the document uses, as ``(kind, code, path)`` in document order."""
    refs: list[tuple[str, str, list[str | int]]] = [("map", doc.map, ["map"])]
    if doc.mode is not None:
        refs.append(("mode", doc.mode, ["mode"]))
    for index, fact in enumerate(doc.facts):
        refs.append(("stat", fact.stat, ["facts", index, "stat"]))
        if fact.entity is not None:
            refs.append(("character", fact.entity, ["facts", index, "entity"]))
    for index, event in enumerate(doc.events):
        refs.append(("event", event.type, ["events", index, "type"]))
        for field in ("entity", "related_entity"):
            if (code := getattr(event, field)) is not None:
                refs.append(("character", code, ["events", index, field]))
    return refs


def _any(codes: set[str]):
    """One array bind however many codes (a long list as ``IN (...)`` would exceed the driver's bind limit)."""
    return sa.any_(sa.literal(sorted(codes), type_=postgresql.ARRAY(sa.String)))


async def _entities(
    session: AsyncSession, discipline: str, codes: Mapping[str, set[str]]
) -> tuple[dict[str, dict[str, int]], dict[str, int | None]]:
    """Active ids by kind and slug, plus each found map's parent ``mode`` id (``None`` without one)."""
    entity, parent = models.CatalogEntity, aliased(models.CatalogEntity)
    kinds = ("map", "mode", "character")
    rows = await session.execute(
        sa.select(entity.kind, entity.slug, entity.id, parent.id)
        .outerjoin(
            parent,
            sa.and_(parent.id == entity.parent_id, parent.kind == "mode", parent.discipline == entity.discipline),
        )
        .where(
            entity.discipline == discipline,
            entity.active.is_(True),
            sa.or_(*(sa.and_(entity.kind == kind, entity.slug == _any(codes[kind])) for kind in kinds)),
        )
    )
    found: dict[str, dict[str, int]] = {kind: {} for kind in kinds}
    map_modes: dict[str, int | None] = {}
    for kind, slug, row_id, parent_id in rows:
        found[kind][slug] = row_id
        if kind == "map":
            map_modes[slug] = parent_id
    return found, map_modes


async def _definitions(session: AsyncSession, model: type, discipline: str, codes: set[str]) -> dict[str, int]:
    rows = await session.execute(
        sa.select(model.code, model.id).where(
            model.discipline == discipline, model.active.is_(True), model.code == _any(codes)
        )
    )
    return dict(rows.all())


def _leaf_resolves(ontology: Ontology, node: RoleNode) -> bool:
    """A workspace-owned leaf must climb, through active same-dimension ancestors, to a module-owned root."""
    seen, current = {node.id}, node
    while current.parent_id is not None:
        parent = ontology.parent(current)
        if parent is None or parent.id in seen or not parent.active or parent.dimension_id != node.dimension_id:
            return False
        seen.add(parent.id)
        current = parent
    return node.workspace_id is None or current.workspace_id is None


async def _roles_of(
    session: AsyncSession, doc: MatchDoc, workspace_id: int, found: _Collector
) -> dict[tuple[str, str], int]:
    refs = [(index, p.role) for index, p in enumerate(doc.participants) if p.role is not None]
    if not refs:
        return {}
    ontology = await _roles.ontology(session, discipline=doc.discipline, workspace_id=workspace_id)
    rated = ontology.rated.code
    resolved: dict[tuple[str, str], int] = {}
    for index, ref in refs:
        key = (ref.dimension, ref.role)
        path: list[str | int] = ["participants", index, "role"]
        raw_name = f"{ref.dimension}:{ref.role}"
        if key in resolved:
            continue
        if ref.dimension != rated:
            found.miss(
                path, "role", raw_name, "role_dimension_mismatch", "role is not on the discipline's rated dimension"
            )
            continue
        try:
            node = ontology.node(ref.dimension, ref.role)
        except UnknownRole:
            found.miss(path, "role", raw_name, "unknown_role", "role is not declared for this workspace")
            continue
        if not node.active:
            found.miss(path, "role", raw_name, "unknown_role", "role is not active for this workspace")
        elif not _leaf_resolves(ontology, node):
            found.miss(path, "role", raw_name, "invalid_role", "role does not descend from a module role")
        else:
            resolved[key] = node.id
    return resolved


async def _hints(session: AsyncSession, doc: MatchDoc, workspace_id: int, found: _Collector) -> None:
    """Hints constrain candidates only. Every failure is the same nondisclosing reference error."""
    hint = doc.hint
    if hint is None:
        return
    unresolved = "hint does not reference an object in this workspace and discipline"
    tournament, encounter, game = models.Tournament, models.Encounter, models.EncounterGame
    tournament_row = encounter_row = game_row = None
    if hint.tournament_id is not None:
        tournament_row = await session.scalar(
            sa.select(tournament.id).where(
                tournament.id == hint.tournament_id,
                tournament.workspace_id == workspace_id,
                tournament.discipline == doc.discipline,
            )
        )
        if tournament_row is None:
            found.add(["hint", "tournament_id"], "hint_unresolved", unresolved)
    if hint.encounter_id is not None:
        encounter_row = (
            await session.execute(
                sa.select(encounter.id, encounter.tournament_id).where(
                    encounter.id == hint.encounter_id,
                    encounter.workspace_id == workspace_id,
                    encounter.discipline == doc.discipline,
                )
            )
        ).first()
        if encounter_row is None:
            found.add(["hint", "encounter_id"], "hint_unresolved", unresolved)
    if hint.encounter_game_id is not None:
        game_row = (
            await session.execute(
                sa.select(game.id, game.encounter_id, encounter.tournament_id)
                .join(encounter, encounter.id == game.encounter_id)
                .where(
                    game.id == hint.encounter_game_id,
                    encounter.workspace_id == workspace_id,
                    encounter.discipline == doc.discipline,
                )
            )
        ).first()
        if game_row is None:
            found.add(["hint", "encounter_game_id"], "hint_unresolved", unresolved)
    # Mutual agreement: a hint set that names different series is as unresolvable as a foreign id.
    if (
        encounter_row is not None
        and hint.tournament_id is not None
        and encounter_row.tournament_id != hint.tournament_id
    ):
        found.add(["hint", "encounter_id"], "hint_unresolved", unresolved)
    if game_row is not None and hint.encounter_id is not None and game_row.encounter_id != hint.encounter_id:
        found.add(["hint", "encounter_game_id"], "hint_unresolved", unresolved)
    elif game_row is not None and hint.tournament_id is not None and game_row.tournament_id != hint.tournament_id:
        found.add(["hint", "encounter_game_id"], "hint_unresolved", unresolved)


async def validate_document(
    session: AsyncSession,
    *,
    workspace_id: int,
    doc: MatchDoc,
    producer: Literal["canonical", "decoded"] = "canonical",
) -> ValidatedDocument:
    """Resolve every code of ``doc`` for ``workspace_id``; raise :class:`DocumentRejected` with all findings.

    ``producer="canonical"`` (a caller-authored document) also enforces each known provider's handle grammar at
    ``participants[i].identity.id`` and that no event is later than ``duration_s``; ``"decoded"`` documents
    (server-authored from raw logs) carry bare in-game names and the log's own timeline and skip both. Everything
    else is identical.

    Reads run under ``no_autoflush``: pending state of the caller's session is never flushed by validation.
    """
    with session.no_autoflush:
        return await _validate(session, workspace_id, doc, producer)


async def _validate(session: AsyncSession, workspace_id: int, doc: MatchDoc, producer: str) -> ValidatedDocument:
    spec = DISCIPLINES.get(doc.discipline)
    registered = await session.scalar(sa.select(models.Discipline.code).where(models.Discipline.code == doc.discipline))
    if spec is None or registered is None:
        raise DocumentRejected(
            "unknown_discipline", [IngestIssue(["discipline"], "unknown_discipline", "discipline is not registered")]
        )
    workspace = await _workspaces.get(session, workspace_id)
    if workspace is None or doc.discipline not in workspace.disciplines_enabled:
        raise DocumentRejected(
            "discipline_not_enabled",
            [IngestIssue(["discipline"], "discipline_not_enabled", "discipline is not enabled for this workspace")],
        )

    found = _Collector()
    for index, person in enumerate(doc.participants):
        if spec.identity_provider is None or person.identity.provider != spec.identity_provider:
            found.add(
                ["participants", index, "identity", "provider"],
                "unknown_identity_provider",
                "identity provider is not this discipline's provider",
            )
        elif producer == "canonical" and not matches_handle_pattern(person.identity.provider, person.identity.id):
            found.add(
                ["participants", index, "identity", "id"],
                "invalid_identity",
                "identity id is not a valid handle for the provider",
            )
    if producer == "canonical":
        # A caller-authored timeline must end with the match. A raw log keeps what it recorded (its observations and
        # duration are preserved as decoded), so this is a producer rule, not a structural one.
        for index, event in enumerate(doc.events):
            if event.t > doc.duration_s:
                found.add(["events", index, "t"], "event_after_end", "t exceeds duration_s")

    refs = _references(doc)
    wanted: dict[str, set[str]] = {kind: set() for kind in ("map", "mode", "character", "stat", "event")}
    for kind, code, _ in refs:
        wanted[kind].add(code)
    entities, map_modes = await _entities(session, doc.discipline, wanted)
    stat_ids = await _definitions(session, models.StatDef, doc.discipline, wanted["stat"])
    event_ids = await _definitions(session, models.EventType, doc.discipline, wanted["event"])
    resolved = {**entities, "stat": stat_ids, "event": event_ids}
    for kind, code, path in refs:
        if code not in resolved[kind]:
            found.miss(path, kind, code, f"unknown_{kind}", f"{kind} code is not available for this discipline")
    map_mode = map_modes.get(doc.map)
    mode_id = entities["mode"].get(doc.mode) if doc.mode is not None else map_mode
    if doc.mode is not None and mode_id is not None and map_mode not in (None, mode_id):
        found.miss(["mode"], "mode", doc.mode, "mode_map_mismatch", "mode is not the map's catalog mode")
    role_ids = await _roles_of(session, doc, workspace_id, found)
    await _hints(session, doc, workspace_id, found)

    if found.issues:
        codes = {issue.code for issue in found.issues}
        code = next(
            (
                c
                for c in ("unknown_identity_provider", "invalid_identity", "event_after_end", "mode_map_mismatch")
                if c in codes
            ),
            "unresolved_references",
        )
        raise DocumentRejected(code, found.issues)
    return ValidatedDocument(
        doc=doc,
        workspace_id=workspace_id,
        discipline=doc.discipline,
        map_id=entities["map"][doc.map],
        mode_id=mode_id,
        entity_ids=entities["character"],
        stat_ids=stat_ids,
        event_type_ids=event_ids,
        role_ids=role_ids,
    )
