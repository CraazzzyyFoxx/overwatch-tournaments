"""Auth confirmation and identity outages must not partially merge player data."""

import asyncio
from unittest import IsolatedAsyncioTestCase
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import BaseAPIException
from shared.schemas.user_merge_auth import AuthMergeOAuthDestination, AuthMergePolicy
from shared.testing.db import create_test_async_engine
from src.schemas.admin.user_merge import UserMergeExecuteRequest, UserMergePreviewRequest
from src.services.admin.user_merge import UserMergeService


class UserMergeAuthTransactionTests(IsolatedAsyncioTestCase):
    loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self):
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(
            bind=self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        self.merges = UserMergeService()
        tag = uuid4().hex
        donor = models.AuthUser(
            email=f"merge-donor-{tag}@test.invalid", username=f"donor-{tag}", hashed_password="donor"
        )
        survivor = models.AuthUser(
            email=f"merge-survivor-{tag}@test.invalid", username=f"survivor-{tag}", hashed_password="survivor"
        )
        self.session.add_all([donor, survivor])
        await self.session.flush()
        source = models.User(name=f"source-{tag}", auth_user_id=donor.id)
        target = models.User(name=f"target-{tag}", auth_user_id=survivor.id)
        workspace = models.Workspace(name="Merge rollback", slug=f"merge-rollback-{tag}", owner_id=donor.id)
        self.session.add_all([source, target, workspace])
        await self.session.flush()
        oauth = models.OAuthConnection(
            auth_user_id=donor.id, provider="discord", provider_user_id=tag, username=tag, access_token="oauth-secret"
        )
        view = models.EncounterSavedView(
            workspace_id=workspace.id, auth_user_id=donor.id, name="Saved", filters_json={"round": 2}
        )
        self.session.add_all([oauth, view])
        await self.session.flush()
        self.ids = {
            "donor": donor.id,
            "survivor": survivor.id,
            "source": source.id,
            "target": target.id,
            "workspace": workspace.id,
            "oauth": oauth.id,
            "view": view.id,
        }
        await self.session.commit()
        self.policy = AuthMergePolicy(
            surviving_auth_user_id=self.ids["survivor"],
            other_account_action="delete",
            oauth_destinations=[
                AuthMergeOAuthDestination(connection_id=self.ids["oauth"], auth_user_id=self.ids["survivor"])
            ],
        )

    async def asyncTearDown(self):
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    async def request(self, **confirmations):
        preview = await self.merges.preview_merge(
            self.session,
            UserMergePreviewRequest(
                source_user_id=self.ids["source"], target_user_id=self.ids["target"], auth_policy=self.policy
            ),
        )
        self.assertFalse(preview.conflicts.has_auth_conflict)
        self.assertEqual([], preview.auth_merge.issues)
        return UserMergeExecuteRequest(
            source_user_id=self.ids["source"],
            target_user_id=self.ids["target"],
            preview_fingerprint=preview.preview_fingerprint,
            auth_policy=preview.auth_merge.policy,
            field_policy={},
            identity_selection={},
            **confirmations,
        )

    async def assert_original_ownership(self):
        players = dict(
            (
                await self.session.execute(
                    sa.select(models.User.id, models.User.auth_user_id).where(
                        models.User.id.in_([self.ids["source"], self.ids["target"]])
                    )
                )
            ).all()
        )
        self.assertEqual({self.ids["source"]: self.ids["donor"], self.ids["target"]: self.ids["survivor"]}, players)
        self.assertEqual(
            self.ids["donor"],
            await self.session.scalar(sa.select(models.AuthUser.id).where(models.AuthUser.id == self.ids["donor"])),
        )
        self.assertEqual(
            self.ids["donor"],
            await self.session.scalar(
                sa.select(models.OAuthConnection.auth_user_id).where(models.OAuthConnection.id == self.ids["oauth"])
            ),
        )
        self.assertEqual(
            self.ids["donor"],
            await self.session.scalar(
                sa.select(models.Workspace.owner_id).where(models.Workspace.id == self.ids["workspace"])
            ),
        )
        self.assertEqual(
            self.ids["donor"],
            await self.session.scalar(
                sa.select(models.EncounterSavedView.auth_user_id).where(
                    models.EncounterSavedView.id == self.ids["view"]
                )
            ),
        )
        self.assertIsNone(
            await self.session.scalar(
                sa.select(models.UserMergeAudit.id).where(models.UserMergeAudit.target_user_id == self.ids["target"])
            )
        )

    async def test_missing_auth_confirmation_preserves_both_players_and_accounts(self):
        request = await self.request(confirm_auth_deletion=True, confirm_permission_changes=True)

        async def unavailable_identity(_result):
            raise RuntimeError("Identity unavailable")

        with self.assertRaises(BaseAPIException) as caught:
            await self.merges.execute_merge(
                self.session, request, operator_auth_user_id=None, auth_finalizer=unavailable_identity
            )
        self.assertEqual(409, caught.exception.status_code)
        await self.assert_original_ownership()

    async def test_identity_outage_rolls_back_player_auth_resources_and_audit(self):
        request = await self.request(
            confirm_auth_changes=True, confirm_auth_deletion=True, confirm_permission_changes=True
        )

        async def unavailable_identity(_result):
            raise RuntimeError("Identity unavailable")

        with self.assertRaisesRegex(RuntimeError, "Identity unavailable"):
            await self.merges.execute_merge(
                self.session, request, operator_auth_user_id=None, auth_finalizer=unavailable_identity
            )
        await self.assert_original_ownership()
