"""Orchestration for OverFast rank collection: state bookkeeping + snapshot
writes. RankStateService talks to the repositories in
``shared.repository.ranks`` for every raw DB write (see that module for the
exact SQL shapes preserved from this file's earlier, pre-repository form).

Transaction-neutral — methods mutate/flush the session via the repositories;
the caller commits.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import enums
from shared.core.social import SocialProvider, normalize_social_handle
from shared.core.tournament_state import FINISHED_STATUSES
from shared.repository.ranks import (
    BattleTagRankStateRepository,
    RankFetchLogRepository,
    RankSnapshotRepository,
    workspace_account_ids,
)
from shared.repository.ranks import jittered_interval as _jittered_interval
from shared.schemas.settings import RankCollectionConfig
from src import models
from src.domain.overwatch_rank import RankFetchResult, battle_tag_to_slug

from . import mapping
from .client import INVALID_BATTLE_TAG_ERROR

# Multipliers applied to the base interval for non-error terminal states so we
# poll quiet accounts less often.
PRIVATE_INTERVAL_FACTOR = 4
NOT_FOUND_INTERVAL_FACTOR = 8
MAX_BACKOFF_SECONDS = 6 * 60 * 60

# Tournament statuses whose registrations we do NOT backfill — finished events
# shouldn't keep the collector polling their players forever.
INACTIVE_TOURNAMENT_STATUSES = tuple(sorted(status.value for status in FINISHED_STATUSES))


def _now() -> datetime:
    return datetime.now(UTC)


class RankStateService:
    """Write/orchestration half of OverFast rank collection: get-or-create +
    priority bumps, tier seeding/promotion/demotion, due-tag claiming, fetch
    result/failure recording, and admin recovery (reenable/defer).
    """

    def __init__(
        self,
        *,
        repo: BattleTagRankStateRepository = BattleTagRankStateRepository(),
        snapshot_repo: RankSnapshotRepository = RankSnapshotRepository(),
        log_repo: RankFetchLogRepository = RankFetchLogRepository(),
    ) -> None:
        self.repo = repo
        self.snapshot_repo = snapshot_repo
        self.log_repo = log_repo

    async def log_fetch(
        self,
        session: AsyncSession,
        *,
        social_account_id: int | None,
        battle_tag: str,
        status: str,
        source: str,
        error: str | None = None,
        snapshots_written: int = 0,
    ) -> None:
        """Append a worker fetch attempt to the task-history log (caller commits)."""
        await self.log_repo.create(
            session,
            models.RankFetchLog(
                social_account_id=social_account_id,
                battle_tag=battle_tag,
                status=str(status),
                source=source,
                error=error[:2000] if error else None,
                snapshots_written=snapshots_written,
            ),
        )

    async def ensure_state(
        self,
        session: AsyncSession,
        social_account_id: int,
        battle_tag: str,
        *,
        priority_tier: int = 0,
    ) -> models.BattleTagRankState:
        """Get-or-create the collection state for a battle tag, bumping priority."""
        state = await self.repo.get_by_social_account_id(session, social_account_id)
        if state is None:
            return await self.repo.create_for_tag(
                session,
                social_account_id=social_account_id,
                battle_tag=battle_tag,
                player_id_slug=battle_tag_to_slug(battle_tag),
                priority_tier=priority_tier,
            )
        return await self.repo.bump_priority(session, state, priority_tier)

    async def resolve_user_registration_targets(
        self,
        session: AsyncSession,
        user_id: int,
        registered_normalized: set[str],
        extra_accounts: int,
    ) -> list[tuple[int, str]]:
        """A user's collection pool: their registered tags + up to N extra accounts.

        ``registered_normalized`` is the set of normalized battlenet handles the
        player entered (main + smurfs). Every matching ``social_account`` is
        included; then up to ``extra_accounts`` of their *other* battlenet
        accounts (lowest id first, deterministic).
        """
        rows = (
            await session.execute(
                sa.select(
                    models.SocialAccount.id,
                    models.SocialAccount.username,
                    models.SocialAccount.username_normalized,
                )
                .where(
                    models.SocialAccount.user_id == user_id,
                    models.SocialAccount.provider == SocialProvider.BATTLENET,
                )
                .order_by(models.SocialAccount.id.asc())
            )
        ).all()
        targets: list[tuple[int, str]] = []
        extras = 0
        for account_id, username, normalized in rows:
            if normalized and normalized in registered_normalized:
                targets.append((account_id, username))
            elif extras < extra_accounts:
                targets.append((account_id, username))
                extras += 1
        return targets

    async def resolve_registration_targets(
        self,
        session: AsyncSession,
        *,
        registration_id: int | None,
        fallback_battle_tag: str | None,
        user_id: int,
        extra_accounts: int,
    ) -> list[tuple[int, str]]:
        """Collection pool for one approved registration (registered tags + N extra)."""
        registered_normalized: set[str] = set()
        registration = (
            await session.scalar(
                sa.select(models.BalancerRegistration).where(models.BalancerRegistration.id == registration_id)
            )
            if registration_id is not None
            else None
        )
        if registration is not None:
            if registration.battle_tag:
                registered_normalized.add(normalize_social_handle(SocialProvider.BATTLENET, registration.battle_tag))
            for smurf in registration.smurf_tags_json or []:
                if smurf:
                    registered_normalized.add(normalize_social_handle(SocialProvider.BATTLENET, str(smurf)))
        elif fallback_battle_tag:
            registered_normalized.add(normalize_social_handle(SocialProvider.BATTLENET, fallback_battle_tag))

        return await self.resolve_user_registration_targets(session, user_id, registered_normalized, extra_accounts)

    async def seed_states_for_all_battle_tags(self, session: AsyncSession, *, interval_seconds: int) -> int:
        """Insert a (tier 0) state row for every battle tag that lacks one.

        New rows are seeded with a jittered ``next_eligible_at`` spread across
        ``[now, now+interval_seconds]`` so the first collection cycle is even
        rather than a thundering herd.
        """
        return await self.repo.bulk_seed_missing(session, interval_seconds=interval_seconds)

    async def _registration_collection_targets(self, session: AsyncSession, extra_accounts: int) -> set[int]:
        """``social_account_id`` set to collect under ``registrations_only``.

        For active-tournament registrations: the tags the player *entered* (main
        + smurfs), matched to battlenet ``social_account`` rows, plus up to
        ``extra_accounts`` of each registrant's *other* battle.net accounts.
        Tournaments that are ``completed``/``archived`` are excluded.
        """
        reg = models.BalancerRegistration
        tournament = models.Tournament
        acc = models.SocialAccount

        # Registrations are anchored on workspace_member (dbarch02 dropped
        # user_id); LEFT JOIN so member-less rows still contribute their entered
        # battle tags (their player_id resolves to None, exactly like the old
        # NULL user_id).
        member = models.WorkspaceMember
        rows = (
            await session.execute(
                sa.select(member.player_id, reg.battle_tag, reg.smurf_tags_json)
                .select_from(reg)
                .join(tournament, tournament.id == reg.tournament_id)
                .outerjoin(member, member.id == reg.workspace_member_id)
                .where(
                    reg.deleted_at.is_(None),
                    tournament.status.notin_(INACTIVE_TOURNAMENT_STATUSES),
                )
            )
        ).all()

        registered_normalized: set[str] = set()
        user_ids: set[int] = set()
        for user_id, battle_tag, smurfs in rows:
            if user_id is not None:
                user_ids.add(user_id)
            if battle_tag:
                registered_normalized.add(normalize_social_handle(SocialProvider.BATTLENET, battle_tag))
            for smurf in smurfs or []:
                if smurf:
                    registered_normalized.add(normalize_social_handle(SocialProvider.BATTLENET, str(smurf)))

        target_ids: set[int] = set()

        # Tags explicitly registered (matches by normalized handle; covers regs without a user).
        if registered_normalized:
            ids = (
                await session.scalars(
                    sa.select(acc.id).where(
                        acc.provider == SocialProvider.BATTLENET,
                        acc.username_normalized.in_(registered_normalized),
                    )
                )
            ).all()
            target_ids.update(ids)

        # Per registrant user: registered accounts + up to N extra accounts (lowest id first).
        if user_ids:
            user_rows = (
                await session.execute(
                    sa.select(acc.user_id, acc.id, acc.username_normalized)
                    .where(
                        acc.user_id.in_(user_ids),
                        acc.provider == SocialProvider.BATTLENET,
                    )
                    .order_by(acc.user_id.asc(), acc.id.asc())
                )
            ).all()
            extras_per_user: dict[int, int] = {}
            for uid, account_id, normalized in user_rows:
                if normalized and normalized in registered_normalized:
                    target_ids.add(account_id)
                elif extras_per_user.get(uid, 0) < extra_accounts:
                    target_ids.add(account_id)
                    extras_per_user[uid] = extras_per_user.get(uid, 0) + 1

        return target_ids

    async def seed_states_from_registrations(
        self, session: AsyncSession, *, interval_seconds: int, extra_accounts: int = 0
    ) -> int:
        """Sync tier-1 state to the registration collection pool (registrations_only).

        Keeps ``priority_tier == 1`` equal to the registered tags (main + smurfs)
        of active-tournament registrations plus up to ``extra_accounts`` other
        accounts per registrant:

        - inserts a tier-1 state row for newly-targeted tags,
        - promotes an existing tier-0 row back to tier 1 when its tag enters the pool,
        - demotes tier-1 rows that leave the pool (e.g. tournament completed) to tier 0.

        Tier 2 (manual triggers / approval hook) is never touched. Returns the
        number of new state rows inserted.
        """
        target_ids = await self._registration_collection_targets(session, extra_accounts)

        # Demote tier-1 rows that are no longer in the registration pool.
        await self.repo.demote_tier1_not_in(session, target_ids)

        if not target_ids:
            return 0

        # Promote existing tier-0 rows that are now in the pool.
        await self.repo.promote_tier0_in(session, target_ids)

        # Insert tier-1 rows for pool accounts that have no state row yet, spread
        # across the interval (see ``seed_states_for_all_battle_tags``).
        return await self.repo.bulk_seed_missing(
            session, interval_seconds=interval_seconds, target_ids=target_ids, priority_tier=1
        )

    async def count_in_scope(self, session: AsyncSession, *, scope: str) -> int:
        """Count non-disabled tags eligible for collection under ``scope``.

        Sizes the self-pacing batch off the *whole* in-scope population (not the
        currently-due subset, which would self-amplify into bursts during a backlog).
        """
        state = models.BattleTagRankState
        query = (
            sa.select(sa.func.count())
            .select_from(state)
            .where(state.status != enums.RankCollectionStatus.disabled.value)
        )
        if scope == "registrations_only":
            query = query.where(state.priority_tier > 0)
        return int(await session.scalar(query) or 0)

    async def last_success_at(self, session: AsyncSession) -> datetime | None:
        """Newest successful capture across every tag, or ``None`` if there is none.

        One aggregate, deliberately separate from :meth:`collection_stats`: the
        scheduler exports it as a gauge on every tick and must not pay for the
        whole dashboard to do it.
        """
        state = models.BattleTagRankState
        return await session.scalar(sa.select(sa.func.max(state.last_success_at)))

    async def collection_stats(self, session: AsyncSession, *, workspace_id: int | None = None) -> dict:
        """Aggregate collection health (DB layer only; caller adds config).

        Mirrors the manual incident-diagnostic queries: state status/tier mix,
        whole population size, distinct-account snapshot coverage over
        24h/7d, the global last successful capture, and the last-24h
        ``fetch_log`` outcome mix.

        ``workspace_id`` narrows every aggregate to the battle tags of that
        workspace's players (the caller's authorization scope — see ``rpc/rank.py``).
        """
        state = models.BattleTagRankState
        snap = models.UserRankSnapshot
        log = models.RankFetchLog
        now = _now()
        accounts = workspace_account_ids(workspace_id) if workspace_id is not None else None

        def _scoped(stmt: sa.Select, column: sa.ColumnElement) -> sa.Select:
            return stmt if accounts is None else stmt.where(column.in_(accounts))

        by_status = {
            str(status): int(count)
            for status, count in (
                await session.execute(
                    _scoped(sa.select(state.status, sa.func.count()), state.social_account_id).group_by(state.status)
                )
            ).all()
        }
        by_tier = {
            int(tier): int(count)
            for tier, count in (
                await session.execute(
                    _scoped(sa.select(state.priority_tier, sa.func.count()), state.social_account_id).group_by(
                        state.priority_tier
                    )
                )
            ).all()
        }
        total = int(
            await session.scalar(_scoped(sa.select(sa.func.count()).select_from(state), state.social_account_id)) or 0
        )
        never_checked = int(
            await session.scalar(
                _scoped(sa.select(sa.func.count()).select_from(state), state.social_account_id).where(
                    state.last_checked_at.is_(None)
                )
            )
            or 0
        )
        last_success_at = await session.scalar(
            _scoped(sa.select(sa.func.max(state.last_success_at)), state.social_account_id)
        )

        async def _coverage(delta: timedelta) -> int:
            return int(
                await session.scalar(
                    _scoped(
                        sa.select(sa.func.count(sa.distinct(snap.social_account_id))), snap.social_account_id
                    ).where(snap.captured_at > now - delta)
                )
                or 0
            )

        fetch_24h = {
            str(status): int(count)
            for status, count in (
                await session.execute(
                    _scoped(sa.select(log.status, sa.func.count()), log.social_account_id)
                    .where(log.created_at > now - timedelta(hours=24))
                    .group_by(log.status)
                )
            ).all()
        }

        # Tags the client refuses before any HTTP call (``Name#1234`` shape broken —
        # e.g. a mangled handle stored at registration). They never reach OverFast,
        # so they never recover on their own and need an operator, not a retry.
        invalid_battle_tags_24h = int(
            await session.scalar(
                _scoped(sa.select(sa.func.count()).select_from(log), log.social_account_id).where(
                    log.created_at > now - timedelta(hours=24),
                    log.error == INVALID_BATTLE_TAG_ERROR,
                )
            )
            or 0
        )

        return {
            "total": total,
            "never_checked": never_checked,
            "by_status": by_status,
            "by_tier": by_tier,
            "last_success_at": last_success_at,
            "coverage_24h": await _coverage(timedelta(hours=24)),
            "coverage_7d": await _coverage(timedelta(days=7)),
            "fetch_24h": fetch_24h,
            "invalid_battle_tags_24h": invalid_battle_tags_24h,
        }

    async def select_and_claim_due(
        self,
        session: AsyncSession,
        *,
        limit: int,
        scope: str,
        interval_seconds: int,
        jitter_fraction: float = 0.0,
        now: datetime | None = None,
    ) -> Sequence[models.BattleTagRankState]:
        """Pick the most-due tags, claim them (push out ``next_eligible_at``), return them.

        See ``BattleTagRankStateRepository.claim_due`` for the exact
        ordering/claim shape; this just resolves the default ``now``.
        """
        now = now or _now()
        return await self.repo.claim_due(
            session,
            limit=limit,
            scope=scope,
            interval_seconds=interval_seconds,
            jitter_fraction=jitter_fraction,
            now=now,
        )

    async def _user_id_for_tag(self, session: AsyncSession, social_account_id: int) -> int | None:
        return await session.scalar(
            sa.select(models.SocialAccount.user_id).where(models.SocialAccount.id == social_account_id)
        )

    async def record_result(
        self,
        session: AsyncSession,
        *,
        social_account_id: int,
        battle_tag: str,
        source: str,
        result: RankFetchResult,
        lookup: mapping.RankLookup,
        mapping_version: str,
        config: RankCollectionConfig,
        now: datetime | None = None,
    ) -> int:
        """Persist a fetch outcome: snapshot rows (on success) + state update.

        Returns the number of snapshot rows written.
        """
        now = now or _now()
        state = await self.ensure_state(session, social_account_id, battle_tag)
        state.last_checked_at = now
        state.last_error = None

        status = result.status
        written = 0

        if status == enums.RankCollectionStatus.ok:
            user_id = await self._user_id_for_tag(session, social_account_id)
            last_snapshot: models.UserRankSnapshot | None = None
            if user_id is not None:
                snapshots = [
                    models.UserRankSnapshot(
                        user_id=user_id,
                        social_account_id=social_account_id,
                        battle_tag=battle_tag,
                        platform=parsed.platform,
                        role=parsed.role,
                        division=parsed.division,
                        tier=parsed.tier,
                        season=parsed.season,
                        rank_value=mapping.map_division_tier_to_rank_value(parsed.division, parsed.tier, lookup),
                        mapping_version=mapping_version,
                        is_ranked=parsed.is_ranked,
                        raw_payload=parsed.raw,
                        captured_at=now,
                        source=source,
                    )
                    for parsed in result.ranks
                ]
                await self.snapshot_repo.create_many(session, snapshots)
                written = len(snapshots)
                last_snapshot = snapshots[-1] if snapshots else None
            state.status = enums.RankCollectionStatus.ok.value
            state.last_success_at = now
            state.consecutive_failures = 0
            if last_snapshot is not None:
                state.last_snapshot_id = last_snapshot.id
            state.next_eligible_at = now + timedelta(
                seconds=_jittered_interval(config.interval_seconds, config.jitter_fraction)
            )
        elif status == enums.RankCollectionStatus.private:
            state.status = enums.RankCollectionStatus.private.value
            state.consecutive_failures = 0
            state.next_eligible_at = now + timedelta(
                seconds=_jittered_interval(
                    config.interval_seconds * PRIVATE_INTERVAL_FACTOR,
                    config.jitter_fraction,
                )
            )
        elif status == enums.RankCollectionStatus.not_found:
            state.status = enums.RankCollectionStatus.not_found.value
            state.consecutive_failures = 0
            state.next_eligible_at = now + timedelta(
                seconds=_jittered_interval(
                    config.interval_seconds * NOT_FOUND_INTERVAL_FACTOR,
                    config.jitter_fraction,
                )
            )
        else:  # error
            return await self.record_failure(
                session,
                social_account_id=social_account_id,
                battle_tag=battle_tag,
                status=enums.RankCollectionStatus.error,
                error=result.error,
                config=config,
                now=now,
            )

        await session.flush()
        return written

    async def record_failure(
        self,
        session: AsyncSession,
        *,
        social_account_id: int,
        battle_tag: str,
        status: enums.RankCollectionStatus,
        error: str | None,
        config: RankCollectionConfig,
        transient: bool = False,
        now: datetime | None = None,
    ) -> int:
        """Apply exponential backoff for a failure; auto-disable only *permanent* ones.

        ``transient=True`` (OverFast 5xx / timeout / 429 — the upstream is at
        fault, not the tag) NEVER auto-disables: it only backs off (capped at
        ``MAX_BACKOFF_SECONDS``) so the tag keeps retrying and recovers on its
        own once OverFast is healthy again. Without this, an upstream outage
        that trips ``max_consecutive_failures`` in a row would permanently
        disable healthy accounts with no recovery path (``select_and_claim_due``
        skips ``disabled`` and nothing re-enables them). Only permanent failures
        (an invalid battle tag that will never resolve) count toward
        auto-disable.
        """
        now = now or _now()
        state = await self.ensure_state(session, social_account_id, battle_tag)
        state.last_checked_at = now
        state.last_error = (error or "")[:2000] or None
        state.consecutive_failures = (state.consecutive_failures or 0) + 1

        if not transient and state.consecutive_failures >= config.max_consecutive_failures:
            state.status = enums.RankCollectionStatus.disabled.value
            state.next_eligible_at = None
        else:
            # Cap the exponent: a transient outage can drive consecutive_failures
            # arbitrarily high (it no longer disables), and 2**big is wasteful — the
            # backoff is clamped to MAX_BACKOFF_SECONDS long before then anyway.
            backoff = min(
                config.backoff_base_seconds * (2 ** min(state.consecutive_failures - 1, 16)),
                MAX_BACKOFF_SECONDS,
            )
            state.status = status.value
            state.next_eligible_at = now + timedelta(seconds=backoff)
        await session.flush()
        return 0

    async def reenable_disabled(
        self,
        session: AsyncSession,
        *,
        interval_seconds: int,
        only_previously_succeeded: bool = False,
        workspace_id: int | None = None,
    ) -> int:
        """Requeue auto-disabled tags: ``disabled`` -> ``pending``, reset failures.

        Recovery path for accounts wrongly disabled by a transient upstream
        outage (see ``record_failure``). ``only_previously_succeeded`` limits it
        to tags that ever produced a snapshot (skip genuinely-dead handles).
        Returns the number of rows re-enabled; caller commits. ``workspace_id``
        limits the recovery to the battle tags of that workspace's players, so a
        workspace-scoped admin cannot requeue another tenant's backlog.
        """
        return await self.repo.reenable_disabled(
            session,
            interval_seconds=interval_seconds,
            only_previously_succeeded=only_previously_succeeded,
            workspace_id=workspace_id,
        )

    async def defer_tag(
        self,
        session: AsyncSession,
        *,
        social_account_id: int,
        delay_seconds: int,
        now: datetime | None = None,
    ) -> None:
        """Push a tag's next eligibility out (used when a global cooldown is active)."""
        now = now or _now()
        await self.repo.defer(session, social_account_id=social_account_id, delay_seconds=delay_seconds, now=now)


