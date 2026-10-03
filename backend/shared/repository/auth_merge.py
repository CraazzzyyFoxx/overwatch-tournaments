"""Database-only support for profile/auth merges; the caller owns the transaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from shared import models
from shared.core.db import Base
from shared.models.identity.rbac import role_permissions, user_roles
from shared.schemas.user_merge_auth import AuthMergePreview, AuthMergeResult

# Owner column, resulting uniqueness key, and data that needs explicit resolution.
# New CASCADE dependents are detected below and blocked, never implicitly discarded.
RESOURCES = {
    models.SubscriptionEntitlement.__table__: (
        "auth_user_id",
        ("workspace_id", "auth_user_id", "provider"),
        ("state", "tier_rank", "tier_label", "source", "checked_at", "expires_at", "evidence_json"),
    ),
    models.MemberRank.__table__: (
        "author_user_id",
        ("workspace_id", "author_user_id", "workspace_member_id", "role"),
        ("rank_value",),
    ),
    models.FavoritePlayer.__table__: ("auth_user_id", ("auth_user_id", "player_id"), ()),
    models.EncounterSavedView.__table__: (
        "auth_user_id",
        ("workspace_id", "auth_user_id", "name"),
        ("filters_json", "sort_order"),
    ),
    models.UserBalancerConfig.__table__: (
        "user_id",
        ("user_id",),
        ("config_json", "role_slots_json", "points_per_win"),
    ),
    models.NotificationPreference.__table__: ("auth_user_id", ("auth_user_id",), ("discord_dm",)),
    models.UserPermissionDeny.__table__: ("user_id", ("user_id", "permission_id", "workspace_id"), ("reason",)),
    models.TournamentPreviewAccess.__table__: ("auth_user_id", ("tournament_id", "auth_user_id"), ()),
    models.CustomGameCoHost.__table__: ("user_id", ("custom_game_id", "user_id"), ()),
    models.ScrimRoom.__table__: ("created_by_auth_user_id", ("id",), ()),
    models.NotificationRead.__table__: ("auth_user_id", ("auth_user_id", "notification_id"), ("read_at", "deleted_at")),
    models.ChatMute.__table__: (
        "auth_user_id",
        ("room_kind", "room_ref_id", "auth_user_id"),
        ("muted_until", "reason"),
    ),
}
OWNERSHIP = {
    models.Workspace.__table__: ("owner_id",),
    models.CustomGame.__table__: ("host_user_id",),
    models.DraftTeam.__table__: ("captain_auth_user_id",),
    models.BalancerRegistrationTeamInvite.__table__: ("target_auth_user_id",),
    models.SubscriptionCheckLog.__table__: ("auth_user_id",),
    models.Notification.__table__: ("recipient_auth_user_id",),
}
CREDENTIAL_TABLES = {models.RefreshToken.__table__, models.ApiKey.__table__}
LOGICAL_OWNERSHIP = {
    models.Notification.__table__: "recipient_auth_user_id",
    models.NotificationRead.__table__: "auth_user_id",
    models.ChatMute.__table__: "auth_user_id",
}


@dataclass
class _Plan:
    preview: AuthMergePreview
    donor_id: int | None
    destinations: dict[int, int]
    updates: list[tuple[sa.Table, dict[str, Any], dict[str, Any]]] = field(default_factory=list)
    deletes: list[tuple[sa.Table, dict[str, Any]]] = field(default_factory=list)
    workspace_ids: set[int] = field(default_factory=set)
    moved_role_ids: set[int] = field(default_factory=set)


@dataclass
class AuthMergeState:
    accounts: list[dict[str, Any]]
    rows: dict[sa.Table, list[dict[str, Any]]]
    auth_foreign_keys: dict[sa.Table, tuple[sa.ForeignKey, ...]]
    memberships: list[dict[str, Any]]
    socials: list[dict[str, Any]]
    roles: list[dict[str, Any]]
    permissions: list[dict[str, Any]]
    role_permissions: list[dict[str, Any]]
    role_grants: list[dict[str, Any]]
    player_links: list[dict[str, Any]]


async def _rows(session: AsyncSession, table: sa.Table, condition: Any, *, lock: bool) -> list[dict[str, Any]]:
    query = sa.select(table).where(condition).order_by(*table.primary_key.columns)
    if lock:
        query = query.with_for_update()
    return [dict(row) for row in (await session.execute(query)).mappings()]


async def load_auth_merge_state(
    session: AsyncSession,
    source: models.User,
    target: models.User,
    *,
    lock: bool = False,
) -> AuthMergeState:
    auth_ids = sorted({value for value in (source.auth_user_id, target.auth_user_id) if value is not None})
    player_ids = [source.id, target.id]
    # Lock parents first. PostgreSQL FK key-share locks then prevent new auth
    # dependents from racing the validated snapshot and subsequent deletion.
    accounts = await _rows(session, models.AuthUser.__table__, models.AuthUser.id.in_(auth_ids), lock=lock)
    links = await _rows(
        session,
        models.User.__table__,
        sa.or_(models.User.id.in_(player_ids), models.User.auth_user_id.in_(auth_ids)),
        lock=lock,
    )
    memberships = await _rows(
        session, models.WorkspaceMember.__table__, models.WorkspaceMember.player_id.in_(player_ids), lock=lock
    )
    member_ids = [row["id"] for row in memberships]
    foreign_keys = {}
    rows = {}
    for table, owner in LOGICAL_OWNERSHIP.items():
        if lock:
            # ponytail: serialize writes to these FK-free journals during rare
            # admin merges; add auth-parent locking in writers if contention matters.
            name = session.get_bind().dialect.identifier_preparer.format_table(table)
            await session.execute(sa.text(f"LOCK TABLE {name} IN SHARE ROW EXCLUSIVE MODE"))
        rows[table] = await _rows(session, table, table.c[owner].in_(auth_ids), lock=lock)
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.fullname):
        keys = tuple(fk for fk in table.foreign_keys if fk.target_fullname == "auth.user.id")
        if not keys:
            continue
        foreign_keys[table] = keys
        conditions = [fk.parent.in_(auth_ids) for fk in keys]
        if table is models.MemberRank.__table__:
            conditions.append(table.c.workspace_member_id.in_(member_ids))
        if table is models.FavoritePlayer.__table__:
            # Third-party bookmarks on the disappearing profile are preserved too.
            conditions.append(table.c.player_id.in_(player_ids))
        rows[table] = await _rows(session, table, sa.or_(*conditions), lock=lock)
    api_key_ids = [row["id"] for row in rows.get(models.ApiKey.__table__, [])]
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.fullname):
        key_refs = [fk for fk in table.foreign_keys if fk.target_fullname == "auth.api_key.id"]
        if key_refs:
            conditions = [fk.parent.in_(api_key_ids) for fk in key_refs]
            conditions.extend(fk.parent.in_(auth_ids) for fk in foreign_keys.get(table, ()))
            rows[table] = await _rows(session, table, sa.or_(*conditions), lock=lock)
    socials = await _rows(
        session, models.SocialAccount.__table__, models.SocialAccount.user_id.in_(player_ids), lock=lock
    )
    pair_grants = rows.get(user_roles, [])
    role_ids = sorted({row["role_id"] for row in pair_grants})
    roles = await _rows(session, models.Role.__table__, models.Role.id.in_(role_ids), lock=lock)
    grants = await _rows(session, user_roles, user_roles.c.role_id.in_(role_ids), lock=lock)
    role_permission_rows = await _rows(session, role_permissions, role_permissions.c.role_id.in_(role_ids), lock=lock)
    permission_ids = {row["permission_id"] for row in role_permission_rows}
    permission_ids.update(row["permission_id"] for row in rows.get(models.UserPermissionDeny.__table__, []))
    permissions = await _rows(session, models.Permission.__table__, models.Permission.id.in_(permission_ids), lock=lock)
    if any(account["is_superuser"] for account in accounts):
        rows[models.AuthUser.__table__] = await _rows(
            session,
            models.AuthUser.__table__,
            sa.and_(models.AuthUser.is_superuser.is_(True), models.AuthUser.is_active.is_(True)),
            lock=lock,
        )
    return AuthMergeState(
        accounts, rows, foreign_keys, memberships, socials, roles, permissions, role_permission_rows, grants, links
    )


def row_identity(table: sa.Table, row: dict[str, Any]) -> sa.ColumnElement[bool]:
    return sa.and_(*(column == row[column.name] for column in table.primary_key.columns))


async def ensure_target_memberships(session: AsyncSession, target_id: int, workspace_ids: set[int]) -> dict[int, int]:
    """Create anchors only, without auto-granting any implicit baseline role."""
    if not workspace_ids:
        return {}
    table = models.WorkspaceMember.__table__
    await session.execute(
        pg_insert(table)
        .values([{"workspace_id": workspace_id, "player_id": target_id} for workspace_id in sorted(workspace_ids)])
        .on_conflict_do_nothing(constraint="uq_workspace_member_workspace_player")
    )
    result = await session.execute(
        sa.select(table.c.workspace_id, table.c.id).where(
            table.c.player_id == target_id, table.c.workspace_id.in_(workspace_ids)
        )
    )
    return dict(result.all())


async def transfer_oauth(session: AsyncSession, destinations: dict[int, int], state: AuthMergeState) -> list[int]:
    table = models.OAuthConnection.__table__
    moved = []
    for row in state.rows.get(table, []):
        destination = destinations[row["id"]]
        if destination != row["auth_user_id"]:
            await session.execute(sa.update(table).where(table.c.id == row["id"]).values(auth_user_id=destination))
            moved.append(row["id"])
    # Core UPDATE bypasses delete-orphan bookkeeping. Expire BOTH cached
    # collections and connection backrefs so a later ORM parent delete cannot
    # walk the donor's old collection and delete the transferred connections.
    for instance in list(session.identity_map.values()):
        if isinstance(instance, models.AuthUser) and instance.id in set(destinations.values()) | {
            row["auth_user_id"] for row in state.rows.get(table, [])
        }:
            session.expire(instance, ["oauth_connections", "player", "roles"])
        elif isinstance(instance, models.OAuthConnection) and instance.id in destinations:
            set_committed_value(instance, "auth_user_id", destinations[instance.id])
            session.expire(instance, ["auth_user"])
    return moved


async def link_survivor(session: AsyncSession, source: models.User, target: models.User, survivor_id: int) -> None:
    # Clear both unique links before claiming the selected survivor on target.
    table = models.User.__table__
    await session.execute(sa.update(table).where(table.c.id.in_([source.id, target.id])).values(auth_user_id=None))
    await session.execute(sa.update(table).where(table.c.id == target.id).values(auth_user_id=survivor_id))
    set_committed_value(source, "auth_user_id", None)
    set_committed_value(target, "auth_user_id", survivor_id)
    session.expire(source, ["auth_user"])
    session.expire(target, ["auth_user"])


async def apply_auth_merge_plan(
    session: AsyncSession,
    source: models.User,
    target: models.User,
    state: AuthMergeState,
    plan: _Plan,
    social_updates: dict[int, dict[str, Any]],
) -> AuthMergeResult:
    """Apply a validated preservation plan without committing its transaction."""
    fresh = plan.preview
    survivor_id = fresh.policy.surviving_auth_user_id
    members = await ensure_target_memberships(session, target.id, plan.workspace_ids)
    for source_member in state.memberships:
        if (
            source_member["player_id"] == source.id
            and source_member["display_name"] is not None
            and not any(
                row["player_id"] == target.id and row["workspace_id"] == source_member["workspace_id"]
                for row in state.memberships
            )
        ):
            await session.execute(
                sa.update(models.WorkspaceMember.__table__)
                .where(models.WorkspaceMember.id == members[source_member["workspace_id"]])
                .values(display_name=source_member["display_name"])
            )
    # Remove colliding rows first; updates can then claim all unique keys.
    for table, row in plan.deletes:
        await session.execute(sa.delete(table).where(row_identity(table, row)))
    applied_updates = {}
    for table, row, updates in plan.updates:
        if table is models.MemberRank.__table__ and isinstance(updates.get("workspace_member_id"), str):
            updates = {**updates, "workspace_member_id": members[row["workspace_id"]]}
        await session.execute(sa.update(table).where(row_identity(table, row)).values(**updates))
        applied_updates[(table, tuple(row[column.name] for column in table.primary_key.columns))] = updates
    moved = await transfer_oauth(session, plan.destinations, state)
    existing_roles = {row["role_id"] for row in state.rows.get(user_roles, []) if row["user_id"] == survivor_id}
    if plan.donor_id is not None:
        for grant in state.rows.get(user_roles, []):
            if grant["user_id"] == plan.donor_id and grant["role_id"] not in existing_roles:
                await session.execute(sa.insert(user_roles).values(user_id=survivor_id, role_id=grant["role_id"]))
                existing_roles.add(grant["role_id"])
    for grant in state.rows.get(user_roles, []):
        if grant["role_id"] not in plan.moved_role_ids or grant["user_id"] == survivor_id:
            continue
        if grant["role_id"] not in existing_roles:
            await session.execute(sa.insert(user_roles).values(user_id=survivor_id, role_id=grant["role_id"]))
            existing_roles.add(grant["role_id"])
        await session.execute(sa.delete(user_roles).where(user_roles.c.id == grant["id"]))
    await link_survivor(session, source, target, survivor_id)
    for social_id, values in social_updates.items():
        await session.execute(
            sa.update(models.SocialAccount.__table__).where(models.SocialAccount.id == social_id).values(**values)
        )
    affected_ids = sorted(row["id"] for row in state.accounts)
    token_rows = state.rows.get(models.RefreshToken.__table__, [])
    revoked = sorted({str(row["session_id"]) for row in token_rows})
    # Revoke all affected sessions, even for retained accounts: both ownership
    # and RBAC claims may have changed. API keys are not portable credentials.
    for table in CREDENTIAL_TABLES:
        owner = "user_id" if table is models.RefreshToken.__table__ else "auth_user_id"
        await session.execute(sa.delete(table).where(table.c[owner].in_(affected_ids)))
    if plan.donor_id is not None:
        await session.execute(sa.delete(models.AuthUser.__table__).where(models.AuthUser.id == plan.donor_id))
    deleted_rows = {
        (table, tuple(row[column.name] for column in table.primary_key.columns)) for table, row in plan.deletes
    }
    for instance in list(session.identity_map.values()):
        if isinstance(instance, models.AuthUser) and instance.id == plan.donor_id:
            session.expunge(instance)
        elif isinstance(instance, models.SocialAccount) and instance.id in social_updates:
            for key, value in social_updates[instance.id].items():
                set_committed_value(instance, key, value)
        else:
            instance_state = sa.inspect(instance)
            mapper = instance_state.mapper
            identity = (mapper.local_table, instance_state.identity)
            if identity in deleted_rows:
                session.expunge(instance)
            elif identity in applied_updates:
                updates = applied_updates[identity]
                for key, value in updates.items():
                    set_committed_value(instance, key, value)
                if any(column.primary_key and column.name in updates for column in mapper.local_table.columns):
                    session.expunge(instance)
                else:
                    relationships = [
                        relation.key
                        for relation in mapper.relationships
                        if any(column.name in updates for column in relation.local_columns)
                    ]
                    if relationships:
                        session.expire(instance, relationships)
    await session.flush()
    return AuthMergeResult(
        surviving_auth_user_id=survivor_id,
        deleted_auth_user_id=plan.donor_id,
        moved_oauth_connection_ids=moved,
        transferred_counts=fresh.resource_counts,
        revoked_session_ids=revoked,
        affected_auth_user_ids=affected_ids,
    )
