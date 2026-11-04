from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from shared import models
from shared.core.enums import MapVetoSessionStatus, MixStatus, PickBanKind
from shared.core.errors import BaseAPIException
from shared.repository.base import BaseRepository
from shared.repository.roles import CatalogRoleRepository


class CustomGameRepository(BaseRepository[models.CustomGame]):
    def __init__(self) -> None:
        super().__init__(models.CustomGame)

    async def list_for_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
        discipline: str | None = None,
        *,
        statuses: Collection[str] | None = None,
        search: str | None = None,
        before_id: int | None = None,
        limit: int | None = None,
    ) -> Sequence[models.CustomGame]:
        """The workspace's mixes, newest first; one game's when ``discipline`` is given.

        ``before_id`` is a keyset cursor (ids only grow, so "older than" is
        ``id <``). ``search`` is a case-insensitive substring of the mix name or
        of the host's name as the list shows it -- the workspace display name,
        else the player name, else the account username (``hosts_by_user_id``).
        Both run here, before ``limit``, so a page is never filtered after the
        fact into a short one.
        """
        query = self.select().where(self.model.workspace_id == workspace_id)
        if discipline is not None:
            query = query.where(self.model.discipline == discipline)
        if statuses is not None:
            query = query.where(self.model.status.in_(statuses))
        if before_id is not None:
            query = query.where(self.model.id < before_id)
        if search:
            host_name = sa.func.coalesce(
                sa.func.nullif(models.WorkspaceMember.display_name, ""),
                sa.func.nullif(models.User.name, ""),
                models.AuthUser.username,
            )
            # EXISTS, not a join: the outer joins below must not fan a mix out into duplicate rows.
            host_matches = (
                sa.select(models.AuthUser.id)
                .outerjoin(models.User, models.User.auth_user_id == models.AuthUser.id)
                .outerjoin(
                    models.WorkspaceMember,
                    sa.and_(
                        models.WorkspaceMember.player_id == models.User.id,
                        models.WorkspaceMember.workspace_id == workspace_id,
                    ),
                )
                .where(
                    models.AuthUser.id == self.model.host_user_id,
                    host_name.icontains(search, autoescape=True),
                )
                .exists()
            )
            query = query.where(sa.or_(self.model.name.icontains(search, autoescape=True), host_matches))
        query = query.order_by(self.model.id.desc())
        if limit is not None:
            query = query.limit(limit)
        return (await session.scalars(query)).all()

    async def list_open_runnable(
        self, session: AsyncSession, workspace_id: int, *, user_id: int | None
    ) -> Sequence[sa.Row[tuple[int, str, int]]]:
        """``(id, name, lobby_count)`` of the open mixes ``user_id`` hosts or co-hosts, newest first.

        ``user_id=None`` drops the host filter: every open mix of the workspace.
        """
        query = (
            sa.select(models.CustomGame.id, models.CustomGame.name, models.CustomGame.lobby_count)
            .where(
                models.CustomGame.workspace_id == workspace_id,
                models.CustomGame.status.in_((MixStatus.DRAFT, MixStatus.BALANCED)),
            )
            .order_by(models.CustomGame.id.desc())
            .limit(25)  # Discord shows at most 25 autocomplete choices
        )
        if user_id is not None:
            co_hosted = sa.select(models.CustomGameCoHost.custom_game_id).where(
                models.CustomGameCoHost.user_id == user_id
            )
            query = query.where(sa.or_(models.CustomGame.host_user_id == user_id, models.CustomGame.id.in_(co_hosted)))
        return (await session.execute(query)).all()


class CustomGamePlayerRepository(BaseRepository[models.CustomGamePlayer]):
    def __init__(self) -> None:
        super().__init__(models.CustomGamePlayer)

    async def list_for_game(self, session: AsyncSession, custom_game_id: int) -> Sequence[models.CustomGamePlayer]:
        result = await session.scalars(
            self.select()
            .where(self.model.custom_game_id == custom_game_id)
            .order_by(self.model.sort_order, self.model.id)
        )
        return result.all()

    async def counts_for_games(self, session: AsyncSession, custom_game_ids: Sequence[int]) -> dict[int, int]:
        """``custom_game_id -> roster rows`` for a whole mix list in one query; an empty roster is absent."""
        if not custom_game_ids:
            return {}
        result = await session.execute(
            sa.select(self.model.custom_game_id, sa.func.count())
            .where(self.model.custom_game_id.in_(custom_game_ids))
            .group_by(self.model.custom_game_id)
        )
        return dict(result.all())


