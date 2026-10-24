from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.core.utils import join_entity, prepare_entities, selectin_entity
from shared.repository.base import BaseRepository
from shared.repository.identity import UserRepository


class TournamentRepository(BaseRepository[models.Tournament]):
    def __init__(self) -> None:
        super().__init__(models.Tournament)

    async def get_by_name(self, session: AsyncSession, name: str) -> models.Tournament | None:
        return await self.get_by(session, name=name)

    async def get_by_slug(self, session: AsyncSession, slug: str) -> models.Tournament | None:
        return await self.get_by(session, slug=slug)

    async def resolve_public_ref(self, session: AsyncSession, ref: int | str) -> models.Tournament | None:
        """Resolve a public URL ref to a tournament: a legacy numeric id, the
        current slug, or an old slug an explicit rename retired (see
        ``models.TournamentSlugRedirect``). Old links keep resolving even after
        a rename -- only newly generated links ever use the current slug.
        """
        if isinstance(ref, int):
            return await self.get(session, ref)
        tournament = await self.get_by_slug(session, ref)
        if tournament is not None:
            return tournament
        redirected_id = await session.scalar(
            sa.select(models.TournamentSlugRedirect.tournament_id).where(models.TournamentSlugRedirect.old_slug == ref)
        )
        return await self.get(session, redirected_id) if redirected_id is not None else None

    async def get_workspace_id(self, session: AsyncSession, tournament_id: int) -> int | None:
        """The owning workspace, without loading the rest of the row.

        A cheap scalar lookup for the common "does this tournament belong to
        that workspace" check (e.g. the stream-svc repoll ownership guard),
        which never needs anything but this one column.
        """
        return await session.scalar(
            sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
        )

    async def lock_for_computation(
        self, session: AsyncSession, tournament_id: int, *, skip_locked: bool = False
    ) -> int | None:
        """The bracket/standings workers' lock on the tournament row, held to commit.

        ``FOR NO KEY UPDATE``, not ``FOR UPDATE``: it still excludes every writer
        of the row (the other worker, an admin ``UPDATE``), but not the
        ``FOR KEY SHARE`` a foreign-key check takes for any insert that references
        the tournament. An achievement run inserts such rows and holds them for its
        whole 30-50 s transaction; under ``FOR UPDATE`` that held every standings
        job, and with it the next Swiss round, for as long.

        ``None`` with ``skip_locked`` when another writer holds the row (or it is gone).
        """
        return await session.scalar(
            sa.select(models.Tournament.id)
            .where(models.Tournament.id == tournament_id)
            .with_for_update(skip_locked=skip_locked, key_share=True)
        )

    async def get_owner(self, session: AsyncSession, tournament_id: int) -> tuple[int | None, str] | None:
        """``(workspace_id, discipline)`` of the tournament, or ``None`` when it does not exist.

        The discipline is the tournament's own column: it is what chooses a game's module, never a caller's guess.
        """
        row = (
            await session.execute(
                sa.select(models.Tournament.workspace_id, models.Tournament.discipline).where(
                    models.Tournament.id == tournament_id
                )
            )
        ).one_or_none()
        return None if row is None else (row.workspace_id, row.discipline)

    async def list_by_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
    ) -> Sequence[models.Tournament]:
        result = await session.execute(
            sa.select(models.Tournament)
            .where(models.Tournament.workspace_id == workspace_id)
            .order_by(models.Tournament.id.desc())
        )
        return result.scalars().all()

    async def list_filtered(
        self,
        session: AsyncSession,
        *,
        is_league: bool | None = None,
        is_finished: bool | None = None,
        workspace_id: int | None = None,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.Tournament]:
        """Unpaginated tournament list with optional equality filters, in id order.

        Skips ``list()``'s COUNT query -- every current caller here only ever
        wants the rows.
        """
        query = self._apply_options(self.select(), options).order_by(models.Tournament.id.asc())
        if is_league is not None:
            query = query.where(models.Tournament.is_league.is_(is_league))
        if is_finished is not None:
            query = query.where(models.Tournament.is_finished.is_(is_finished))
        if workspace_id is not None:
            query = query.where(models.Tournament.workspace_id == workspace_id)
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def get_summary_row(self, session: AsyncSession, tournament_id: int) -> sa.Row | None:
        """``(id, name, status)`` of the tournament, or ``None`` when it does not exist. No ``is_hidden`` filter."""
        return (
            await session.execute(
                sa.select(models.Tournament.id, models.Tournament.name, models.Tournament.status).where(
                    models.Tournament.id == tournament_id
                )
            )
        ).one_or_none()

    async def get_draft_format_json(self, session: AsyncSession, tournament_id: int) -> dict | None:
        """The stored draft format rule; ``None`` when the tournament never set one (snake)."""
        return await session.scalar(
            sa.select(models.Tournament.draft_format_json).where(models.Tournament.id == tournament_id)
        )

    async def get_team_formation(self, session: AsyncSession, tournament_id: int) -> str | None:
        """How the tournament forms its teams (``balancer``, ``draft``, ...); ``None`` when it does not exist."""
        return await session.scalar(
            sa.select(models.Tournament.team_formation).where(models.Tournament.id == tournament_id)
        )

    async def get_for_registration(self, session: AsyncSession, registration_id: int) -> models.Tournament | None:
        """The tournament a balancer registration belongs to."""
        return await session.scalar(
            sa.select(models.Tournament)
            .join(models.Registration, models.Registration.tournament_id == models.Tournament.id)
            .where(models.Registration.id == registration_id)
        )


