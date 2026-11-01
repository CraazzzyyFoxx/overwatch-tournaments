"""The game handle a surface may show for a person: the game's identity provider's primary account, visible in scope.

Display only. Identity resolution (rank lookups, log matching) keeps using the unfiltered primary handle; this one
honours ``SocialAccountVisibility``: an account shows only with a global row or a row for ``workspace_id``.
A Steam account shows its persona name (``display_name``), never the opaque account id.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.social import PROVIDERS
from shared.disciplines import DISCIPLINES, identity_provider
from shared.schemas.identity import PersonDisplayRead

__all__ = ("game_handle", "game_handle_of", "load_person_displays", "pick_game_handle")


def _shows_persona(provider: str) -> bool:
    spec = PROVIDERS.get(provider)
    return spec is not None and spec.normalize == "steam_id"


def game_handle(
    user_id: sa.ColumnElement[int],
    provider: str,
    workspace_id: sa.ColumnElement[int] | int | None,
) -> sa.ScalarSelect[str | None]:
    """Correlated scalar: the shown handle of ``user_id``'s primary visible ``provider`` account, or NULL.

    A scalar rather than a join for the reason ``main_handle`` gives: several accounts of one provider would
    multiply the rows.
    """
    account = models.SocialAccount
    visibility = models.SocialAccountVisibility
    scope = visibility.workspace_id.is_(None)
    if workspace_id is not None:
        scope = sa.or_(scope, visibility.workspace_id == workspace_id)
    label = account.display_name if _shows_persona(provider) else account.username
    return (
        sa.select(label)
        .where(
            account.user_id == user_id,
            account.provider == provider,
            # Not auto-correlated: a column ``workspace_id`` belongs to the select two levels up.
            sa.exists().where(visibility.account_id == account.id, scope).correlate_except(visibility),
        )
        .order_by(account.is_primary.desc(), account.id.asc())
        .limit(1)
        .scalar_subquery()
    )


def pick_game_handle(accounts: Iterable[models.SocialAccount], provider: str, workspace_id: int | None) -> str | None:
    """``game_handle`` over loaded accounts; their ``visibilities`` must be loaded."""
    visible = [
        account
        for account in accounts
        if account.provider == provider
        and any(v.workspace_id is None or v.workspace_id == workspace_id for v in account.visibilities)
    ]
    if not visible:
        return None
    account = min(visible, key=lambda a: (not a.is_primary, a.id))
    return account.display_name if _shows_persona(provider) else account.username


def game_handle_of(
    user_id: sa.ColumnElement[int], discipline: sa.ColumnElement[str], workspace_id: sa.ColumnElement[int] | int | None
) -> sa.ColumnElement[str | None]:
    """``game_handle`` for a row whose game is a column (a cross-game read): each game's own provider."""
    codes: dict[str, list[str]] = {}
    for code, spec in DISCIPLINES.items():
        if spec.identity_provider:
            codes.setdefault(spec.identity_provider, []).append(code)
    return sa.case(
        *((discipline.in_(group), game_handle(user_id, provider, workspace_id)) for provider, group in codes.items()),
        else_=None,
    )


async def load_person_displays(
    session: AsyncSession,
    user_ids: Iterable[int],
    *,
    discipline: str,
    workspace_id: int | None,
    snapshots: Mapping[int, str | None] | None = None,
) -> dict[int, PersonDisplayRead]:
    """How each user is named on a ``discipline`` surface of ``workspace_id`` (``None``: the discipline-wide scope).

    ``snapshots`` maps a user id to the name the surface's own event recorded, if it has one.
    """
    ids = set(user_ids)
    if not ids:
        return {}
    provider = identity_provider(discipline)
    user, member = models.User, models.WorkspaceMember
    query = sa.select(
        user.id,
        user.name,
        game_handle(user.id, provider, workspace_id),
        *((member.display_name,) if workspace_id is not None else ()),
    ).where(user.id.in_(ids))
    if workspace_id is not None:
        query = query.outerjoin(member, sa.and_(member.player_id == user.id, member.workspace_id == workspace_id))
    return {
        uid: PersonDisplayRead.build(
            canonical=name,
            provider=provider,
            handle=handle,
            workspace_name=rest[0] if rest else None,
            snapshot=(snapshots or {}).get(uid),
        )
        for uid, name, handle, *rest in (await session.execute(query)).all()
    }
