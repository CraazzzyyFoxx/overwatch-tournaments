from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.core.enums import HeroClass
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


class StageRepository(BaseRepository[models.Stage]):
    def __init__(self) -> None:
        super().__init__(models.Stage)

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

    async def list_by_stage(self, session: AsyncSession, stage_id: int) -> Sequence[models.StageItem]:
        result = await session.execute(
            sa.select(models.StageItem)
            .where(models.StageItem.stage_id == stage_id)
            .order_by(models.StageItem.order.asc(), models.StageItem.id.asc())
        )
        return result.scalars().all()


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

    async def get_by_player_ids(
        self,
        session: AsyncSession,
        player_ids: Sequence[int],
        tournament_id: int,
        *,
        min_players: int = 3,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> models.Team | None:
        """The team a roster (``player_ids`` = ``workspace_member.player_id`` values)
        belongs to in ``tournament_id`` -- matched by majority membership (at least
        ``min_players`` of them on one non-substitute roster), not exact set
        equality, since a sub might sit on a different team than the roster
        being resolved.
        """
        query = (
            self._apply_options(sa.select(models.Team), options)
            .join(models.Player, models.Team.id == models.Player.team_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id.in_(player_ids),
                models.Team.tournament_id == tournament_id,
                models.Player.is_substitution.is_(False),
            )
            .group_by(models.Team.id)
            .having(sa.func.count(models.Player.id) >= min_players)
        )
        result = await session.execute(query)
        return result.unique().scalars().first()


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
        has no ``user_id`` column. It was dropped in the workspace-anchoring contract
        step (iwrefac07); ``workspace_member_id`` is the sole identity anchor now. This
        method previously filtered on the dead column and raised ``InvalidRequestError``
        on every call; it had no callers, which is why nothing caught it.
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

    async def list_by_team(self, session: AsyncSession, team_id: int) -> Sequence[models.Player]:
        result = await session.execute(
            sa.select(models.Player).where(models.Player.team_id == team_id).order_by(models.Player.id.asc())
        )
        return result.scalars().all()

    async def list_by_related_player(self, session: AsyncSession, player_id: int) -> Sequence[models.Player]:
        """Roster rows that name ``player_id`` as the player they substitute for.

        One level only — the caller walks the chain itself to collect descendants.
        """
        result = await session.execute(
            self.select().where(models.Player.related_player_id == player_id).order_by(models.Player.id.asc())
        )
        return result.scalars().all()

    async def get_by_team_and_user(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        user_id: int,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> models.Player | None:
        query = self._apply_options(
            sa.select(models.Player).where(
                models.Player.workspace_member.has(models.WorkspaceMember.player_id == user_id),
                models.Player.team_id == team_id,
            ),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().first()

    async def list_by_user_and_role(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        role: HeroClass,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.Player]:
        query = self._apply_options(
            sa.select(models.Player).where(
                models.Player.workspace_member.has(models.WorkspaceMember.player_id == user_id),
                models.Player.role == role,
            ),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()


class EncounterRepository(BaseRepository[models.Encounter]):
    def __init__(self) -> None:
        super().__init__(models.Encounter)

    async def get_for_update(
        self,
        session: AsyncSession,
        encounter_id: int,
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> models.Encounter | None:
        """Locking read for admin score/result edits.

        ``SELECT ... FOR UPDATE`` so two concurrent admin updates to one encounter
        serialize instead of interleaving a read-modify-write on the score fields.
        Eager-load ``options`` ride along in the same locked statement.
        """
        query = self._apply_options(self.select().where(models.Encounter.id == encounter_id), options).with_for_update()
        result = await session.execute(query)
        return result.unique().scalars().first()

    async def get_by_challonge_id(
        self,
        session: AsyncSession,
        challonge_id: int,
    ) -> models.Encounter | None:
        return await self.get_by(session, challonge_id=challonge_id)

    async def list_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Sequence[models.Encounter]:
        result = await session.execute(
            sa.select(models.Encounter)
            .where(models.Encounter.tournament_id == tournament_id)
            .order_by(models.Encounter.round.asc(), models.Encounter.id.asc())
        )
        return result.scalars().all()

    async def list_for_stage_scope(
        self,
        session: AsyncSession,
        *,
        stage_id: int,
        stage_item_id: int | None,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.Encounter]:
        """Encounters in one stage, narrowed to one stage item (or the unassigned ones).

        ``stage_item_id=None`` renders ``IS NULL`` explicitly rather than relying on
        ``col == None``: same SQL, but the intent survives a reader who does not know
        SQLAlchemy overloads ``==``. No ``ORDER BY`` — neither caller orders, and
        inventing one would be a behaviour change.
        """
        item_clause = (
            models.Encounter.stage_item_id.is_(None)
            if stage_item_id is None
            else models.Encounter.stage_item_id == stage_item_id
        )
        query = self._apply_options(self.select().where(models.Encounter.stage_id == stage_id, item_clause), options)
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def list_by_stage(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        stage_id: int,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.Encounter]:
        query = self._apply_options(
            self.select()
            .where(
                models.Encounter.tournament_id == tournament_id,
                models.Encounter.stage_id == stage_id,
            )
            .order_by(models.Encounter.round.asc(), models.Encounter.id.asc()),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def delete_for_stage(self, session: AsyncSession, stage_id: int) -> None:
        """Statement delete of a stage's encounters.

        NOT cascade cleanup: ``Encounter.stage_id`` is ``ON DELETE SET NULL``, so this
        is the only thing standing between deleting a stage and orphaning its matches.
        One statement rather than an ORM load-then-delete of the whole bracket.
        """
        await session.execute(sa.delete(models.Encounter).where(models.Encounter.stage_id == stage_id))

    async def delete_for_stage_item(self, session: AsyncSession, stage_item_id: int) -> None:
        """Statement delete — see ``delete_for_stage``, scoped to one stage item
        (group/bracket lane) instead of the whole stage. ``Encounter.stage_item_id``
        is also ``ON DELETE SET NULL``.
        """
        await session.execute(sa.delete(models.Encounter).where(models.Encounter.stage_item_id == stage_item_id))


class MatchRepository(BaseRepository[models.Match]):
    def __init__(self) -> None:
        super().__init__(models.Match)

    async def list_by_encounter(self, session: AsyncSession, encounter_id: int) -> Sequence[models.Match]:
        result = await session.execute(
            sa.select(models.Match).where(models.Match.encounter_id == encounter_id).order_by(models.Match.id.asc())
        )
        return result.scalars().all()

    async def list_for_encounter_map(
        self,
        session: AsyncSession,
        *,
        encounter_id: int,
        map_id: int,
    ) -> Sequence[models.Match]:
        """Every match row for one (encounter, map) pair.

        Returns all of them, unordered by design — the caller picks among duplicates
        itself, and a `LIMIT 1` here would hide the duplicate case it exists to handle.
        """
        result = await session.execute(
            self.select().where(
                models.Match.encounter_id == encounter_id,
                models.Match.map_id == map_id,
            )
        )
        return result.scalars().all()


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


class PlayerSubRoleRepository(BaseRepository[models.PlayerSubRole]):
    """``player_sub_role`` — per-workspace sub-role vocabulary (role → slug → label)."""

    def __init__(self) -> None:
        super().__init__(models.PlayerSubRole)

    async def list_for_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
        *,
        role: str | None = None,
        only_active: bool = False,
    ) -> Sequence[models.PlayerSubRole]:
        filters: list[sa.ColumnElement[bool]] = [models.PlayerSubRole.workspace_id == workspace_id]
        if role is not None:
            filters.append(models.PlayerSubRole.role == role)
        if only_active:
            filters.append(models.PlayerSubRole.is_active.is_(True))
        result = await session.execute(
            self.select()
            .where(*filters)
            .order_by(
                models.PlayerSubRole.role,
                models.PlayerSubRole.sort_order,
                models.PlayerSubRole.label,
            )
        )
        return result.scalars().all()

    async def get_by_slug(
        self, session: AsyncSession, *, workspace_id: int, role: str, slug: str
    ) -> models.PlayerSubRole | None:
        return await self.get_by(session, workspace_id=workspace_id, role=role, slug=slug)


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
