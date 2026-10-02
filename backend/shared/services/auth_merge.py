"""Preview and apply auth preservation inside the player's merge transaction.

Trust boundary: only the caller authorizes the operator. This module independently
validates destinations, a fresh locked snapshot and explicit destructive/permission
consent. Credentials are never copied between accounts; OAuth rows retain their
provider subject and tokens, and their ownership alone changes. Audit and the
required pre-commit session blacklisting belong to the caller, not this helper.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import BaseAPIException
from shared.core.social import oauth_handle_candidates, social_provider_for_oauth
from shared.models.identity.rbac import user_roles
from shared.repository.auth_merge import (
    CREDENTIAL_TABLES,
    OWNERSHIP,
    RESOURCES,
    AuthMergeState,
    _Plan,
    apply_auth_merge_plan,
    load_auth_merge_state,
)
from shared.schemas.user_merge_auth import (
    AuthMergeAccount,
    AuthMergeDataConflict,
    AuthMergeDeny,
    AuthMergeOAuthConnection,
    AuthMergePolicy,
    AuthMergePreview,
    AuthMergeResult,
    AuthMergeRole,
)


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, UUID)):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[redacted]"
                if any(word in str(key).lower() for word in ("token", "password", "secret", "credential"))
                else _public_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_public_value(item) for item in value]
    return _json_value(value)


def _fingerprint(state: AuthMergeState, source: models.User, target: models.User, policy: AuthMergePolicy) -> str:
    snapshot = {
        "source": [source.id, source.auth_user_id],
        "target": [target.id, target.auth_user_id],
        "policy": policy.model_dump(mode="json"),
        "accounts": state.accounts,
        "rows": {table.fullname: rows for table, rows in state.rows.items()},
        "memberships": state.memberships,
        "socials": state.socials,
        "roles": state.roles,
        "permissions": state.permissions,
        "role_permissions": state.role_permissions,
        "role_grants": state.role_grants,
        "links": [{"id": row["id"], "auth_user_id": row["auth_user_id"]} for row in state.player_links],
    }
    # Complete values (including credential rotation) are hashed internally;
    # neither the canonical snapshot nor any credential is returned to clients.
    return hashlib.sha256(
        json.dumps(_json_value(snapshot), default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _merge_value(
    incoming: Any,
    existing: Any,
    *,
    key: str,
    resource: str,
    label: str,
    policy: AuthMergePolicy,
    conflicts: list[AuthMergeDataConflict],
    atomic: bool = False,
) -> Any:
    if incoming == existing:
        return deepcopy(existing)
    if not atomic and isinstance(incoming, dict) and isinstance(existing, dict):
        merged = deepcopy(existing)
        for name, value in incoming.items():
            path_name = str(name).replace("~", "~0").replace("/", "~1")
            merged[name] = (
                _merge_value(
                    value,
                    existing[name],
                    key=f"{key}/{path_name}",
                    resource=resource,
                    label=f"{label}: {name}",
                    policy=policy,
                    conflicts=conflicts,
                )
                if name in existing
                else deepcopy(value)
            )
        return merged
    sensitive = any(word in key.lower() for word in ("token", "password", "secret", "credential"))
    conflicts.append(
        AuthMergeDataConflict(
            key=key,
            resource=resource,
            label=label,
            source_value="[redacted]" if sensitive else _public_value(incoming),
            target_value="[redacted]" if sensitive else _public_value(existing),
        )
    )
    return deepcopy(incoming if policy.conflict_choices.get(key) == "source" else existing)


def _build_plan(
    state: AuthMergeState,
    source: models.User,
    target: models.User,
    policy: AuthMergePolicy | None,
    operator_id: int | None,
) -> _Plan:
    accounts = {row["id"]: row for row in state.accounts}
    auth_ids = {value for value in (source.auth_user_id, target.auth_user_id) if value is not None}
    if policy is None:
        default_survivor_id = target.auth_user_id or source.auth_user_id
        if default_survivor_id is None:
            raise BaseAPIException(409, "Neither input player owns an auth account.")
        policy = AuthMergePolicy(surviving_auth_user_id=default_survivor_id)
    else:
        policy = policy.model_copy(deep=True)
    policy.oauth_destinations.sort(key=lambda item: item.connection_id)
    survivor_id = policy.surviving_auth_user_id
    other_ids = auth_ids - {survivor_id}
    donor_id = next(iter(other_ids)) if policy.other_account_action == "delete" and len(other_ids) == 1 else None
    issues = []
    if source.id == target.id:
        issues.append("Source and target players must be distinct.")
    if survivor_id not in auth_ids or survivor_id not in accounts:
        issues.append("Surviving auth account must belong to the two input players.")
    if set(accounts) != auth_ids:
        issues.append("An input auth account no longer exists. Preview the merge again.")
    if len(auth_ids) != len(state.accounts) or len(auth_ids) > 2:
        issues.append("Invalid input auth ownership.")
    links = {row["id"]: row["auth_user_id"] for row in state.player_links}
    if links.get(source.id) != source.auth_user_id or links.get(target.id) != target.auth_user_id:
        issues.append("Player auth ownership changed. Preview the merge again.")
    if any(row["id"] not in (source.id, target.id) and row["auth_user_id"] in auth_ids for row in state.player_links):
        issues.append("An input auth account is owned by another player.")
    if policy.other_account_action == "delete" and donor_id is None:
        issues.append("There is no distinct other auth account to delete.")
    if donor_id is not None and donor_id == operator_id:
        issues.append("Cannot delete the current operator's auth account.")

    oauth_rows = state.rows.get(models.OAuthConnection.__table__, [])
    destinations = {row["id"]: row["auth_user_id"] for row in oauth_rows}
    seen = set()
    for destination in policy.oauth_destinations:
        if destination.connection_id in seen:
            issues.append(f"OAuth connection {destination.connection_id} has duplicate destinations.")
        seen.add(destination.connection_id)
        if destination.connection_id not in destinations:
            issues.append(f"Unknown OAuth connection {destination.connection_id}.")
        elif destination.auth_user_id not in auth_ids:
            issues.append(f"OAuth connection {destination.connection_id} must remain on an input auth account.")
        else:
            destinations[destination.connection_id] = destination.auth_user_id
    if donor_id in destinations.values():
        issues.append("Every OAuth connection on the deleted account needs an explicit surviving destination.")
    for auth_id, account in accounts.items():
        if auth_id != donor_id and not account["hashed_password"] and auth_id not in destinations.values():
            issues.append(f"Retained auth account {auth_id} would have no password or OAuth login.")

    roles = {row["id"]: row for row in state.roles}
    permissions = {row["id"]: row for row in state.permissions}
    pair_grants = state.rows.get(user_roles, [])
    denies = state.rows.get(models.UserPermissionDeny.__table__, [])
    summaries = []
    for auth_id, account in accounts.items():
        account_roles = [roles[row["role_id"]] for row in pair_grants if row["user_id"] == auth_id]
        account_denies = [row for row in denies if row["user_id"] == auth_id]
        summaries.append(
            AuthMergeAccount(
                id=auth_id,
                username=account["username"],
                email=account["email"],
                has_password=bool(account["hashed_password"]),
                is_active=account["is_active"],
                is_superuser=account["is_superuser"],
                roles=[
                    AuthMergeRole(id=row["id"], name=row["name"], workspace_id=row["workspace_id"])
                    for row in account_roles
                ],
                denies=[
                    AuthMergeDeny(
                        permission_id=row["permission_id"],
                        workspace_id=row["workspace_id"],
                        resource=permissions[row["permission_id"]]["resource"],
                        action=permissions[row["permission_id"]]["action"],
                        reason=row["reason"],
                    )
                    for row in account_denies
                ],
            )
        )
    if policy.other_account_action == "keep":
        for grant in pair_grants:
            role = roles[grant["role_id"]]
            if grant["user_id"] != survivor_id and role["workspace_id"] is not None and role["name"] != "player":
                issues.append(
                    f"Retaining auth account {grant['user_id']} would strand its operational workspace role {role['name']} in workspace {role['workspace_id']}."
                )

    donor_grants = [row for row in pair_grants if row["user_id"] == donor_id]
    donor_denies = [row for row in denies if row["user_id"] == donor_id]
    permission_changes = bool(
        donor_grants or donor_denies or (donor_id in accounts and accounts[donor_id]["is_superuser"])
    )
    conflicts = []
    counts = {}
    preview = AuthMergePreview(
        accounts=summaries,
        oauth_connections=[
            AuthMergeOAuthConnection(
                id=row["id"],
                provider=row["provider"],
                provider_user_id=row["provider_user_id"],
                username=row["username"],
                auth_user_id=row["auth_user_id"],
            )
            for row in oauth_rows
        ],
        policy=policy,
        issues=issues,
        permission_changes=permission_changes,
        state_fingerprint=_fingerprint(state, source, target, policy),
    )
    plan = _Plan(preview, donor_id, destinations)
    source_members = {row["id"]: row for row in state.memberships if row["player_id"] == source.id}
    target_members = {row["workspace_id"]: row for row in state.memberships if row["player_id"] == target.id}
    plan.workspace_ids.update(row["workspace_id"] for row in source_members.values())
    plan.workspace_ids.update(
        roles[row["role_id"]]["workspace_id"]
        for row in pair_grants
        if row["user_id"] in (survivor_id, donor_id) and roles[row["role_id"]]["workspace_id"] is not None
    )

    for table, (owner, key_columns, payload_columns) in RESOURCES.items():
        groups = {}
        changed_rows = 0
        for row in state.rows.get(table, []):
            desired = dict(row)
            if donor_id is not None and row[owner] == donor_id:
                desired[owner] = survivor_id
            if table is models.FavoritePlayer.__table__ and row["player_id"] == source.id:
                desired["player_id"] = target.id
            if table is models.MemberRank.__table__ and row["workspace_member_id"] in source_members:
                workspace_id = row["workspace_id"]
                # A symbolic subject key lets preview detect a collision before
                # its target membership exists. Apply resolves it to the real id.
                desired["workspace_member_id"] = (
                    target_members[workspace_id]["id"] if workspace_id in target_members else f"target:{workspace_id}"
                )
            changed = any(row[column] != desired[column] for column in key_columns) or row[owner] != desired[owner]
            if changed:
                changed_rows += 1
            key = tuple(desired[column] for column in key_columns)
            groups.setdefault(key, []).append((row, desired, changed))
        for group in groups.values():
            group.sort(
                key=lambda item: (
                    donor_id is not None and item[0][owner] == donor_id,
                    table is models.MemberRank.__table__ and item[0]["workspace_member_id"] in source_members,
                    item[2],
                    tuple(str(item[0][column.name]) for column in table.primary_key.columns),
                )
            )
            existing, result, _ = group[0]
            selected_rank_values: set[int] = set()
            for incoming, desired, _ in group[1:]:
                identity = ":".join(str(incoming[column.name]) for column in table.primary_key.columns)
                prefix = f"{table.fullname}:{identity}"
                if table is models.SubscriptionEntitlement.__table__:
                    # A provider verdict is atomic: never synthesize active/max
                    # or mix its expiry with evidence from another observation.
                    incoming_payload = {name: desired[name] for name in payload_columns}
                    existing_payload = {name: result[name] for name in payload_columns}
                    if incoming_payload != existing_payload:
                        conflicts.append(
                            AuthMergeDataConflict(
                                key=prefix,
                                resource=table.fullname,
                                label=f"Subscription {desired['provider']} in workspace {desired['workspace_id']}",
                                source_value=_public_value(incoming_payload),
                                target_value=_public_value(existing_payload),
                            )
                        )
                        if policy.conflict_choices.get(prefix) == "source":
                            result.update(incoming_payload)
                else:
                    for name in payload_columns:
                        if table is models.MemberRank.__table__:
                            # Subject and author merges can collapse four rows.
                            # Compare immutable originals so choices never add,
                            # remove or relabel another collision.
                            conflict_key = f"{prefix}/{name}"
                            _merge_value(
                                desired[name],
                                existing[name],
                                key=conflict_key,
                                resource=table.fullname,
                                label=f"Rank {desired['role']} in workspace {desired['workspace_id']}",
                                policy=policy,
                                conflicts=conflicts,
                            )
                            if (
                                desired[name] != existing[name]
                                and policy.conflict_choices.get(conflict_key) == "source"
                            ):
                                selected_rank_values.add(desired[name])
                                result[name] = desired[name]
                            continue
                        if table is models.ChatMute.__table__ and name == "muted_until":
                            # Union two restrictions; a collision must never
                            # shorten an existing mute or erase an indefinite one.
                            result[name] = (
                                None
                                if desired[name] is None or result[name] is None
                                else max(desired[name], result[name])
                            )
                            continue
                        result[name] = _merge_value(
                            desired[name],
                            result[name],
                            key=f"{prefix}/{name}",
                            resource=table.fullname,
                            label=f"{table.name}: {name}",
                            policy=policy,
                            conflicts=conflicts,
                            atomic=table is models.UserBalancerConfig.__table__ and name == "role_slots_json",
                        )
                plan.deletes.append((table, incoming))
            if len(selected_rank_values) > 1:
                issues.append(
                    "Conflicting rank selections collapse to one rank row; select only one distinct incoming value."
                )
            updates = {
                column.name: result[column.name]
                for column in table.columns
                if column.name not in ("id", "created_at", "updated_at")
                and result[column.name] != existing[column.name]
            }
            if updates:
                plan.updates.append((table, existing, updates))
        if changed_rows:
            counts[table.fullname] = changed_rows
            if table in (
                models.CustomGameCoHost.__table__,
                models.TournamentPreviewAccess.__table__,
                models.ChatMute.__table__,
            ):
                preview.permission_changes = True

    for table, columns in OWNERSHIP.items():
        if donor_id is None:
            continue
        transferred = 0
        for row in state.rows.get(table, []):
            changes = {name: survivor_id for name in columns if row[name] == donor_id}
            if changes:
                plan.updates.append((table, row, changes))
                transferred += 1
        if transferred:
            counts[table.fullname] = counts.get(table.fullname, 0) + transferred
            if table is not models.SubscriptionCheckLog.__table__:
                preview.permission_changes = True

    # Preserve workspace-local profile content as well as rank subjects.
    for member in source_members.values():
        target_member = target_members.get(member["workspace_id"])
        if target_member and member["display_name"] is not None:
            value = (
                _merge_value(
                    member["display_name"],
                    target_member["display_name"],
                    key=f"workspace_member:{member['id']}/display_name",
                    resource="workspace_member",
                    label=f"Workspace {member['workspace_id']} display name",
                    policy=policy,
                    conflicts=conflicts,
                )
                if target_member["display_name"] is not None
                else member["display_name"]
            )
            if value != target_member["display_name"]:
                plan.updates.append((models.WorkspaceMember.__table__, target_member, {"display_name": value}))
    for table, foreign_keys in state.auth_foreign_keys.items():
        for fk in foreign_keys:
            if (
                fk.ondelete == "CASCADE"
                and table not in set(RESOURCES) | CREDENTIAL_TABLES | {models.OAuthConnection.__table__, user_roles}
                and donor_id is not None
            ):
                if any(row[fk.parent.name] == donor_id for row in state.rows.get(table, [])):
                    issues.append(
                        f"Cannot preserve unsupported auth-owned resource {table.fullname}.{fk.parent.name}; deletion is blocked."
                    )
    survivor = accounts.get(survivor_id)
    resulting_denies = [row for row in denies if row["user_id"] in (survivor_id, donor_id)]
    for grant in pair_grants:
        if donor_id is None or grant["user_id"] not in (survivor_id, donor_id):
            continue
        role = roles[grant["role_id"]]
        if role["name"] != "owner" or role["workspace_id"] is None:
            continue
        if survivor:
            governance_denied = any(
                row["workspace_id"] in (None, role["workspace_id"])
                and permissions[row["permission_id"]]["resource"]
                in ("workspace", "workspace_member", "role", "permission", "admin", "*")
                for row in resulting_denies
            )
            if not survivor["is_active"] or governance_denied:
                issues.append(
                    f"Merge would leave workspace {role['workspace_id']} ownership with a disabled or governance-denied account."
                )
    if (
        donor_id in accounts
        and accounts[donor_id]["is_superuser"]
        and accounts[donor_id]["is_active"]
        and survivor
        and not survivor["is_superuser"]
    ):
        if not any(row["id"] not in (donor_id, survivor_id) for row in state.rows.get(models.AuthUser.__table__, [])):
            issues.append(
                "Cannot delete the last active platform superuser; surviving account flags are never promoted."
            )
    known = {conflict.key for conflict in conflicts}
    for key in policy.conflict_choices.keys() - known:
        issues.append(f"Unknown data conflict choice {key}.")
    counts["oauth_connections"] = sum(row["auth_user_id"] != destinations[row["id"]] for row in oauth_rows)
    preview.permission_changes |= bool(counts["oauth_connections"])
    counts["workspace_memberships"] = len(plan.workspace_ids - set(target_members))
    for table in CREDENTIAL_TABLES:
        counts[f"revoked_{table.fullname}"] = len(state.rows.get(table, []))
    if donor_id is not None:
        counts["roles"] = len(donor_grants)
    preview.resource_counts = counts
    preview.data_conflicts = conflicts
    preview.issues = issues
    return plan


async def preview_auth_merge(
    session: AsyncSession,
    source: models.User,
    target: models.User,
    policy: AuthMergePolicy | None,
    *,
    operator_auth_user_id: int | None = None,
) -> AuthMergePreview | None:
    if source.auth_user_id is None and target.auth_user_id is None:
        return None
    state = await load_auth_merge_state(session, source, target)
    return _build_plan(state, source, target, policy, operator_auth_user_id).preview


async def apply_auth_merge(
    session: AsyncSession,
    source: models.User,
    target: models.User,
    preview: AuthMergePreview,
    *,
    confirm_auth_changes: bool,
    confirm_auth_deletion: bool,
    confirm_permission_changes: bool,
    operator_auth_user_id: int | None,
) -> AuthMergeResult:
    state = await load_auth_merge_state(session, source, target, lock=True)
    plan = _build_plan(state, source, target, preview.policy, operator_auth_user_id)
    fresh = plan.preview
    if fresh.state_fingerprint != preview.state_fingerprint:
        raise BaseAPIException(409, "Auth merge state changed. Preview the merge again.")
    if fresh.issues:
        raise BaseAPIException(409, "; ".join(fresh.issues))
    if any(conflict.key not in fresh.policy.conflict_choices for conflict in fresh.data_conflicts):
        raise BaseAPIException(409, "Resolve every auth data conflict before merging.")
    if not confirm_auth_changes:
        raise BaseAPIException(409, "Explicit auth changes confirmation is required.")
    if plan.donor_id is not None and not confirm_auth_deletion:
        raise BaseAPIException(409, "Explicit auth account deletion confirmation is required.")
    if fresh.permission_changes and not confirm_permission_changes:
        raise BaseAPIException(409, "Explicit permission changes confirmation is required.")
    # All rejection paths above precede any destructive operation.
    survivor_id = fresh.policy.surviving_auth_user_id
    # Apply before the parent's social selection: both players' proofs are
    # checked against the final target owner. Unselected source rows disappear
    # with source, selected rows keep only evidence the survivor actually owns.
    oauth_rows = state.rows.get(models.OAuthConnection.__table__, [])
    social_updates = {}
    for social in state.socials:
        if not social["is_verified"] or social_provider_for_oauth(social["provider"]) is None:
            continue
        matches = [
            row
            for row in oauth_rows
            if social_provider_for_oauth(row["provider"]) == social["provider"]
            and plan.destinations[row["id"]] == survivor_id
            and (
                row["provider_user_id"] == social["provider_user_id"]
                if social["provider_user_id"] is not None
                else social["username_normalized"]
                in oauth_handle_candidates(
                    social["provider"],
                    username=row["username"],
                    display_name=row["display_name"],
                    provider_data=row["provider_data"],
                )
            )
        ]
        values = {"is_verified": bool(matches)}
        if not matches:
            # A stale pin is an identity claim too; free it when its actual
            # login stays on the other retained auth account.
            values["provider_user_id"] = None
        social_updates[social["id"]] = values
    return await apply_auth_merge_plan(session, source, target, state, plan, social_updates)