class CustomGameCoHostRepository:
    async def user_ids_for_game(self, session: AsyncSession, custom_game_id: int) -> list[int]:
        result = await session.scalars(
            sa.select(models.CustomGameCoHost.user_id).where(models.CustomGameCoHost.custom_game_id == custom_game_id)
        )
        return list(result.all())

    async def add(self, session: AsyncSession, custom_game_id: int, user_id: int) -> None:
        session.add(models.CustomGameCoHost(custom_game_id=custom_game_id, user_id=user_id))
        await session.flush()

    async def remove(self, session: AsyncSession, custom_game_id: int, user_id: int) -> None:
        await session.execute(
            sa.delete(models.CustomGameCoHost).where(
                models.CustomGameCoHost.custom_game_id == custom_game_id,
                models.CustomGameCoHost.user_id == user_id,
            )
        )
        await session.flush()


class CustomGamePlayerRoleRepository:
    async def roles_for_players(
        self,
        session: AsyncSession,
        custom_game_player_ids: Sequence[int],
    ) -> dict[int, list[str]]:
        if not custom_game_player_ids:
            return {}
        result = await session.scalars(
            sa.select(models.CustomGamePlayerRole)
            .where(models.CustomGamePlayerRole.custom_game_player_id.in_(custom_game_player_ids))
            .order_by(
                models.CustomGamePlayerRole.custom_game_player_id,
                models.CustomGamePlayerRole.priority,
            )
        )
        grouped: dict[int, list[str]] = {}
        for row in result.all():
            grouped.setdefault(row.custom_game_player_id, []).append(row.role)
        return grouped

    async def replace_for_player(
        self,
        session: AsyncSession,
        custom_game_player_id: int,
        roles: Sequence[str],
        *,
        discipline: str,
    ) -> None:
        rows = await CatalogRoleRepository().rated_rows(session, discipline=discipline, workspace_id=None)
        for code in roles:
            if code not in rows or rows[code].parent_role_id is not None:
                raise BaseAPIException(status_code=422, detail=f"unknown_role: {code!r}")
        await session.execute(
            sa.delete(models.CustomGamePlayerRole).where(
                models.CustomGamePlayerRole.custom_game_player_id == custom_game_player_id
            )
        )
        session.add_all(
            [
                models.CustomGamePlayerRole(
                    custom_game_player_id=custom_game_player_id,
                    dimension_id=rows[role].dimension_id,
                    role_id=rows[role].id,
                    catalog_role=rows[role],
                    priority=priority,
                )
                for priority, role in enumerate(roles, start=1)
            ]
        )
        await session.flush()


class CustomGameTeamNameRepository:
    async def mapping_for_game(self, session: AsyncSession, custom_game_id: int) -> dict[int, str]:
        result = await session.execute(
            sa.select(models.CustomGameTeamName.team_index, models.CustomGameTeamName.name).where(
                models.CustomGameTeamName.custom_game_id == custom_game_id
            )
        )
        return dict(result.all())

    async def mapping_for_games(
        self, session: AsyncSession, custom_game_ids: Sequence[int]
    ) -> dict[int, dict[int, str]]:
        """``custom_game_id -> {team_index: name}`` for a whole mix list in one query.

        A mix with no custom names is absent from the result.
        """
        if not custom_game_ids:
            return {}
        result = await session.execute(
            sa.select(
                models.CustomGameTeamName.custom_game_id,
                models.CustomGameTeamName.team_index,
                models.CustomGameTeamName.name,
            ).where(models.CustomGameTeamName.custom_game_id.in_(custom_game_ids))
        )
        grouped: dict[int, dict[int, str]] = {}
        for custom_game_id, team_index, name in result.all():
            grouped.setdefault(custom_game_id, {})[team_index] = name
        return grouped

    async def set(
        self,
        session: AsyncSession,
        custom_game_id: int,
        team_index: int,
        name: str | None,
    ) -> None:
        current = await session.get(models.CustomGameTeamName, (custom_game_id, team_index))
        if name is None:
            if current is not None:
                await session.delete(current)
        elif current is None:
            session.add(
                models.CustomGameTeamName(
                    custom_game_id=custom_game_id,
                    team_index=team_index,
                    name=name,
                )
            )
        else:
            current.name = name
        await session.flush()