rank_state_service = RankStateService()

# Module-attribute compatibility seam: admin.py/scheduler.py/tasks.py call these
# as bare ``service.<name>(...)`` (never ``rank_state_service.<name>``), and
# several tests patch/call them the same way
# (``patch.object(tasks.service, "record_result", ...)``,
# ``service.select_and_claim_due(...)``, ``service.workspace_account_ids(...)``)
# — per the ``differ.py``/balancer-service precedent, test coupling patches the
# *module's* namespace, not ``self.``, so every name below must stay resolvable
# as a plain module attribute bound to the singleton's method.
log_fetch = rank_state_service.log_fetch
ensure_state = rank_state_service.ensure_state
resolve_user_registration_targets = rank_state_service.resolve_user_registration_targets
resolve_registration_targets = rank_state_service.resolve_registration_targets
seed_states_for_all_battle_tags = rank_state_service.seed_states_for_all_battle_tags
seed_states_from_registrations = rank_state_service.seed_states_from_registrations
count_in_scope = rank_state_service.count_in_scope
last_success_at = rank_state_service.last_success_at
collection_stats = rank_state_service.collection_stats
select_and_claim_due = rank_state_service.select_and_claim_due
record_result = rank_state_service.record_result
record_failure = rank_state_service.record_failure
reenable_disabled = rank_state_service.reenable_disabled
defer_tag = rank_state_service.defer_tag
