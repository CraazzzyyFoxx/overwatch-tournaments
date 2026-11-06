"""Workspace-level subscription provider configuration.

Minimal admin surface: raw ids typed by hand (role ids, broadcaster id). The Discord
guild id is NOT typed here -- it belongs to the workspace, and the list response
echoes it back read-only.

Three rules carry the weight here:

- **Plaintext codes are never persisted.** The admin types a code, the server keeps
  only its SHA-256, and the read model returns neither the code nor the digest — a
  digest is still brute-forcible offline, so the UI learns only that a code exists,
  at which tier, and until when.
- **Omitting a field keeps what is stored.** The admin cannot see existing codes,
  so a plain save must not wipe them. Passing an explicit list replaces them.
- **The verification method is authoritative over the cache, not just the call.**
  Narrowing it invalidates stored entitlements whose source it no longer accepts —
  see ``shared.services.subscriptions.verification`` for why that is load-bearing.

The workspace requirement lives here too, beside the provider config and under the
same permissions: both answer "what does this workspace demand of a registrant?", and
keeping them together means one file in tournament-service knows the subscription
tables. Unlike a provider config it is replaced wholesale -- a partial merge of an
admission rule would be a silent policy change.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SocialProvider
from shared.repository import (
    SubscriptionProviderConfigRepository,
    WorkspaceRepository,
    WorkspaceSubscriptionRequirementRepository,
)
from shared.services.registration_window import tournament_sign_up_open_clause
from shared.services.subscriptions import parse_verification_method
from shared.services.subscriptions.challenge_code import hash_code
from src.schemas.registration import (
    ChallengeCodeRead,
    RoleTierRead,
    SubscriptionProviderConfigListResponse,
    SubscriptionProviderConfigRead,
    SubscriptionProviderConfigUpsert,
    WorkspaceSubscriptionRequirementRead,
    WorkspaceSubscriptionRequirementUpsert,
)

__all__ = (
    "CONFIGURABLE_PROVIDERS",
    "DEFAULT_REQUIREMENT_NAME",
    "SubscriptionConfigService",
    "build_config_json",
    "serialize_provider_config",
    "subscription_config_service",
)

CONFIGURABLE_PROVIDERS = (SocialProvider.BOOSTY, SocialProvider.TWITCH)
DEFAULT_REQUIREMENT_NAME = "default"


def build_config_json(body: SubscriptionProviderConfigUpsert, *, existing: dict[str, Any]) -> dict[str, Any]:
    """Merge an upsert over the stored blob.

    ``None`` means "not supplied, keep what is there"; an explicit value (including
    an empty string or empty list) replaces it.
    """
    config = dict(existing)

    if body.broadcaster_id is not None:
        config["broadcaster_id"] = body.broadcaster_id.strip()
    if body.broadcaster_login is not None:
        config["broadcaster_login"] = body.broadcaster_login.strip()
    if body.verification_method is not None:
        config["verification_method"] = body.verification_method

    if body.role_tiers is not None:
        config["role_tiers"] = [
            {
                # Kept as a string: a Discord snowflake exceeds 2**53.
                "role_id": row.role_id.strip(),
                "tier_rank": row.tier_rank,
                "tier_label": row.tier_label,
            }
            for row in body.role_tiers
        ]

    if body.codes is not None:
        config["codes"] = [
            {
                # Plaintext is hashed here and dropped; only the digest is stored.
                "code_sha256": row.code_sha256 or hash_code(row.code),
                "tier_rank": row.tier_rank,
                "tier_label": row.tier_label,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
            for row in body.codes
        ]

    return config


def serialize_provider_config(row: Any) -> SubscriptionProviderConfigRead:
    config = row.config_json or {}
    return SubscriptionProviderConfigRead(
        provider=row.provider,
        enabled=bool(row.enabled),
        role_tiers=[
            RoleTierRead(
                role_id=str(entry.get("role_id") or ""),
                tier_rank=int(entry.get("tier_rank") or 1),
                tier_label=str(entry.get("tier_label") or ""),
            )
            for entry in config.get("role_tiers") or []
            if entry.get("role_id")
        ],
        broadcaster_id=config.get("broadcaster_id") or None,
        broadcaster_login=config.get("broadcaster_login") or None,
        # Redacted on purpose: neither the code nor its digest leaves the server.
        codes=[
            ChallengeCodeRead(
                tier_rank=int(entry.get("tier_rank") or 1),
                tier_label=str(entry.get("tier_label") or ""),
                expires_at=entry.get("expires_at"),
            )
            for entry in config.get("codes") or []
        ],
        # Through the runtime parser, not the raw blob: a stored value the code does
        # not recognise must read back as `any`, matching what the gate will do.
        verification_method=parse_verification_method(config),
    )


class SubscriptionConfigService:
    def __init__(
        self,
        *,
        provider_repo: SubscriptionProviderConfigRepository = SubscriptionProviderConfigRepository(),
        requirement_repo: WorkspaceSubscriptionRequirementRepository = WorkspaceSubscriptionRequirementRepository(),
        workspace_repo: WorkspaceRepository = WorkspaceRepository(),
    ) -> None:
        self.provider_repo = provider_repo
        self.requirement_repo = requirement_repo
        self.workspace_repo = workspace_repo

    async def _ensure_workspace_exists(self, session: AsyncSession, workspace_id: int) -> None:
        """404 before an upsert, which would otherwise surface a missing workspace as an FK 500."""
        if not await self.workspace_repo.exists(session, id=workspace_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    async def list_provider_configs(
        self,
        session: AsyncSession,
        workspace_id: int,
    ) -> SubscriptionProviderConfigListResponse:
        """Every configurable provider, present or not, plus the workspace's guild.

        Providers with no row are returned disabled and empty, so the admin UI renders
        one card per provider without inventing placeholder rows in the database.

        The guild is response-level rather than per-provider because it lives on the
        workspace, not in any provider blob: the card renders it read-only and the
        workspace settings form is the only place that writes it.
        """
        rows = await self.provider_repo.list_for_workspace(session, workspace_id)
        by_provider = {row.provider: row for row in rows}
        configs = [
            serialize_provider_config(by_provider[provider])
            if provider in by_provider
            else SubscriptionProviderConfigRead(provider=provider, enabled=False)
            for provider in CONFIGURABLE_PROVIDERS
        ]
        # A one-column projection, not a row read: `WorkspaceRepository.get` would
        # load and identity-map the whole workspace to answer one nullable string.
        discord_guild_id = await session.scalar(
            sa.select(models.Workspace.discord_guild_id).where(models.Workspace.id == workspace_id)
        )
        return SubscriptionProviderConfigListResponse(configs=configs, discord_guild_id=discord_guild_id or None)

    async def upsert_provider_config(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        body: SubscriptionProviderConfigUpsert,
    ) -> SubscriptionProviderConfigRead:
        """Create or update one provider's config. Commits internally."""
        await self._ensure_workspace_exists(session, workspace_id)
        existing = await self.provider_repo.get_for_provider(
            session,
            workspace_id=workspace_id,
            provider=body.provider,
        )
        config_json = build_config_json(body, existing=(existing.config_json or {}) if existing else {})

        await self.provider_repo.upsert(
            session,
            workspace_id=workspace_id,
            provider=body.provider,
            enabled=body.enabled,
            config_json=config_json,
        )
        await session.commit()

        # `populate_existing` is load-bearing: the INSERT ... ON CONFLICT above changes
        # the row behind the ORM's back, so a plain SELECT would be served from the
        # identity map and return the PRE-upsert `config_json` -- an explicit
        # `codes: []` would read back uncleared.
        row = await self.provider_repo.get_for_provider(
            session,
            workspace_id=workspace_id,
            provider=body.provider,
            populate_existing=True,
        )
        return serialize_provider_config(row)

    async def load_workspace_requirement_blob(self, session: AsyncSession, workspace_id: int) -> dict[str, Any]:
        """The workspace's default rule as a raw blob, or ``{}`` when it has none.

        One scalar read, used both by the admin endpoint and by the registration-form read
        projection -- which carries the rule so the public check-in dialog does not have to
        learn about a second table.
        """
        return await self.requirement_repo.get_default_blob(session, workspace_id)

    async def count_enforcing_tournaments(self, session: AsyncSession, workspace_id: int) -> int:
        """Live tournaments this workspace's rule would gate.

        Applies the collector's TOURNAMENT-side predicate only
        (``find_tournaments_requiring_subscriptions``): open, unfinished, toggle on. A
        finished tournament still carrying the toggle is not "gated" in any sense the
        organizer cares about, and counting it would overstate the blast radius the admin
        screen is there to report honestly.

        It deliberately omits the rest of what the collector sweeps on -- the inner join to
        ``subscriptions.requirement ... is_default`` and the drop of targets whose blob
        parses empty -- so this counts what a rule WOULD gate, not only what one currently
        does. That is the question the admin card asks ("how many tournaments will the rule
        you are about to save gate?"), and adding the join would read 0 in the one state
        where the blast radius matters most: toggles on, no rule row yet, which is exactly
        where an admin stands when they first open this card.
        """
        return (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(models.Tournament)
                .where(
                    models.Tournament.workspace_id == workspace_id,
                    models.Tournament.is_finished.is_(False),
                    # Some registration node accepts sign-ups AND requires the subscription: the node's status and
                    # window decide openness, its config the toggle.
                    tournament_sign_up_open_clause(
                        None, models.FlowNode.config["require_subscription"].as_boolean().is_(True)
                    ),
                )
            )
        ) or 0

    async def get_workspace_requirement(
        self,
        session: AsyncSession,
        workspace_id: int,
    ) -> WorkspaceSubscriptionRequirementRead:
        return WorkspaceSubscriptionRequirementRead(
            requirement=await self.load_workspace_requirement_blob(session, workspace_id),
            enforcing_tournaments=await self.count_enforcing_tournaments(session, workspace_id),
        )

    async def upsert_workspace_requirement(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        body: WorkspaceSubscriptionRequirementUpsert,
    ) -> WorkspaceSubscriptionRequirementRead:
        """Replace the workspace's default rule. Commits internally.

        Conflicts on ``(workspace_id, name)`` rather than on the partial "one default per
        workspace" index: the named constraint is the stable target, and ``name`` is
        always ``'default'``.
        """
        await self._ensure_workspace_exists(session, workspace_id)
        await self.requirement_repo.upsert_default(
            session,
            workspace_id=workspace_id,
            name=DEFAULT_REQUIREMENT_NAME,
            requirement_json=body.requirement,
        )
        await session.commit()
        # Read back rather than echoing the request: the INSERT ... ON CONFLICT wrote behind
        # the ORM's back, and the caller should see what the gates will now read.
        return await self.get_workspace_requirement(session, workspace_id)


subscription_config_service = SubscriptionConfigService()