class CustomGameLobbyRepository:
    """The per-lobby half of a mix, keyed by ``(custom_game_id, lobby_index)``.

    Not a ``BaseRepository``: the row has a composite primary key and no ``id``
    column, which every generic lookup there is written against.

    ``get`` and ``list_for_game`` re-read rows already in the session
    (``populate_existing``): a host write reads its lobbies after locking the
    mix row (``CustomGameService._writable``), and a copy loaded before that
    lock -- a live match another write has since started -- must not be served.
    """

    #: Leaves the solver document in the database. It is the one heavy column a
    #: lobby has -- an entry per balance option, megabytes once balanced -- and
    #: only the detail read and the writes that edit it look at it. ``raiseload``
    #: turns a stray read into an error instead of an implicit async lazy load.
    WITHOUT_BALANCE_RESULT = (defer(models.CustomGameLobby.balance_result_json, raiseload=True),)

    async def list_for_game(self, session: AsyncSession, custom_game_id: int) -> Sequence[models.CustomGameLobby]:
        """Both lobbies of one mix in board order, documents loaded."""
        result = await session.scalars(
            sa.select(models.CustomGameLobby)
            .where(models.CustomGameLobby.custom_game_id == custom_game_id)
            .order_by(models.CustomGameLobby.lobby_index)
            .execution_options(populate_existing=True)
        )
        return result.all()

    async def list_for_games(
        self, session: AsyncSession, custom_game_ids: Sequence[int]
    ) -> dict[int, list[models.CustomGameLobby]]:
        """``custom_game_id -> [lobby, ...]`` for a whole mix list in one query,
        without the solver documents -- no list row renders one."""
        if not custom_game_ids:
            return {}
        result = await session.scalars(
            sa.select(models.CustomGameLobby)
            .where(models.CustomGameLobby.custom_game_id.in_(custom_game_ids))
            .options(*self.WITHOUT_BALANCE_RESULT)
            .order_by(models.CustomGameLobby.custom_game_id, models.CustomGameLobby.lobby_index)
        )
        grouped: dict[int, list[models.CustomGameLobby]] = {}
        for row in result.all():
            grouped.setdefault(row.custom_game_id, []).append(row)
        return grouped

    async def get(self, session: AsyncSession, custom_game_id: int, lobby_index: int) -> models.CustomGameLobby | None:
        return await session.get(models.CustomGameLobby, (custom_game_id, lobby_index), populate_existing=True)

    async def live_started_at(self, session: AsyncSession, encounter_ids: Sequence[int]) -> dict[int, datetime | None]:
        """When each of these live matches started -- the cards' elapsed clock. No ids, no query."""
        if not encounter_ids:
            return {}
        rows = await session.execute(
            sa.select(models.Encounter.id, models.Encounter.started_at).where(models.Encounter.id.in_(encounter_ids))
        )
        return {row.id: row.started_at for row in rows}

    async def pregame_ids(self, session: AsyncSession, encounter_ids: Sequence[int]) -> frozenset[int]:
        """The live matches still in Pre-game (spec §5): started on a frozen ban preset (``live_ban_preset``) and
        their hero room not completed or cancelled -- or not open yet. Not readiness: Start marks every match's seats
        ready, with bans or without. No ids, no query."""
        if not encounter_ids:
            return frozenset()
        done = sa.exists().where(
            models.PickBanSession.encounter_id == models.CustomGameLobby.live_encounter_id,
            models.PickBanSession.kind == PickBanKind.HERO,
            models.PickBanSession.status.in_((MapVetoSessionStatus.COMPLETED, MapVetoSessionStatus.CANCELLED)),
        )
        rows = await session.scalars(
            sa.select(models.CustomGameLobby.live_encounter_id).where(
                models.CustomGameLobby.live_encounter_id.in_(encounter_ids),
                models.CustomGameLobby.live_ban_preset.is_not(None),
                ~done,
            )
        )
        return frozenset(rows)

    async def live_seats(self, session: AsyncSession, encounter_ids: Sequence[int]) -> dict[int, list[dict[str, Any]]]:
        """Each live match's participations in slot order as ``{id, slot, name}`` -- the seats its ban room names.
        No ids, no query."""
        if not encounter_ids:
            return {}
        team = models.EncounterTeam
        rows = await session.execute(
            sa.select(team.encounter_id, team.id, team.slot, team.name)
            .where(team.encounter_id.in_(encounter_ids), team.active.is_(True))
            .order_by(team.encounter_id, team.slot)
        )
        seats: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            seats.setdefault(row.encounter_id, []).append({"id": row.id, "slot": row.slot, "name": row.name})
        return seats

    async def team_sizes(self, session: AsyncSession, encounter_id: int) -> list[int]:
        """The seated (active) members of each active team of one match, in slot order."""
        team, member = models.EncounterTeam, models.EncounterTeamMember
        rows = await session.execute(
            sa.select(sa.func.count(member.id))
            .select_from(team)
            .outerjoin(member, sa.and_(member.encounter_team_id == team.id, member.active.is_(True)))
            .where(team.encounter_id == encounter_id, team.active.is_(True))
            .group_by(team.id, team.slot)
            .order_by(team.slot)
        )
        return list(rows.scalars())

    async def create(self, session: AsyncSession, lobby: models.CustomGameLobby) -> models.CustomGameLobby:
        session.add(lobby)
        await session.flush()
        return lobby

    async def delete(self, session: AsyncSession, lobby: models.CustomGameLobby) -> None:
        await session.delete(lobby)
        await session.flush()


