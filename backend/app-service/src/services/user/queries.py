"""Player identity lookups: by id, the paginated directory, the autocomplete and the profile-slug resolution."""

import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.core import pagination, utils
from shared.core.social import GAME_PROVIDERS, SocialProvider, normalize_social_handle

__all__ = ("UserIdentityQueries", "queries", "user_entities")

#: Providers whose publicly visible handles find a player in the autocomplete, besides the profile name.
_SEARCH_PROVIDERS: typing.Final = (*GAME_PROVIDERS, SocialProvider.DISCORD, SocialProvider.TWITCH)


def user_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    """SQLAlchemy load options for the related entities named in ``in_entities``.

    ``child`` is an existing relationship/join entity to chain the options onto
    instead of loading straight off ``User``.
    """
    entities = []
    # Unified identity source consumed by ``UserService.to_read``, loaded when ``social_accounts`` is requested.
    if "social_accounts" in in_entities:
        # Eager-load each account's visibility rows alongside it so ``to_read`` can
        # compute ``visible_global`` and (on public reads) drop hidden accounts
        # without a lazy load outside the async greenlet.
        social_load = utils.join_entity(child, models.User.social_accounts)
        entities.append(social_load.selectinload(models.SocialAccount.visibilities))
    return entities


class UserIdentityQueries:
    async def get_all(
        self, session: AsyncSession, params: pagination.PaginationSortSearchParams
    ) -> tuple[typing.Sequence[models.User], int]:
        """Paginated users matching ``params``, plus the total match count."""
        query = sa.select(models.User).options(*user_entities(params.entities))
        total_query = sa.select(sa.func.count(sa.distinct(models.User.id)))

        if params.query:
            query = params.apply_search(query, models.User)
            total_query = params.apply_search(total_query, models.User)

        query = params.apply_pagination_sort(query, models.User)

        result = await session.execute(query)
        result_total = await session.execute(total_query)
        return result.unique().scalars().all(), result_total.scalar_one()

    async def search_by_name(self, session: AsyncSession, query: str) -> typing.Sequence[sa.Row[tuple[int, str]]]:
        """Players matching ``query`` (autocomplete) as ``(id, name)`` rows, one per player.

        Matches the canonical ``players.user.name``, the handle of every publicly visible game, Discord or Twitch
        account, and the provider display name (Steam persona) of any publicly visible account. Returns up to 10
        players ranked by their best exact / prefix / trigram-similarity match.
        """
        query = query.strip().replace("-", "#")
        if not query or len(query) < 2:
            return []

        account = models.SocialAccount
        # Accounts hidden from the public profile (no global visibility row) must not surface in search either.
        public = (
            sa.select(models.SocialAccountVisibility.id)
            .where(
                models.SocialAccountVisibility.account_id == account.id,
                models.SocialAccountVisibility.workspace_id.is_(None),
            )
            .exists()
        )
        handles = sa.union_all(
            sa.select(models.User.id.label("user_id"), models.User.name.label("handle")),
            sa.select(account.user_id, account.username).where(account.provider.in_(_SEARCH_PROVIDERS), public),
            sa.select(account.user_id, account.display_name).where(account.display_name.is_not(None), public),
        ).subquery()

        column = handles.c.handle
        like_query = f"{query}%" if len(query) < 3 else f"%{query}%"
        query_lower = query.lower()

        conditions = [column.ilike(like_query)]
        if len(query) >= 3:
            conditions.append(column.op("%")(query))

        best = (
            sa.select(
                handles.c.user_id,
                sa.func.min(sa.case((sa.func.lower(column) == query_lower, 0), else_=1)).label("exact"),
                sa.func.min(sa.case((sa.func.lower(column).like(f"{query_lower}%"), 0), else_=1)).label("prefix"),
                sa.func.max(sa.func.word_similarity(column, query)).label("similarity"),
            )
            .where(sa.or_(*conditions))
            .group_by(handles.c.user_id)
            .subquery()
        )
        stmt = (
            sa.select(models.User.id, models.User.name)
            .join(best, best.c.user_id == models.User.id)
            .order_by(best.c.exact, best.c.prefix, best.c.similarity.desc(), models.User.name)
            .limit(10)
        )
        return (await session.execute(stmt)).all()

    async def find_by_battle_tag(
        self, session: AsyncSession, battle_tag: str, entities: list[str]
    ) -> models.User | None:
        """A user by battle tag, with ``entities`` eager-loaded.

        Matches the canonical player name first, then the normalized handle of any game provider, or (Battle.net
        only) the in-game name part before ``#``, case-insensitively.
        """
        normalized_battle_tag = battle_tag.strip()
        if not normalized_battle_tag:
            return None

        battle_tag_lower = normalized_battle_tag.lower()
        exact_user_name_match = sa.func.lower(models.User.name) == battle_tag_lower
        # Game identity lives in players.social_account for every game provider; each handle is compared in
        # its own provider's normal form. The bare in-game name is a BattleTag-only convenience.
        bnet_name_part = sa.func.lower(sa.func.split_part(models.SocialAccount.username, "#", 1))

        query = (
            sa.select(models.User)
            .options(*user_entities(entities))
            .outerjoin(
                models.SocialAccount,
                sa.and_(
                    models.User.id == models.SocialAccount.user_id,
                    models.SocialAccount.provider.in_(GAME_PROVIDERS),
                ),
            )
            .where(
                sa.or_(
                    exact_user_name_match,
                    sa.or_(
                        *(
                            sa.and_(
                                models.SocialAccount.provider == provider,
                                models.SocialAccount.username_normalized
                                == normalize_social_handle(provider, normalized_battle_tag),
                            )
                            for provider in GAME_PROVIDERS
                        )
                    ),
                    sa.and_(
                        models.SocialAccount.provider == SocialProvider.BATTLENET, bnet_name_part == battle_tag_lower
                    ),
                )
            )
            .order_by(
                sa.case((exact_user_name_match, 0), else_=1),
                models.User.id.asc(),
            )
            .limit(1)
        )
        result = await session.execute(query)
        return result.unique().scalar_one_or_none()

    async def find_by_exact_name(self, session: AsyncSession, name: str, entities: list[str]) -> models.User | None:
        """A user by canonical (unique) ``players.user.name``: the exact spelling first, else case-insensitively."""
        query = (
            sa.select(models.User)
            .options(*user_entities(entities))
            .where(sa.func.lower(models.User.name) == name.strip().lower())
            .order_by(sa.case((models.User.name == name.strip(), 0), else_=1), models.User.id.asc())
            .limit(1)
        )
        result = await session.execute(query)
        return result.unique().scalar_one_or_none()

    async def get_by_discord(self, session: AsyncSession, discord: str, entities: list[str]) -> models.User | None:
        """A user by Discord handle, with ``entities`` eager-loaded."""
        query = (
            sa.select(models.User)
            .options(*user_entities(entities))
            .join(models.SocialAccount, models.User.id == models.SocialAccount.user_id)
            .where(
                models.SocialAccount.provider == SocialProvider.DISCORD,
                models.SocialAccount.username_normalized == normalize_social_handle(SocialProvider.DISCORD, discord),
            )
        )
        result = await session.scalars(query)
        return result.unique().first()


queries = UserIdentityQueries()