class StageRepository(BaseRepository[models.Stage]):
    def __init__(self) -> None:
        super().__init__(models.Stage)

    async def get(
        self,
        session: AsyncSession,
        id: int | str,
        *,
        options: Sequence[_AbstractLoad] | None = None,
        populate_existing: bool = False,
    ) -> models.Stage | None:
        # A plain lookup is an identity-map hit: an encounter list resolves the
        # same few stages once per row, and a SELECT each is N statements.
        if options is None and not populate_existing:
            return await session.get(models.Stage, id)
        return await super().get(session, id, options=options, populate_existing=populate_existing)

    async def list_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.Stage]:
        """Stages in organizer order. ``id`` is only a tiebreak for equal ``order``."""
        query = self._apply_options(
            self.select()
            .where(models.Stage.tournament_id == tournament_id)
            .order_by(models.Stage.order.asc(), models.Stage.id.asc()),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def get_next_order(self, session: AsyncSession, tournament_id: int) -> int:
        """Highest existing stage order in this tournament, plus one (0 if none exist)."""
        result = await session.execute(
            sa.select(sa.func.coalesce(sa.func.max(models.Stage.order), -1)).where(
                models.Stage.tournament_id == tournament_id
            )
        )
        return int(result.scalar_one()) + 1

    async def get_tournament_id(self, session: AsyncSession, stage_id: int) -> int | None:
        """Scope resolution: which tournament a stage belongs to.

        A projection rather than a full row load — every caller wants the id only,
        to gate a permission check or to scope a sibling lookup.
        """
        return await session.scalar(sa.select(models.Stage.tournament_id).where(models.Stage.id == stage_id))


class StageItemRepository(BaseRepository[models.StageItem]):
    def __init__(self) -> None:
        super().__init__(models.StageItem)

    async def get(
        self,
        session: AsyncSession,
        id: int | str,
        *,
        options: Sequence[_AbstractLoad] | None = None,
        populate_existing: bool = False,
    ) -> models.StageItem | None:
        # Identity-map lookup for a plain read; see ``StageRepository.get``.
        if options is None and not populate_existing:
            return await session.get(models.StageItem, id)
        return await super().get(session, id, options=options, populate_existing=populate_existing)

    async def list_by_stage(self, session: AsyncSession, stage_id: int) -> Sequence[models.StageItem]:
        result = await session.execute(
            sa.select(models.StageItem)
            .where(models.StageItem.stage_id == stage_id)
            .order_by(models.StageItem.order.asc(), models.StageItem.id.asc())
        )
        return result.scalars().all()


def _in_swiss_scope(
    model: type[models.SwissBye] | type[models.SwissStoppedScope], stage_id: int, stage_item_id: int | None
) -> tuple:
    return model.stage_id == stage_id, model.stage_item_id.is_not_distinct_from(stage_item_id)


class SwissByeRepository(BaseRepository[models.SwissBye]):
    def __init__(self) -> None:
        super().__init__(models.SwissBye)

    async def team_ids(self, session: AsyncSession, stage_id: int, stage_item_id: int | None) -> list[int]:
        result = await session.execute(
            sa.select(models.SwissBye.team_id)
            .where(*_in_swiss_scope(models.SwissBye, stage_id, stage_item_id))
            .order_by(models.SwissBye.id)
        )
        return list(result.scalars().all())

    async def delete_round(
        self, session: AsyncSession, stage_id: int, stage_item_id: int | None, round_number: int
    ) -> None:
        await session.execute(
            sa.delete(models.SwissBye).where(
                *_in_swiss_scope(models.SwissBye, stage_id, stage_item_id), models.SwissBye.round == round_number
            )
        )

    async def delete_scope(self, session: AsyncSession, stage_id: int, stage_item_id: int | None) -> None:
        await session.execute(
            sa.delete(models.SwissBye).where(*_in_swiss_scope(models.SwissBye, stage_id, stage_item_id))
        )


class SwissStoppedScopeRepository(BaseRepository[models.SwissStoppedScope]):
    def __init__(self) -> None:
        super().__init__(models.SwissStoppedScope)

    async def mark(self, session: AsyncSession, stage_id: int, stage_item_id: int | None) -> None:
        exists = await session.scalar(
            sa.select(models.SwissStoppedScope.id).where(
                *_in_swiss_scope(models.SwissStoppedScope, stage_id, stage_item_id)
            )
        )
        if exists is None:
            await self.create(session, models.SwissStoppedScope(stage_id=stage_id, stage_item_id=stage_item_id))

    async def delete_scope(self, session: AsyncSession, stage_id: int, stage_item_id: int | None) -> None:
        await session.execute(
            sa.delete(models.SwissStoppedScope).where(
                *_in_swiss_scope(models.SwissStoppedScope, stage_id, stage_item_id)
            )
        )


class BracketEncounterRepository(BaseRepository[models.BracketEncounter]):
    """``tournament.bracket_encounter`` — where an encounter sits in a bracket.

    The row's key is ``encounter_id``, so the base ``get`` (keyed on ``id``) does
    not apply; ``get_position`` is the identity-map primary-key lookup.
    """

    def __init__(self) -> None:
        super().__init__(models.BracketEncounter)

    async def get_position(self, session: AsyncSession, encounter_id: int) -> models.BracketEncounter | None:
        return await session.get(models.BracketEncounter, encounter_id)


class TeamRepository(BaseRepository[models.Team]):
    def __init__(self) -> None:
        super().__init__(models.Team)

    @staticmethod
    def team_entities(in_entities: list[str], child: Any | None = None) -> list[_AbstractLoad]:
        """Eager-load options for a ``Team`` read, gated by the requested entity
        tokens (``tournament``, ``players``[``.user``], ``captain``, ``placement``,
        ``group``). Shared by every service that serializes a Team -- the token
        vocabulary is a superset across services (e.g. parser's ``TeamRead`` has
        no ``group`` field, so it never requests that token; the branch simply
        never runs for it).

        ``players``/``placement``/``group`` use ``selectin_entity``, never
        ``join_entity``: they're to-many relationships, and joinedload on a
        to-many multiplies the row set (see ``shared.core.utils.selectin_entity``).
        """
        entities: list[_AbstractLoad] = []
        if "tournament" in in_entities:
            entities.append(join_entity(child, models.Team.tournament))
        if "players" in in_entities:
            players_entities = prepare_entities(in_entities, "players")
            players_entity = selectin_entity(child, models.Team.players)
            entities.append(players_entity)
            # PlayerRead.user_id is a required field (resolved from
            # workspace_member.player_id), so workspace_member itself must always
            # be loaded here -- not just when "user" is requested. The nested
            # workspace_member.player (+ further user sub-entities) stays gated
            # behind "user" since that's the expensive/optional part.
            workspace_member_entity = join_entity(players_entity, models.Player.workspace_member)
            entities.append(workspace_member_entity)
            if "user" in players_entities:
                user_entity = join_entity(workspace_member_entity, models.WorkspaceMember.player)
                entities.append(user_entity)
                entities.extend(
                    UserRepository.identity_options(prepare_entities(players_entities, "user"), user_entity)
                )
        if "captain" in in_entities:
            captain_entity = join_entity(child, models.Team.captain)
            entities.append(captain_entity)
            entities.extend(UserRepository.identity_options(prepare_entities(in_entities, "captain"), captain_entity))
        if "placement" in in_entities:
            entities.append(selectin_entity(child, models.Team.standings))
        if "group" in in_entities:
            standings = selectin_entity(child, models.Team.standings)
            entities.append(standings)
            entities.append(join_entity(standings, models.Standing.stage_item))
        return entities

    async def get_by_name_and_tournament(
        self,
        session: AsyncSession,
        *,
        name: str,
        tournament_id: int,
    ) -> models.Team | None:
        return await self.get_by(session, name=name, tournament_id=tournament_id)

    async def list_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.Team]:
        query = self._apply_options(
            sa.select(models.Team).where(models.Team.tournament_id == tournament_id).order_by(models.Team.id.asc()),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def claim_captain(self, session: AsyncSession, team_id: int, captain_id: int) -> bool:
        """Set ``captain_id`` only while the team has none; whether this call won it."""
        result = await session.execute(
            sa.update(models.Team)
            .where(models.Team.id == team_id, models.Team.captain_id.is_(None))
            .values(captain_id=captain_id)
        )
        return result.rowcount != 0


class PlayerRepository(BaseRepository[models.Player]):
    def __init__(self) -> None:
        super().__init__(models.Player)

    @staticmethod
    def player_entities(in_entities: list[str], child: Any | None = None) -> list[_AbstractLoad]:
        """Eager-load options for a ``Player`` read, gated by the requested entity
        tokens (``user``, ``tournament``, ``team``). Shared by every service that
        serializes a Player.

        ``workspace_member`` is always loaded, regardless of tokens:
        ``PlayerRead.user_id`` is a required field resolved from
        ``workspace_member.player_id`` -- the nested ``.player`` (full user
        profile) stays gated behind ``"user"``.
        """
        entities: list[_AbstractLoad] = []
        workspace_member_entity = join_entity(child, models.Player.workspace_member)
        entities.append(workspace_member_entity)
        if "user" in in_entities:
            entities.append(join_entity(workspace_member_entity, models.WorkspaceMember.player))
        if "tournament" in in_entities:
            entities.append(join_entity(child, models.Player.tournament))
        if "team" in in_entities:
            team_entity = join_entity(child, models.Player.team)
            entities.append(team_entity)
            entities.extend(TeamRepository.team_entities(prepare_entities(in_entities, "team"), team_entity))
        return entities

    async def get_by_user_and_tournament(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        tournament_id: int,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> models.Player | None:
        """One roster row for a user in a tournament.

        ``user_id`` is a ``User.id``, reached through ``workspace_member`` — ``Player``
        has no ``user_id`` column; ``workspace_member_id`` is the sole identity anchor.
        """
        query = self._apply_options(
            sa.select(models.Player).where(
                models.Player.workspace_member.has(models.WorkspaceMember.player_id == user_id),
                models.Player.tournament_id == tournament_id,
            ),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().first()

    async def rated_roster_rows(
        self, session: AsyncSession, tournament_id: int, workspace_member_id: int
    ) -> Sequence[tuple[int | None, int | None, str | None]]:
        """``(team_id, rank, rated role code)`` of this member's roster rows in a tournament.

        The rated leaf is the player's rated-dimension role, root or workspace sub-role alike
        (``rated_role_code`` only reports sub-roles).
        """
        rated_leaf = (
            sa.select(models.CatalogRole.code)
            .select_from(models.PlayerRole)
            .join(models.CatalogRole, models.CatalogRole.id == models.PlayerRole.role_id)
            .join(
                models.RoleDimension,
                sa.and_(
                    models.RoleDimension.id == models.CatalogRole.dimension_id, models.RoleDimension.rated.is_(True)
                ),
            )
            .where(models.PlayerRole.player_id == models.Player.id)
            .limit(1)
            .scalar_subquery()
        )
        result = await session.execute(
            sa.select(models.Player.team_id, models.Player.rank, rated_leaf).where(
                models.Player.tournament_id == tournament_id, models.Player.workspace_member_id == workspace_member_id
            )
        )
        return result.tuples().all()

    async def list_by_related_player(self, session: AsyncSession, player_id: int) -> Sequence[models.Player]:
        """Roster rows that name ``player_id`` as the player they substitute for.

        One level only — the caller walks the chain itself to collect descendants.
        """
        result = await session.execute(
            self.select().where(models.Player.related_player_id == player_id).order_by(models.Player.id.asc())
        )
        return result.scalars().all()


class EncounterRepository(BaseRepository[models.Encounter]):
    def __init__(self) -> None:
        super().__init__(models.Encounter)

    def select(self) -> sa.Select[tuple[models.Encounter]]:
        """Tournament-owned encounters only: a mix round is not a tournament encounter, and every
        get/lock/list here starts from this one predicate instead of trusting a join to the tournament."""
        return super().select().where(models.Encounter.tournament_id.is_not(None))

    def count_select(self) -> sa.Select[tuple[int]]:
        return super().count_select().where(models.Encounter.tournament_id.is_not(None))

    async def get_for_update(
        self,
        session: AsyncSession,
        encounter_id: int,
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> models.Encounter | None:
        """Locking read for every result write.

        ``SELECT ... FOR UPDATE`` so two concurrent writers to one encounter
        serialize instead of interleaving a read-modify-write on ``score`` and
        ``result_version``. ``populate_existing`` is part of the lock, not an
        optimization: an encounter already in the identity map would otherwise
        be handed back exactly as it was first read, and the version this
        writer bumps would be a stale one. Eager-load ``options`` ride along in
        the same locked statement.
        """
        query = (
            self._apply_options(self.select().where(models.Encounter.id == encounter_id), options)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await session.execute(query)
        return result.unique().scalars().first()

    async def get_any_owner_for_update(
        self, session: AsyncSession, encounter_id: int, *, skip_locked: bool = False
    ) -> models.Encounter | None:
        """``get_for_update`` without the tournament-owned predicate (D77's one exception): the pick-ban, readiness
        and chat paths run a mix round's room (spec §8.2), and a consumer that must leave a mix round a refusal
        receipt locks it first. ``skip_locked`` is for the scheduled healers, which must never queue."""
        result = await session.execute(
            super()
            .select()
            .where(models.Encounter.id == encounter_id)
            .with_for_update(skip_locked=skip_locked)
            .execution_options(populate_existing=True)
        )
        return result.unique().scalars().first()

    async def get_any_owner(self, session: AsyncSession, encounter_id: int) -> models.Encounter | None:
        """``get_any_owner_for_update``'s plain read: no lock, no refresh, the identity-mapped row when there is one --
        for the room reads (state, the healer's pre-check, a mix's overview signal) that must not queue behind a
        writer."""
        return await session.get(models.Encounter, encounter_id)

    async def list_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Sequence[models.Encounter]:
        """Bracket order, then id. An encounter with no bracket position -- a
        mix, a scrim -- sorts last rather than dropping out of the list."""
        result = await session.execute(
            sa.select(models.Encounter)
            .outerjoin(
                models.BracketEncounter,
                models.BracketEncounter.encounter_id == models.Encounter.id,
            )
            .where(models.Encounter.tournament_id == tournament_id)
            .order_by(models.BracketEncounter.round.asc().nulls_last(), models.Encounter.id.asc())
        )
        return result.scalars().all()

    async def delete_for_stage(self, session: AsyncSession, stage_id: int) -> None:
        """Statement delete of a stage's encounters.

        NOT cascade cleanup: ``tournament.bracket_encounter.stage_id`` is
        ``ON DELETE SET NULL``, so this is the only thing standing between
        deleting a stage and orphaning its encounters. One statement rather
        than an ORM load-then-delete of the whole bracket.
        """
        await session.execute(
            sa.delete(models.Encounter).where(
                models.Encounter.id.in_(
                    sa.select(models.BracketEncounter.encounter_id).where(models.BracketEncounter.stage_id == stage_id)
                )
            )
        )

    async def delete_for_stage_item(self, session: AsyncSession, stage_item_id: int) -> None:
        """Statement delete — see ``delete_for_stage``, scoped to one stage item
        (group/bracket lane) instead of the whole stage.
        """
        await session.execute(
            sa.delete(models.Encounter).where(
                models.Encounter.id.in_(
                    sa.select(models.BracketEncounter.encounter_id).where(
                        models.BracketEncounter.stage_item_id == stage_item_id
                    )
                )
            )
        )


class StandingRepository(BaseRepository[models.Standing]):
    def __init__(self) -> None:
        super().__init__(models.Standing)

    async def list_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Sequence[models.Standing]:
        result = await session.execute(
            sa.select(models.Standing)
            .where(models.Standing.tournament_id == tournament_id)
            .order_by(models.Standing.position.asc(), models.Standing.id.asc())
        )
        return result.scalars().all()

    async def delete_for_stage(self, session: AsyncSession, stage_id: int) -> None:
        """Statement delete — see ``EncounterRepository.delete_for_stage``."""
        await session.execute(sa.delete(models.Standing).where(models.Standing.stage_id == stage_id))

    async def delete_for_stage_item(self, session: AsyncSession, stage_item_id: int) -> None:
        """Statement delete — see ``EncounterRepository.delete_for_stage_item``."""
        await session.execute(sa.delete(models.Standing).where(models.Standing.stage_item_id == stage_item_id))

    async def delete_for_tournament(self, session: AsyncSession, tournament_id: int) -> None:
        await session.execute(sa.delete(models.Standing).where(models.Standing.tournament_id == tournament_id))

    async def delete_for_team(self, session: AsyncSession, team_id: int) -> None:
        await session.execute(sa.delete(models.Standing).where(models.Standing.team_id == team_id))


class StandingPinRepository(BaseRepository[models.StandingPin]):
    def __init__(self) -> None:
        super().__init__(models.StandingPin)

    async def replace(
        self,
        session: AsyncSession,
        *,
        stage_id: int,
        stage_item_id: int | None,
        pins: Sequence[models.StandingPin],
    ) -> None:
        """Replace one table's pins.

        The delete runs before the new rows flush, so the unique indexes never see both.
        """
        await session.execute(
            sa.delete(models.StandingPin).where(
                models.StandingPin.stage_id == stage_id,
                models.StandingPin.stage_item_id.is_not_distinct_from(stage_item_id),
            )
        )
        await self.create_many(session, pins)


class TournamentLinkRepository(BaseRepository[models.TournamentLink]):
    """``tournament.tournament_link`` — typed external links (Discord, stream, VOD, ...).

    Mostly read paths: app-service renders them, stream-svc polls the ``kind='stream'``
    ones, tournament-service's admin surface lists and validates them.
    """

    def __init__(self) -> None:
        super().__init__(models.TournamentLink)

    async def list_for_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        active_only: bool = False,
    ) -> Sequence[models.TournamentLink]:
        """Every link on a tournament, in organizer order, any kind.

        The admin list needs inactive links too, so ``is_active`` is opt-in here —
        unlike :meth:`list_active_by_kind`, which is the public render path.
        """
        filters: list[sa.ColumnElement[bool]] = [models.TournamentLink.tournament_id == tournament_id]
        if active_only:
            filters.append(models.TournamentLink.is_active.is_(True))
        result = await session.execute(
            self.select()
            .where(*filters)
            .order_by(models.TournamentLink.sort_order.asc(), models.TournamentLink.id.asc())
        )
        return result.scalars().all()

    async def find_conflict(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        kind: str,
        url: str,
        exclude_id: int | None = None,
    ) -> models.TournamentLink | None:
        """Pre-flight duplicate check for the ``(tournament, kind, url)`` constraint.

        Checked explicitly rather than by catching ``IntegrityError``: a failed flush
        poisons the session, and the 409 has to carry a domain message.
        ``exclude_id`` lets an update ignore the row it is updating.
        """
        filters: list[sa.ColumnElement[bool]] = [
            models.TournamentLink.tournament_id == tournament_id,
            models.TournamentLink.kind == kind,
            models.TournamentLink.url == url,
        ]
        if exclude_id is not None:
            filters.append(models.TournamentLink.id != exclude_id)
        result = await session.execute(self.select().where(*filters))
        return result.scalars().first()

    async def list_active_by_kind(
        self,
        session: AsyncSession,
        tournament_id: int,
        kind: str,
    ) -> Sequence[models.TournamentLink]:
        """Active links of ``kind``, in organizer order."""
        result = await session.execute(
            sa.select(models.TournamentLink)
            .where(
                models.TournamentLink.tournament_id == tournament_id,
                models.TournamentLink.kind == kind,
                models.TournamentLink.is_active.is_(True),
            )
            .order_by(models.TournamentLink.sort_order.asc(), models.TournamentLink.id.asc())
        )
        return result.scalars().all()

    async def list_active_by_kind_bulk(
        self,
        session: AsyncSession,
        tournament_ids: Sequence[int],
        kind: str,
    ) -> dict[int, list[models.TournamentLink]]:
        """``list_active_by_kind`` for every id in ``tournament_ids`` in ONE query.

        A caller that needs this for many tournaments in the same pass (the
        stream-svc poll tick, one per active tournament) would otherwise pay one
        round-trip per tournament for the exact same statement shape.
        """
        by_tournament: dict[int, list[models.TournamentLink]] = {tid: [] for tid in tournament_ids}
        if not tournament_ids:
            return by_tournament
        result = await session.execute(
            sa.select(models.TournamentLink)
            .where(
                models.TournamentLink.tournament_id.in_(tournament_ids),
                models.TournamentLink.kind == kind,
                models.TournamentLink.is_active.is_(True),
            )
            .order_by(models.TournamentLink.sort_order.asc(), models.TournamentLink.id.asc())
        )
        for link in result.scalars().all():
            by_tournament.setdefault(link.tournament_id, []).append(link)
        return by_tournament

    async def list_for_tournaments(
        self,
        session: AsyncSession,
        tournament_ids: Sequence[int],
        *,
        active_only: bool = False,
    ) -> dict[int, list[models.TournamentLink]]:
        """``list_for_tournament`` for every id in ``tournament_ids`` in ONE query.

        The public tournament list serializes ``links`` per row; without this
        that is one round-trip per tournament on the page.
        """
        by_tournament: dict[int, list[models.TournamentLink]] = {tid: [] for tid in tournament_ids}
        if not tournament_ids:
            return by_tournament
        filters: list[sa.ColumnElement[bool]] = [models.TournamentLink.tournament_id.in_(tournament_ids)]
        if active_only:
            filters.append(models.TournamentLink.is_active.is_(True))
        result = await session.execute(
            self.select()
            .where(*filters)
            .order_by(
                models.TournamentLink.tournament_id.asc(),
                models.TournamentLink.sort_order.asc(),
                models.TournamentLink.id.asc(),
            )
        )
        for link in result.scalars().all():
            by_tournament.setdefault(link.tournament_id, []).append(link)
        return by_tournament


class StageItemInputRepository(BaseRepository[models.StageItemInput]):
    def __init__(self) -> None:
        super().__init__(models.StageItemInput)


class TournamentPreviewAccessRepository(BaseRepository[models.TournamentPreviewAccess]):
    """``tournament_preview_access`` — who may see an unpublished tournament."""

    def __init__(self) -> None:
        super().__init__(models.TournamentPreviewAccess)

    async def list_for_tournament(
        self, session: AsyncSession, tournament_id: int
    ) -> Sequence[models.TournamentPreviewAccess]:
        """Grant order as the admin screen has always shown it: oldest first.

        ``id`` is the tiebreak, not the sort key — two grants inserted in one
        transaction share a ``now()`` and would otherwise come back in an arbitrary
        order, which is what the original single-column sort did.
        """
        result = await session.execute(
            self.select()
            .where(models.TournamentPreviewAccess.tournament_id == tournament_id)
            .order_by(
                models.TournamentPreviewAccess.created_at,
                models.TournamentPreviewAccess.id,
            )
        )
        return result.scalars().all()

    async def get_grant(
        self, session: AsyncSession, *, tournament_id: int, auth_user_id: int
    ) -> models.TournamentPreviewAccess | None:
        return await self.get_by(session, tournament_id=tournament_id, auth_user_id=auth_user_id)

    async def revoke(self, session: AsyncSession, *, tournament_id: int, auth_user_id: int) -> None:
        await session.execute(
            sa.delete(models.TournamentPreviewAccess).where(
                models.TournamentPreviewAccess.tournament_id == tournament_id,
                models.TournamentPreviewAccess.auth_user_id == auth_user_id,
            )
        )


class TournamentPhaseScheduleRepository(BaseRepository[models.TournamentPhaseSchedule]):
    """``tournament_phase_schedule`` — planned status windows for auto-transitions."""

    def __init__(self) -> None:
        super().__init__(models.TournamentPhaseSchedule)

    async def list_for_tournament(
        self, session: AsyncSession, tournament_id: int
    ) -> Sequence[models.TournamentPhaseSchedule]:
        result = await session.execute(
            self.select()
            .where(models.TournamentPhaseSchedule.tournament_id == tournament_id)
            .order_by(models.TournamentPhaseSchedule.starts_at)
        )
        return result.scalars().all()

    async def delete_for_tournament(self, session: AsyncSession, tournament_id: int) -> None:
        """Statement delete — the schedule is always rewritten wholesale."""
        await session.execute(
            sa.delete(models.TournamentPhaseSchedule).where(
                models.TournamentPhaseSchedule.tournament_id == tournament_id
            )
        )


class TournamentComputationJobRepository(BaseRepository[models.TournamentComputationJob]):
    """``computation_job`` — bracket/standings recomputation queue."""

    def __init__(self) -> None:
        super().__init__(models.TournamentComputationJob)

    async def get_job(
        self,
        session: AsyncSession,
        job_id: int,
        *,
        for_update: bool = False,
    ) -> models.TournamentComputationJob | None:
        """``for_update`` is the claim/fail lock — a worker reads the row it is about
        to transition under ``SELECT ... FOR UPDATE`` so two pollers cannot both
        advance the same job."""
        query = self.select().where(models.TournamentComputationJob.id == job_id)
        if for_update:
            query = query.with_for_update()
        return await session.scalar(query)

    async def lock_idempotency(self, session: AsyncSession, idempotency_key: str) -> None:
        """Serialize concurrent creates for the same logical job for this transaction."""
        await session.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtext(idempotency_key))))

    async def get_active_by_idempotency(
        self,
        session: AsyncSession,
        idempotency_key: str,
        statuses: Sequence[str],
    ) -> models.TournamentComputationJob | None:
        return await session.scalar(
            self.select()
            .where(
                models.TournamentComputationJob.idempotency_key == idempotency_key,
                models.TournamentComputationJob.status.in_(tuple(statuses)),
            )
            .order_by(models.TournamentComputationJob.id.desc())
            .limit(1)
        )

    async def list_jobs(
        self,
        session: AsyncSession,
        *,
        tournament_id: int | None = None,
        stage_id: int | None = None,
        statuses: Sequence[str] | None = None,
        limit: int = 50,
    ) -> Sequence[models.TournamentComputationJob]:
        query = self.select()
        if tournament_id is not None:
            query = query.where(models.TournamentComputationJob.tournament_id == tournament_id)
        if stage_id is not None:
            query = query.where(models.TournamentComputationJob.stage_id == stage_id)
        if statuses is not None:
            query = query.where(models.TournamentComputationJob.status.in_(tuple(statuses)))
        result = await session.scalars(query.order_by(models.TournamentComputationJob.id.desc()).limit(limit))
        return result.all()


class TournamentRecalculationStateRepository(BaseRepository[models.TournamentRecalculationState]):
    """``recalculation_state`` — requested vs completed generation per tournament."""

    def __init__(self) -> None:
        super().__init__(models.TournamentRecalculationState)

    async def ensure_locked(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        increment: bool,
    ) -> models.TournamentRecalculationState | None:
        """Upsert the state row, then return it locked ``FOR UPDATE``.

        The ``ON CONFLICT DO UPDATE ... requested_generation + 1`` is the whole
        concurrency story: two mutations landing together must each advance the
        generation exactly once, which a read-then-write cannot guarantee. When
        ``increment`` is false the insert is a pure "ensure exists" (``DO NOTHING``).
        The trailing locked read is what serializes the caller's subsequent
        ``completed_generation`` write against a concurrent worker.
        """
        state = models.TournamentRecalculationState
        statement = pg_insert(state).values(
            tournament_id=tournament_id,
            requested_generation=1 if increment else 0,
            completed_generation=0,
        )
        if increment:
            statement = statement.on_conflict_do_update(
                index_elements=[state.tournament_id],
                set_={
                    "requested_generation": state.requested_generation + 1,
                    "updated_at": sa.func.now(),
                },
            )
        else:
            statement = statement.on_conflict_do_nothing(index_elements=[state.tournament_id])
        await session.execute(statement)
        return await session.scalar(self.select().where(state.tournament_id == tournament_id).with_for_update())

    async def get_by_tournament(
        self, session: AsyncSession, tournament_id: int
    ) -> models.TournamentRecalculationState | None:
        return await self.get_by(session, tournament_id=tournament_id)