class CustomGameBotLobbyRepository(BaseRepository[models.CustomGameBotLobby]):
    """The bot party of a live match, keyed by its encounter. Write methods flush only."""

    def __init__(self) -> None:
        super().__init__(models.CustomGameBotLobby)

    async def for_encounters(
        self, session: AsyncSession, encounter_ids: Sequence[int]
    ) -> dict[int, models.CustomGameBotLobby]:
        """``encounter_id -> party`` for the encounters that have one. No ids, no query."""
        if not encounter_ids:
            return {}
        rows = await session.scalars(
            sa.select(models.CustomGameBotLobby).where(models.CustomGameBotLobby.encounter_id.in_(encounter_ids))
        )
        return {row.encounter_id: row for row in rows}

    async def replace(self, session: AsyncSession, bot_lobby: models.CustomGameBotLobby) -> models.CustomGameBotLobby:
        """File ``bot_lobby``, dropping the previous party of its encounter."""
        await session.execute(
            sa.delete(models.CustomGameBotLobby).where(models.CustomGameBotLobby.encounter_id == bot_lobby.encounter_id)
        )
        return await self.create(session, bot_lobby)

    async def get_awaiting_by_token(self, session: AsyncSession, token_sha256: str) -> models.CustomGameBotLobby | None:
        """The party this token opened, locked, while its match id is still unknown (the token is dead after)."""
        return await session.scalar(
            sa.select(models.CustomGameBotLobby)
            .where(
                models.CustomGameBotLobby.callback_token_sha256 == token_sha256,
                models.CustomGameBotLobby.match_id.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def list_awaiting(self, session: AsyncSession, *, since: datetime) -> list[models.CustomGameBotLobby]:
        """Parties created after ``since`` whose match id is still unknown, oldest first."""
        rows = await session.scalars(
            sa.select(models.CustomGameBotLobby)
            .where(models.CustomGameBotLobby.match_id.is_(None), models.CustomGameBotLobby.created_at > since)
            .order_by(models.CustomGameBotLobby.id)
        )
        return list(rows)

    async def get_awaiting_for_update(
        self, session: AsyncSession, bot_lobby_id: int
    ) -> models.CustomGameBotLobby | None:
        """One party, locked, if its match id is still unknown."""
        return await session.scalar(
            sa.select(models.CustomGameBotLobby)
            .where(models.CustomGameBotLobby.id == bot_lobby_id, models.CustomGameBotLobby.match_id.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def match_id_for_encounter(self, session: AsyncSession, encounter_id: int) -> str | None:
        """The match id the encounter's bot party reported, else ``None``."""
        return await session.scalar(
            sa.select(models.CustomGameBotLobby.match_id).where(
                models.CustomGameBotLobby.encounter_id == encounter_id,
                models.CustomGameBotLobby.match_id.is_not(None),
            )
        )
