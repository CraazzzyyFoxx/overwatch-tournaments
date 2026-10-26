"""Who the participants of a document are: global players known by their social identity, workspace anchors for them.

Two steps with different side effects:

* :func:`lookup_identities` is read-only. It maps participant keys to *already known* global player ids, so the binder
  can search for a game without creating anything for a document that may never be bound.
* :func:`resolve_identities` runs once a binding is established. It creates virtual players for the unknown identities
  and observation anchors (``workspace_member`` rows) for every participant. It grants no login, role, rank or roster
  place and never revives a removed member: a log is not a membership decision. An anchor for a player who has an
  auth account is created ``observed_only`` (``insert_observation_members``): membership/visibility reads and the
  link-time role autofill skip such an anchor, and ``removed_at`` stays NULL because nothing was removed.

A canonical identity is matched exactly (its provider-normalized handle). A decoded Workshop log only has bare in-game
names, so the name before ``#`` also matches (never across providers).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.social import display_social_handle, normalize_social_handle
from shared.repository.identity import UserRepository
from shared.repository.workspace import insert_observation_members
from shared.schemas.match_doc import MatchDoc
from shared.services.social_identity import social_identity_service

__all__ = ("IdentityConflict", "lookup_identities", "resolve_identities")

Producer = Literal["canonical", "decoded"]
_users = UserRepository()


class IdentityConflict(ValueError):
    """One participant identity names several distinct global players; nobody is merged or picked."""

    code = "identity_conflict"

    def __init__(self, handles: Iterable[str]) -> None:
        self.handles = sorted(handles)
        super().__init__("identity matches more than one player: " + ", ".join(self.handles[:5]))


def _wanted(doc: MatchDoc) -> dict[tuple[str, str], list[str]]:
    """``(provider, normalized id)`` -> participant keys (the document already refuses duplicate identities)."""
    wanted: dict[tuple[str, str], list[str]] = {}
    for person in doc.participants:
        identity = (person.identity.provider, normalize_social_handle(person.identity.provider, person.identity.id))
        wanted.setdefault(identity, []).append(person.key)
    return wanted


async def lookup_identities(
    session: AsyncSession, *, workspace_id: int, doc: MatchDoc, producer: Producer = "canonical"
) -> dict[str, int]:
    """Participant key -> global player id for every identity that already exists; unknown ones are absent.

    A canonical identity owned by several global players is an :class:`IdentityConflict`. A decoded bare Workshop name
    (the ``#`` prefix rule) that several players answer to is narrowed to the workspace's own (anchored) players; if
    that still leaves more than one it is also a conflict. Nobody is merged and no row is picked.
    """
    wanted = _wanted(doc)
    if not wanted:
        return {}
    account = models.SocialAccount
    found: dict[tuple[str, str], dict[str, set[int]]] = {}
    for provider in {provider for provider, _ in wanted}:
        names = sorted({name for p, name in wanted if p == provider})
        exact = account.username_normalized.in_(names)
        prefix = sa.func.lower(sa.func.split_part(account.username, "#", 1)).in_(names)
        rows = await session.execute(
            sa.select(account.user_id, account.username, account.username_normalized).where(
                account.provider == provider, sa.or_(exact, prefix) if producer == "decoded" else exact
            )
        )
        for user_id, username, normalized in rows:
            handle = normalized or normalize_social_handle(provider, username)
            for requested in (handle, handle.split("#", 1)[0]) if producer == "decoded" else (handle,):
                if (provider, requested) in wanted:
                    kind = "exact" if requested == handle else "prefix"
                    found.setdefault((provider, requested), {}).setdefault(kind, set()).add(user_id)

    resolved: dict[str, int] = {}
    ambiguous: dict[tuple[str, str], set[int]] = {}
    for identity, by_kind in found.items():
        # A full handle beats a bare-name match; the prefix only speaks for names no exact handle claims.
        users = by_kind.get("exact") or by_kind["prefix"]
        if len(users) == 1:
            resolved_user = next(iter(users))
            for key in wanted[identity]:
                resolved[key] = resolved_user
        else:
            ambiguous[identity] = users
    if ambiguous and producer == "canonical":
        # A canonical identity names one global player; several owners is a data conflict that workspace membership
        # cannot settle (nobody is merged or picked).
        raise IdentityConflict(f"{provider}:{name}" for provider, name in ambiguous)
    if ambiguous:
        candidates = {user for users in ambiguous.values() for user in users}
        anchored = set(
            await session.scalars(
                sa.select(models.WorkspaceMember.player_id).where(
                    models.WorkspaceMember.workspace_id == workspace_id,
                    models.WorkspaceMember.player_id.in_(candidates),
                )
            )
        )
        unresolved = []
        for identity, users in ambiguous.items():
            local = users & anchored
            if len(local) == 1:
                for key in wanted[identity]:
                    resolved[key] = next(iter(local))
            else:
                unresolved.append(f"{identity[0]}:{identity[1]}")
        if unresolved:
            raise IdentityConflict(unresolved)
    return resolved


async def _lock_identities(session: AsyncSession, identities: Iterable[tuple[str, str]]) -> None:
    # One round trip for the whole roster. Sorted, so two documents naming overlapping identities queue instead of
    # deadlocking: ``unnest ... WITH ORDINALITY`` scans the array in order and each row takes its lock before the
    # next, so the acquisition order is the sorted one.
    keys = [f"stats.identity:{provider}:{normalized}" for provider, normalized in sorted(identities)]
    if not keys:
        return
    await session.execute(
        sa.text(
            "SELECT pg_advisory_xact_lock(hashtext(k)) FROM unnest(CAST(:keys AS text[])) WITH ORDINALITY AS t(k, n)"
            " ORDER BY n"
        ),
        {"keys": keys},
    )


async def resolve_identities(
    session: AsyncSession,
    *,
    workspace_id: int,
    doc: MatchDoc,
    producer: Producer = "canonical",
) -> dict[str, models.WorkspaceMember]:
    """Participant key -> the workspace member anchoring its observations, creating what is missing.

    Callers hold the final encounter/game/job/match locks first; identity advisory locks follow in sorted order and
    this path takes no encounter or game lock afterwards.
    """
    wanted = _wanted(doc)
    await _lock_identities(session, wanted)
    known = await lookup_identities(session, workspace_id=workspace_id, doc=doc, producer=producer)
    person_of = {person.key: person for person in doc.participants}
    for identity in sorted(wanted):
        keys = [key for key in wanted[identity] if key not in known]
        if not keys:
            continue
        person = person_of[keys[0]]
        display = display_social_handle(person.identity.provider, person.identity.id)
        user = await _users.create_player(session, name=display, identity=identity)
        # Virtual players are not shown on any profile: no global visibility row.
        await social_identity_service.upsert(
            session, user_id=user.id, provider=identity[0], username=display, ensure_global_visibility=False
        )
        for key in keys:
            known[key] = user.id
    await insert_observation_members(session, [(workspace_id, player_id) for player_id in set(known.values())])
    members = {
        member.player_id: member
        for member in await session.scalars(
            sa.select(models.WorkspaceMember)
            .where(
                models.WorkspaceMember.workspace_id == workspace_id,
                models.WorkspaceMember.player_id.in_(set(known.values())),
            )
            .execution_options(populate_existing=True)
        )
    }
    return {key: members[player_id] for key, player_id in known.items()}
