"""Real PostgreSQL security/data-loss checks; each case rolls its transaction back."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.core.errors import BaseAPIException
from shared.schemas.user_merge_auth import AuthMergeMembershipAction, AuthMergeOAuthDestination, AuthMergePolicy
from shared.services.auth_merge import apply_auth_merge, preview_auth_merge
from shared.testing.db import create_test_async_engine


class AuthMergeTests(IsolatedAsyncioTestCase):
    loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self):
        self.engine = create_test_async_engine()
        self.session = async_sessionmaker(self.engine, expire_on_commit=False)()
        tag = uuid4().hex
        self.donor = models.AuthUser(
            email=f"donor-{tag}@test.invalid", username=f"donor-{tag}", hashed_password="donor-secret"
        )
        self.survivor = models.AuthUser(
            email=f"survivor-{tag}@test.invalid", username=f"survivor-{tag}", hashed_password="survivor-secret"
        )
        self.session.add_all([self.donor, self.survivor])
        await self.session.flush()
        self.source = models.User(name=f"source-{tag}", auth_user_id=self.donor.id)
        self.target = models.User(name=f"target-{tag}", auth_user_id=self.survivor.id)
        self.workspace = models.Workspace(slug=f"merge-{tag}", name="Merge fixture", owner_id=self.donor.id)
        self.session.add_all([self.source, self.target, self.workspace])
        await self.session.flush()
        self.connection = models.OAuthConnection(
            auth_user_id=self.donor.id,
            provider="discord",
            provider_user_id=tag,
            username=f"discord-{tag}",
            access_token="oauth-access-secret",
            refresh_token="oauth-refresh-secret",
        )
        self.session.add(self.connection)
        await self.session.flush()

    async def asyncTearDown(self):
        await self.session.rollback()
        await self.session.close()
        await self.engine.dispose()

    def policy(self, **changes):
        return AuthMergePolicy(
            surviving_auth_user_id=self.survivor.id,
            other_account_action="delete",
            oauth_destinations=[
                AuthMergeOAuthDestination(connection_id=self.connection.id, auth_user_id=self.survivor.id)
            ],
            **changes,
        )

    async def preview(self, policy=None):
        return await preview_auth_merge(self.session, self.source, self.target, policy or self.policy())

    async def apply(self, preview, **flags):
        confirmations = {
            "confirm_auth_changes": True,
            "confirm_auth_deletion": True,
            "confirm_permission_changes": True,
            "operator_auth_user_id": None,
        }
        confirmations.update(flags)
        return await apply_auth_merge(self.session, self.source, self.target, preview, **confirmations)

    async def test_delete_preserves_oauth_loaded_collections_rank_subjects_and_credentials(self):
        await self.session.refresh(self.donor, ["oauth_connections"])
        await self.session.refresh(self.survivor, ["oauth_connections"])
        member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.source.id)
        self.session.add(member)
        await self.session.flush()
        rank = models.MemberRank(
            workspace_id=self.workspace.id,
            workspace_member_id=member.id,
            author_user_id=self.donor.id,
            role="damage",
            rank_value=2345,
        )
        canon = models.MemberRank(
            workspace_id=self.workspace.id,
            workspace_member_id=member.id,
            author_user_id=None,
            role="support",
            rank_value=3456,
        )
        session_id = uuid4()
        self.session.add_all(
            [
                rank,
                canon,
                models.FavoritePlayer(auth_user_id=self.donor.id, player_id=self.source.id),
                models.RefreshToken(
                    user_id=self.donor.id,
                    token=uuid4().hex,
                    session_id=session_id,
                    session_started_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                ),
            ]
        )
        await self.session.flush()
        preview = await self.preview()
        self.assertEqual([], preview.issues)
        encoded = preview.model_dump_json()
        for secret in ("donor-secret", "survivor-secret", "oauth-access-secret", "oauth-refresh-secret"):
            self.assertNotIn(secret, encoded)
        result = await self.apply(preview)
        await self.session.delete(self.source)
        await self.session.flush()
        await self.session.refresh(self.connection)
        self.assertEqual(self.survivor.id, self.connection.auth_user_id)
        self.assertEqual("oauth-access-secret", self.connection.access_token)
        ranks = (
            (
                await self.session.execute(
                    sa.select(models.MemberRank.__table__).where(models.MemberRank.id.in_([rank.id, canon.id]))
                )
            )
            .mappings()
            .all()
        )
        self.assertEqual({2345, 3456}, {row["rank_value"] for row in ranks})
        target_member = await self.session.scalar(
            sa.select(models.WorkspaceMember).where(
                models.WorkspaceMember.workspace_id == self.workspace.id,
                models.WorkspaceMember.player_id == self.target.id,
            )
        )
        self.assertTrue(all(row["workspace_member_id"] == target_member.id for row in ranks))
        self.assertEqual(self.survivor.id, next(row for row in ranks if row["role"] == "damage")["author_user_id"])
        self.assertEqual(
            self.survivor.id,
            await self.session.scalar(
                sa.select(models.Workspace.owner_id).where(models.Workspace.id == self.workspace.id)
            ),
        )
        bookmark = await self.session.scalar(
            sa.select(models.FavoritePlayer).where(
                models.FavoritePlayer.auth_user_id == self.survivor.id,
                models.FavoritePlayer.player_id == self.target.id,
            )
        )
        self.assertIsNotNone(bookmark)
        self.assertEqual("survivor-secret", self.survivor.hashed_password)
        self.assertIsNone(
            await self.session.scalar(sa.select(models.AuthUser.id).where(models.AuthUser.id == self.donor.id))
        )
        self.assertIn(str(session_id), result.revoked_session_ids)
        self.assertNotIn("revoked_session_ids", result.model_dump())

    async def test_invalid_ids_login_loss_and_operator_deletion_are_blocked(self):
        invalid = self.policy().model_copy(update={"surviving_auth_user_id": 2147483647})
        self.assertTrue((await self.preview(invalid)).issues)
        unknown = self.policy().model_copy(
            update={
                "oauth_destinations": [
                    AuthMergeOAuthDestination(connection_id=2147483647, auth_user_id=self.survivor.id)
                ]
            }
        )
        self.assertTrue((await self.preview(unknown)).issues)
        deletion = self.policy().model_copy(update={"oauth_destinations": []})
        self.assertTrue((await self.preview(deletion)).issues)
        self.donor.hashed_password = None
        await self.session.flush()
        kept = self.policy().model_copy(update={"other_account_action": "keep"})
        self.assertTrue((await self.preview(kept)).issues)
        preview = await preview_auth_merge(
            self.session, self.source, self.target, self.policy(), operator_auth_user_id=self.donor.id
        )
        self.assertTrue(preview.issues)
        with self.assertRaises(BaseAPIException):
            await self.apply(preview, operator_auth_user_id=self.donor.id)
        self.assertEqual(self.donor.id, self.source.auth_user_id)

    async def test_confirmations_and_unknown_conflicts_reject_before_mutation(self):
        preview = await self.preview()
        for flags in (
            {"confirm_auth_changes": False},
            {"confirm_auth_deletion": False},
            {"confirm_permission_changes": False},
        ):
            with self.assertRaises(BaseAPIException):
                await self.apply(preview, **flags)
            self.assertEqual(self.donor.id, self.source.auth_user_id)
            self.assertEqual(self.donor.id, self.connection.auth_user_id)
        unknown = await self.preview(self.policy(conflict_choices={"not-a-conflict": "source"}))
        with self.assertRaises(BaseAPIException):
            await self.apply(unknown)

    async def test_saved_view_collision_requires_choice_and_preserves_unique_preferences(self):
        for auth, filters in ((self.donor, {"map": "incoming"}), (self.survivor, {"map": "existing"})):
            self.session.add(
                models.EncounterSavedView(
                    workspace_id=self.workspace.id, auth_user_id=auth.id, name="Review", filters_json=filters
                )
            )
        self.session.add_all(
            [
                models.NotificationPreference(
                    auth_user_id=self.donor.id, discord_dm={"matches": False, "tournaments": False}
                ),
                models.NotificationPreference(
                    auth_user_id=self.survivor.id, discord_dm={"matches": True, "announcements": False}
                ),
            ]
        )
        await self.session.flush()
        preview = await self.preview()
        self.assertGreaterEqual(len(preview.data_conflicts), 2)
        with self.assertRaises(BaseAPIException):
            await self.apply(preview)
        policy = self.policy(conflict_choices={conflict.key: "source" for conflict in preview.data_conflicts})
        await self.apply(await self.preview(policy))
        view = (
            (
                await self.session.execute(
                    sa.select(models.EncounterSavedView.__table__).where(
                        models.EncounterSavedView.auth_user_id == self.survivor.id
                    )
                )
            )
            .mappings()
            .one()
        )
        self.assertEqual({"map": "incoming"}, view["filters_json"])
        preferences = await self.session.scalar(
            sa.select(models.NotificationPreference.discord_dm).where(
                models.NotificationPreference.auth_user_id == self.survivor.id
            )
        )
        self.assertEqual({"matches": False, "tournaments": False, "announcements": False}, preferences)

    async def test_stale_resource_content_and_ownership_are_rejected(self):
        saved = models.EncounterSavedView(
            workspace_id=self.workspace.id, auth_user_id=self.donor.id, name="Review", filters_json={"map": "old"}
        )
        self.session.add(saved)
        await self.session.flush()
        preview = await self.preview()
        saved.filters_json = {"map": "changed"}
        await self.session.flush()
        with self.assertRaises(BaseAPIException):
            await self.apply(preview)
        preview = await self.preview()
        self.workspace.owner_id = self.survivor.id
        await self.session.flush()
        with self.assertRaises(BaseAPIException):
            await self.apply(preview)
        self.assertEqual(self.donor.id, self.source.auth_user_id)

    async def test_keep_cannot_strand_operational_membership_and_delete_preserves_denies(self):
        role = models.Role(name="owner", workspace_id=self.workspace.id)
        permission = models.Permission(name=f"merge-deny-{uuid4().hex}", resource="account", action="social")
        self.session.add_all([role, permission])
        await self.session.flush()
        roles = models.AuthUser.__table__.metadata.tables["auth.user_roles"]
        await self.session.execute(sa.insert(roles).values(user_id=self.donor.id, role_id=role.id))
        deny = models.UserPermissionDeny(
            user_id=self.donor.id, permission_id=permission.id, workspace_id=self.workspace.id, reason="Do not erase"
        )
        self.session.add(deny)
        await self.session.flush()
        kept = self.policy().model_copy(update={"other_account_action": "keep"})
        self.assertTrue((await self.preview(kept)).issues)
        preview = await self.preview()
        self.assertTrue(preview.permission_changes)
        with self.assertRaises(BaseAPIException):
            await self.apply(preview, confirm_permission_changes=False)
        await self.apply(preview)
        grants = await self.session.scalar(sa.select(roles.c.user_id).where(roles.c.role_id == role.id))
        self.assertEqual(self.survivor.id, grants)
        row = (
            (
                await self.session.execute(
                    sa.select(models.UserPermissionDeny.__table__).where(
                        models.UserPermissionDeny.permission_id == permission.id
                    )
                )
            )
            .mappings()
            .one()
        )
        self.assertEqual(self.survivor.id, row["user_id"])
        self.assertEqual("Do not erase", row["reason"])
        member = await self.session.scalar(
            sa.select(models.WorkspaceMember.id).where(
                models.WorkspaceMember.workspace_id == self.workspace.id,
                models.WorkspaceMember.player_id == self.target.id,
            )
        )
        self.assertIsNotNone(member)

    async def test_keep_transfers_or_merges_operational_workspace_membership(self):
        role = models.Role(name="member", workspace_id=self.workspace.id)
        self.session.add(role)
        await self.session.flush()
        grants = models.AuthUser.__table__.metadata.tables["auth.user_roles"]
        await self.session.execute(sa.insert(grants).values(user_id=self.donor.id, role_id=role.id))
        await self.session.flush()
        kept = self.policy().model_copy(update={"other_account_action": "keep"})
        preview = await self.preview(kept)
        self.assertEqual([self.workspace.id], [row.workspace_id for row in preview.memberships])
        self.assertFalse(preview.memberships[0].can_merge)
        self.assertTrue(any("transfer or merge" in issue for issue in preview.issues))
        merged = kept.model_copy(
            update={"membership_actions": [AuthMergeMembershipAction(workspace_id=self.workspace.id, action="merge")]}
        )
        self.assertTrue(any("transfer it instead" in issue for issue in (await self.preview(merged)).issues))
        transferred = kept.model_copy(
            update={
                "membership_actions": [AuthMergeMembershipAction(workspace_id=self.workspace.id, action="transfer")]
            }
        )
        preview = await self.preview(transferred)
        self.assertEqual([], preview.issues)
        self.assertTrue(preview.permission_changes)
        await self.apply(preview)
        holders = (
            (await self.session.execute(sa.select(grants.c.user_id).where(grants.c.role_id == role.id))).scalars().all()
        )
        self.assertEqual([self.survivor.id], holders)
        self.assertIsNotNone(await self.session.get(models.AuthUser, self.donor.id))
        member = await self.session.scalar(
            sa.select(models.WorkspaceMember.id).where(
                models.WorkspaceMember.workspace_id == self.workspace.id,
                models.WorkspaceMember.player_id == self.target.id,
            )
        )
        self.assertIsNotNone(member)

    async def test_keep_merges_role_into_existing_workspace_membership(self):
        role = models.Role(name="member", workspace_id=self.workspace.id)
        self.session.add_all(
            [
                role,
                models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.target.id),
            ]
        )
        await self.session.flush()
        grants = models.AuthUser.__table__.metadata.tables["auth.user_roles"]
        await self.session.execute(
            sa.insert(grants).values(
                [
                    {"user_id": self.donor.id, "role_id": role.id},
                    {"user_id": self.survivor.id, "role_id": role.id},
                ]
            )
        )
        await self.session.flush()
        policy = self.policy().model_copy(
            update={
                "other_account_action": "keep",
                "membership_actions": [AuthMergeMembershipAction(workspace_id=self.workspace.id, action="merge")],
            }
        )
        preview = await self.preview(policy)
        self.assertTrue(preview.memberships[0].can_merge)
        self.assertEqual([], preview.issues)
        await self.apply(preview)
        holders = (
            (await self.session.execute(sa.select(grants.c.user_id).where(grants.c.role_id == role.id))).scalars().all()
        )
        self.assertEqual([self.survivor.id], holders)

    async def test_last_owner_cannot_be_transferred_to_disabled_account(self):
        role = models.Role(name="owner", workspace_id=self.workspace.id)
        self.session.add(role)
        await self.session.flush()
        roles = models.AuthUser.__table__.metadata.tables["auth.user_roles"]
        await self.session.execute(sa.insert(roles).values(user_id=self.donor.id, role_id=role.id))
        self.survivor.is_active = False
        await self.session.flush()
        preview = await self.preview()
        self.assertTrue(preview.issues)
        with self.assertRaises(BaseAPIException):
            await self.apply(preview)

    async def test_subscription_collision_selects_whole_validated_verdict(self):
        old = datetime(2025, 1, 1, tzinfo=UTC)
        recent = datetime(2026, 1, 1, tzinfo=UTC)
        incoming = models.SubscriptionEntitlement(
            workspace_id=self.workspace.id,
            auth_user_id=self.donor.id,
            provider="discord",
            state="inactive",
            tier_rank=None,
            checked_at=recent,
            expires_at=recent + timedelta(hours=1),
            evidence_json={"held_role_ids": [], "reason": "not_subscribed"},
        )
        existing = models.SubscriptionEntitlement(
            workspace_id=self.workspace.id,
            auth_user_id=self.survivor.id,
            provider="discord",
            state="active",
            tier_rank=3,
            checked_at=old,
            expires_at=old + timedelta(hours=1),
            evidence_json={"held_role_ids": ["supporter"]},
        )
        self.session.add_all([incoming, existing])
        await self.session.flush()
        preview = await self.preview()
        conflicts = [
            row for row in preview.data_conflicts if row.resource == models.SubscriptionEntitlement.__table__.fullname
        ]
        self.assertEqual(1, len(conflicts))
        policy = self.policy(conflict_choices={conflicts[0].key: "source"})
        await self.apply(await self.preview(policy))
        verdict = (
            (
                await self.session.execute(
                    sa.select(models.SubscriptionEntitlement.__table__).where(
                        models.SubscriptionEntitlement.auth_user_id == self.survivor.id,
                        models.SubscriptionEntitlement.workspace_id == self.workspace.id,
                    )
                )
            )
            .mappings()
            .one()
        )
        self.assertEqual("inactive", verdict["state"])
        self.assertIsNone(verdict["tier_rank"])
        self.assertEqual(recent, verdict["checked_at"])
        self.assertEqual({"held_role_ids": [], "reason": "not_subscribed"}, verdict["evidence_json"])

    async def test_rank_subject_collision_preserves_selected_incoming_value(self):
        source_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.source.id)
        target_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.target.id)
        self.session.add_all([source_member, target_member])
        await self.session.flush()
        self.session.add_all(
            [
                models.MemberRank(
                    workspace_id=self.workspace.id,
                    workspace_member_id=source_member.id,
                    author_user_id=None,
                    role="damage",
                    rank_value=1234,
                ),
                models.MemberRank(
                    workspace_id=self.workspace.id,
                    workspace_member_id=target_member.id,
                    author_user_id=None,
                    role="damage",
                    rank_value=4321,
                ),
            ]
        )
        await self.session.flush()
        preview = await self.preview()
        conflict = next(row for row in preview.data_conflicts if row.resource == models.MemberRank.__table__.fullname)
        self.assertEqual(1234, conflict.source_value)
        self.assertEqual(4321, conflict.target_value)
        await self.apply(await self.preview(self.policy(conflict_choices={conflict.key: "source"})))
        await self.session.delete(self.source)
        await self.session.flush()
        value = await self.session.scalar(
            sa.select(models.MemberRank.rank_value).where(
                models.MemberRank.workspace_member_id == target_member.id,
                models.MemberRank.author_user_id.is_(None),
                models.MemberRank.role == "damage",
            )
        )
        self.assertEqual(1234, value)

    async def test_retained_oauth_is_not_a_verified_claim_for_survivor(self):
        social = models.SocialAccount(
            user_id=self.source.id,
            provider="discord",
            username=self.connection.username,
            username_normalized=self.connection.username.lower(),
            provider_user_id=self.connection.provider_user_id,
            is_verified=True,
        )
        self.session.add(social)
        await self.session.flush()
        policy = AuthMergePolicy(surviving_auth_user_id=self.survivor.id)
        await self.apply(await self.preview(policy))
        self.assertEqual(self.donor.id, self.connection.auth_user_id)
        self.assertFalse(social.is_verified)
        self.assertIsNone(social.provider_user_id)
        self.assertEqual(self.survivor.id, self.target.auth_user_id)
        self.assertIsNone(self.source.auth_user_id)

    async def test_parent_rollback_restores_auth_and_oauth_ownership(self):
        donor_id, survivor_id, source_id, target_id, connection_id = (
            self.donor.id,
            self.survivor.id,
            self.source.id,
            self.target.id,
            self.connection.id,
        )
        savepoint = await self.session.begin_nested()
        await self.apply(await self.preview())
        await savepoint.rollback()
        self.assertEqual(
            donor_id, await self.session.scalar(sa.select(models.User.auth_user_id).where(models.User.id == source_id))
        )
        self.assertEqual(
            survivor_id,
            await self.session.scalar(sa.select(models.User.auth_user_id).where(models.User.id == target_id)),
        )
        self.assertEqual(
            donor_id,
            await self.session.scalar(
                sa.select(models.OAuthConnection.auth_user_id).where(models.OAuthConnection.id == connection_id)
            ),
        )
        self.assertEqual(
            donor_id, await self.session.scalar(sa.select(models.AuthUser.id).where(models.AuthUser.id == donor_id))
        )

    async def test_account_flags_and_api_credentials_are_not_transferred(self):
        tag = uuid4().hex
        self.donor.is_superuser = True
        self.donor.is_verified = True
        self.survivor.is_verified = False
        self.session.add(
            models.AuthUser(
                email=f"admin-{tag}@test.invalid",
                username=f"admin-{tag}",
                hashed_password="independent-secret",
                is_superuser=True,
                is_active=True,
            )
        )
        key = models.ApiKey(
            auth_user_id=self.donor.id,
            workspace_id=self.workspace.id,
            public_id=tag,
            secret_hash="api-key-secret",
            name="Not portable",
        )
        self.session.add(key)
        await self.session.flush()
        self.session.add(models.ApiKeyScope(api_key_id=key.id, scope="workspace.read"))
        await self.session.flush()
        email, username = self.survivor.email, self.survivor.username
        preview = await self.preview()
        self.assertTrue(preview.permission_changes)
        self.assertNotIn("api-key-secret", preview.model_dump_json())
        key_id = key.id
        result = await self.apply(preview)
        self.assertFalse(self.survivor.is_superuser)
        self.assertFalse(self.survivor.is_verified)
        self.assertEqual((email, username), (self.survivor.email, self.survivor.username))
        self.assertIsNone(await self.session.scalar(sa.select(models.ApiKey.id).where(models.ApiKey.id == key_id)))
        self.assertIsNone(
            await self.session.scalar(
                sa.select(models.ApiKeyScope.scope).where(models.ApiKeyScope.api_key_id == key_id)
            )
        )
        self.assertEqual({self.donor.id, self.survivor.id}, set(result.affected_auth_user_ids))

    async def test_non_fk_inbox_and_mute_ownership_are_preserved(self):
        notification = models.Notification(
            audience="user", recipient_auth_user_id=self.donor.id, kind="merge-test", payload_json={}
        )
        self.session.add(notification)
        await self.session.flush()
        self.session.add_all(
            [
                models.NotificationRead(auth_user_id=self.donor.id, notification_id=notification.id),
                models.ChatMute(
                    room_kind="draft",
                    room_ref_id=123456,
                    auth_user_id=self.donor.id,
                    muted_until=None,
                    reason="Restriction",
                    created_by_auth_user_id=self.donor.id,
                ),
                models.ChatMute(
                    room_kind="draft",
                    room_ref_id=123456,
                    auth_user_id=self.survivor.id,
                    muted_until=datetime.now(UTC) + timedelta(hours=1),
                    reason="Restriction",
                    created_by_auth_user_id=self.survivor.id,
                ),
            ]
        )
        await self.session.flush()
        preview = await self.preview()
        self.assertEqual([], preview.data_conflicts)
        await self.apply(preview)
        recipient = await self.session.scalar(
            sa.select(models.Notification.recipient_auth_user_id).where(models.Notification.id == notification.id)
        )
        self.assertEqual(self.survivor.id, recipient)
        marker = await self.session.scalar(
            sa.select(models.NotificationRead.auth_user_id).where(
                models.NotificationRead.notification_id == notification.id
            )
        )
        self.assertEqual(self.survivor.id, marker)
        mute = (
            (
                await self.session.execute(
                    sa.select(models.ChatMute.__table__).where(
                        models.ChatMute.auth_user_id == self.survivor.id, models.ChatMute.room_ref_id == 123456
                    )
                )
            )
            .mappings()
            .one()
        )
        self.assertIsNone(mute["muted_until"])
        self.assertEqual("Restriction", mute["reason"])

    async def test_invalid_oauth_destination_is_not_a_second_account_claim(self):
        invalid = self.policy().model_copy(
            update={
                "oauth_destinations": [
                    AuthMergeOAuthDestination(connection_id=self.connection.id, auth_user_id=2147483647)
                ]
            }
        )
        preview = await self.preview(invalid)
        self.assertTrue(preview.issues)
        with self.assertRaises(BaseAPIException):
            await self.apply(preview)
        self.assertEqual(self.donor.id, self.connection.auth_user_id)
        self.assertEqual(self.donor.id, self.source.auth_user_id)

    async def test_roster_shape_collision_selects_a_real_document_not_a_synthetic_union(self):
        self.session.add_all(
            [
                models.UserBalancerConfig(
                    user_id=self.donor.id, role_slots_json={"tank": 1, "damage": 2}, config_json={"incoming_setting": 1}
                ),
                models.UserBalancerConfig(
                    user_id=self.survivor.id, role_slots_json={"support": 2}, config_json={"existing_setting": 2}
                ),
            ]
        )
        await self.session.flush()
        preview = await self.preview()
        conflict = next(row for row in preview.data_conflicts if row.key.endswith("/role_slots_json"))
        self.assertEqual({"tank": 1, "damage": 2}, conflict.source_value)
        self.assertEqual({"support": 2}, conflict.target_value)
        await self.apply(await self.preview(self.policy(conflict_choices={conflict.key: "source"})))
        row = (
            (
                await self.session.execute(
                    sa.select(models.UserBalancerConfig.__table__).where(
                        models.UserBalancerConfig.user_id == self.survivor.id
                    )
                )
            )
            .mappings()
            .one()
        )
        self.assertEqual({"tank": 1, "damage": 2}, row["role_slots_json"])
        self.assertEqual({"incoming_setting": 1, "existing_setting": 2}, row["config_json"])

    async def test_multi_row_rank_collision_ids_do_not_change_with_resolution(self):
        source_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.source.id)
        target_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.target.id)
        self.session.add_all([source_member, target_member])
        await self.session.flush()
        for author, subject, rank in (
            (self.survivor.id, target_member.id, 100),
            (self.survivor.id, source_member.id, 200),
            (self.donor.id, target_member.id, 300),
            (self.donor.id, source_member.id, 200),
        ):
            self.session.add(
                models.MemberRank(
                    workspace_id=self.workspace.id,
                    workspace_member_id=subject,
                    author_user_id=author,
                    role="damage",
                    rank_value=rank,
                )
            )
        await self.session.flush()
        preview = await self.preview()
        choices = {
            conflict.key: "source" if conflict.source_value == 200 else "target" for conflict in preview.data_conflicts
        }
        resolved = await self.preview(self.policy(conflict_choices=choices))
        self.assertEqual(
            {conflict.key for conflict in preview.data_conflicts},
            {conflict.key for conflict in resolved.data_conflicts},
        )
        self.assertEqual([], resolved.issues)
        await self.apply(resolved)
        value = await self.session.scalar(
            sa.select(models.MemberRank.rank_value).where(
                models.MemberRank.author_user_id == self.survivor.id,
                models.MemberRank.workspace_member_id == target_member.id,
                models.MemberRank.role == "damage",
            )
        )
        self.assertEqual(200, value)

    async def test_default_plan_is_none_only_for_two_authless_profiles(self):
        default = await preview_auth_merge(self.session, self.source, self.target, None)
        self.assertEqual(self.survivor.id, default.policy.surviving_auth_user_id)
        self.assertEqual("keep", default.policy.other_account_action)
        self.target.auth_user_id = None
        await self.session.flush()
        default = await preview_auth_merge(self.session, self.source, self.target, None)
        self.assertEqual(self.donor.id, default.policy.surviving_auth_user_id)
        self.source.auth_user_id = None
        await self.session.flush()
        self.assertIsNone(await preview_auth_merge(self.session, self.source, self.target, None))

    async def test_loaded_members_remain_usable_after_display_name_resolution(self):
        source_member = models.WorkspaceMember(
            workspace_id=self.workspace.id, player_id=self.source.id, display_name="Incoming nickname"
        )
        target_member = models.WorkspaceMember(
            workspace_id=self.workspace.id, player_id=self.target.id, display_name="Existing nickname"
        )
        self.session.add_all([source_member, target_member])
        await self.session.flush()
        preview = await self.preview()
        conflict = next(row for row in preview.data_conflicts if row.resource == "workspace_member")
        await self.apply(await self.preview(self.policy(conflict_choices={conflict.key: "source"})))
        self.assertEqual(self.workspace.id, source_member.workspace_id)
        self.assertEqual(self.source.id, source_member.player_id)
        self.assertEqual("Incoming nickname", target_member.display_name)

    async def test_policy_choices_cannot_erase_a_governance_deny_to_save_last_owner(self):
        role = models.Role(name="owner", workspace_id=self.workspace.id)
        permission = models.Permission(name=f"merge-governance-{uuid4().hex}", resource="role", action="update")
        self.session.add_all([role, permission])
        await self.session.flush()
        grants = models.AuthUser.__table__.metadata.tables["auth.user_roles"]
        await self.session.execute(sa.insert(grants).values(user_id=self.donor.id, role_id=role.id))
        self.session.add(
            models.UserPermissionDeny(
                user_id=self.survivor.id,
                permission_id=permission.id,
                workspace_id=self.workspace.id,
                reason="Governance restricted",
            )
        )
        await self.session.flush()
        preview = await self.preview()
        self.assertTrue(preview.issues)
        with self.assertRaises(BaseAPIException):
            await self.apply(preview)
        self.assertEqual(self.donor.id, self.source.auth_user_id)

    async def test_transferred_deny_cannot_disable_survivors_existing_workspace_ownership(self):
        owner = models.Role(name="owner", workspace_id=self.workspace.id)
        permission = models.Permission(
            name=f"merge-owner-deny-{uuid4().hex}", resource="workspace_member", action="update"
        )
        self.session.add_all([owner, permission])
        await self.session.flush()
        grants = models.AuthUser.__table__.metadata.tables["auth.user_roles"]
        await self.session.execute(sa.insert(grants).values(user_id=self.survivor.id, role_id=owner.id))
        self.workspace.owner_id = self.survivor.id
        self.session.add(
            models.UserPermissionDeny(
                user_id=self.donor.id,
                permission_id=permission.id,
                workspace_id=self.workspace.id,
                reason="Membership administration restricted",
            )
        )
        await self.session.flush()
        preview = await self.preview()
        self.assertTrue(preview.issues)
        with self.assertRaises(BaseAPIException):
            await self.apply(preview)
        self.assertEqual(self.donor.id, self.source.auth_user_id)

    async def test_kept_account_oauth_move_requires_permission_review_and_preserves_both_accounts(self):
        owner = models.Role(name="owner", workspace_id=self.workspace.id)
        member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.source.id)
        connection = models.OAuthConnection(
            auth_user_id=self.survivor.id,
            provider="discord",
            provider_user_id=uuid4().hex,
            username="existing-login",
        )
        self.session.add_all([owner, member, connection])
        await self.session.flush()
        grants = models.AuthUser.__table__.metadata.tables["auth.user_roles"]
        await self.session.execute(sa.insert(grants).values(user_id=self.donor.id, role_id=owner.id))
        policy = AuthMergePolicy(
            surviving_auth_user_id=self.donor.id,
            other_account_action="keep",
            oauth_destinations=[AuthMergeOAuthDestination(connection_id=connection.id, auth_user_id=self.donor.id)],
        )
        preview = await self.preview(policy)
        self.assertEqual([], preview.issues)
        self.assertTrue(preview.permission_changes)
        with self.assertRaises(BaseAPIException):
            await self.apply(preview, confirm_permission_changes=False)
        self.assertEqual(self.survivor.id, connection.auth_user_id)
        await self.apply(preview)
        self.assertEqual(self.donor.id, self.target.auth_user_id)
        self.assertIsNone(self.source.auth_user_id)
        self.assertEqual(self.donor.id, connection.auth_user_id)
        self.assertEqual(
            "survivor-secret",
            await self.session.scalar(
                sa.select(models.AuthUser.hashed_password).where(models.AuthUser.id == self.survivor.id)
            ),
        )

    async def test_source_auth_survivor_keeps_incoming_rank_choice_independent_of_row_order(self):
        source_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.source.id)
        target_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.target.id)
        self.session.add_all([source_member, target_member])
        await self.session.flush()
        incoming = models.MemberRank(
            workspace_id=self.workspace.id,
            workspace_member_id=target_member.id,
            author_user_id=self.survivor.id,
            role="damage",
            rank_value=1111,
        )
        self.session.add(incoming)
        await self.session.flush()
        existing = models.MemberRank(
            workspace_id=self.workspace.id,
            workspace_member_id=source_member.id,
            author_user_id=self.donor.id,
            role="damage",
            rank_value=2222,
        )
        self.session.add(existing)
        await self.session.flush()
        policy = AuthMergePolicy(surviving_auth_user_id=self.donor.id, other_account_action="delete")
        preview = await self.preview(policy)
        self.assertEqual([], preview.issues)
        conflict = next(row for row in preview.data_conflicts if row.resource == "balancer.member_rank")
        self.assertEqual(1111, conflict.source_value)
        self.assertEqual(2222, conflict.target_value)
        policy.conflict_choices[conflict.key] = "source"
        await self.apply(await self.preview(policy))
        ranks = (
            await self.session.execute(
                sa.select(
                    models.MemberRank.rank_value,
                    models.MemberRank.author_user_id,
                    models.MemberRank.workspace_member_id,
                ).where(models.MemberRank.workspace_id == self.workspace.id)
            )
        ).all()
        self.assertEqual([(1111, self.donor.id, target_member.id)], ranks)
        self.assertEqual(self.donor.id, self.target.auth_user_id)
