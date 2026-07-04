"""Google-Sheets feed CRUD, mapping preview and sync orchestration.

Owns everything that talks to the sheet or the feed tables: CSV fetch, feed
upsert/validation, mapping catalog/suggestion/preview, and the periodic sync
(``sync_google_sheet_feed`` / ``sync_due_google_sheet_feeds``). Row parsing
itself lives in ``sheet_parsing``; everything here is re-exported by the
``admin`` facade.

Note for tests: functions here resolve collaborators from *this* module's
globals, so patch ``src.services.registration.sheet_sync`` (not the ``admin``
facade) to intercept e.g. ``fetch_google_sheet_rows`` or
``ensure_player_identity``.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import sqlalchemy as sa
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SocialProvider
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from src import models
from src.schemas.registration import CustomFieldDefinition
from src.services.registration._common import (
    ensure_tournament_exists,
    get_form_custom_field_defs,
    get_tournament_grid,
    replace_registration_roles,
    sync_included_balancer_status,
)
from src.services.registration.mapping_catalog import (
    PARSER_CATALOG,
    build_target_specs,
    classify_row_disposition,
    target_spec_map,
    validate_mapping_config,
)
from src.services.registration.service import ensure_player_identity
from src.services.registration.sheet_parsing import (
    build_default_value_mapping,
    build_registration_role_payloads,
    parse_sheet_row_detailed,
    serialize_parsed_fields,
    suggest_mapping_from_headers,
)
from src.services.registration.utils import (
    DEFAULT_SYNC_INTERVAL_SECONDS,
    GOOGLE_SHEET_FETCH_TIMEOUT,
    MIN_SYNC_INTERVAL_SECONDS,
    build_csv_export_url,
    build_header_keys,
    extract_sheet_source,
    fetch_csv_rows,
    normalize_battle_tag_key,
    row_to_json,
)
from src.services.tournament.realtime_commit import register_tournament_realtime_update

logger = logging.getLogger(__name__)


async def fetch_google_sheet_rows(
    source_url: str,
    *,
    sheet_id: str | None = None,
    gid: str | None = None,
) -> list[list[str]]:
    actual_sheet_id, actual_gid = (sheet_id, gid) if sheet_id else extract_sheet_source(source_url)
    url = build_csv_export_url(actual_sheet_id, actual_gid)
    async with httpx.AsyncClient(timeout=GOOGLE_SHEET_FETCH_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
    return fetch_csv_rows(response.text)


async def get_google_sheet_feed(
    session: AsyncSession,
    tournament_id: int,
) -> models.BalancerRegistrationGoogleSheetFeed | None:
    result = await session.execute(
        sa.select(models.BalancerRegistrationGoogleSheetFeed).where(
            models.BalancerRegistrationGoogleSheetFeed.tournament_id == tournament_id
        )
    )
    return result.scalar_one_or_none()


async def require_google_sheet_feed(
    session: AsyncSession,
    tournament_id: int,
) -> models.BalancerRegistrationGoogleSheetFeed:
    feed = await get_google_sheet_feed(session, tournament_id)
    if feed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Google Sheets feed not configured")
    return feed


async def _resolve_header_keys(
    source_url: str,
    feed: models.BalancerRegistrationGoogleSheetFeed | None,
) -> list[str] | None:
    """Header keys from a cached header row, else a best-effort live fetch.

    Returns ``None`` when headers can't be determined (so validation falls back
    to mode/parser/identity checks without column-existence).
    """
    if feed is not None and feed.source_url == source_url and feed.header_row_json:
        return build_header_keys(feed.header_row_json)
    try:
        rows = await fetch_google_sheet_rows(source_url)
    except (HTTPException, httpx.HTTPError):
        return None
    return build_header_keys(rows[0]) if rows else None


async def _validate_feed_mapping(
    session: AsyncSession,
    tournament_id: int,
    *,
    source_url: str,
    existing_feed: models.BalancerRegistrationGoogleSheetFeed | None,
    mapping_config_json: dict[str, Any],
) -> None:
    custom_fields = await get_form_custom_field_defs(session, tournament_id)
    target_specs = target_spec_map(custom_fields)
    header_keys = await _resolve_header_keys(source_url, existing_feed)
    issues = validate_mapping_config(
        mapping_config_json,
        target_specs=target_specs,
        header_keys=header_keys,
    )
    if issues:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "Invalid mapping configuration",
                "errors": [
                    {"code": issue.code, "target": issue.target, "column": issue.column, "message": issue.message}
                    for issue in issues
                ],
            },
        )


async def upsert_google_sheet_feed(
    session: AsyncSession,
    tournament_id: int,
    *,
    source_url: str,
    title: str | None,
    auto_sync_enabled: bool,
    auto_sync_interval_seconds: int,
    mapping_config_json: dict[str, Any] | None,
    value_mapping_json: dict[str, Any] | None,
) -> models.BalancerRegistrationGoogleSheetFeed:
    tournament = await ensure_tournament_exists(session, tournament_id)
    sheet_id, gid = extract_sheet_source(source_url)
    feed = await get_google_sheet_feed(session, tournament_id)
    if mapping_config_json is not None:
        await _validate_feed_mapping(
            session,
            tournament_id,
            source_url=source_url,
            existing_feed=feed,
            mapping_config_json=mapping_config_json,
        )
    if feed is None:
        feed = models.BalancerRegistrationGoogleSheetFeed(
            tournament_id=tournament.id,
            source_url=source_url,
            sheet_id=sheet_id,
            gid=gid,
            title=title,
            auto_sync_enabled=auto_sync_enabled,
            auto_sync_interval_seconds=auto_sync_interval_seconds,
            mapping_config_json=mapping_config_json,
            value_mapping_json=value_mapping_json,
            last_sync_status="pending",
        )
        session.add(feed)
    else:
        feed.source_url = source_url
        feed.sheet_id = sheet_id
        feed.gid = gid
        feed.title = title
        feed.auto_sync_enabled = auto_sync_enabled
        feed.auto_sync_interval_seconds = auto_sync_interval_seconds
        if mapping_config_json is not None:
            feed.mapping_config_json = mapping_config_json
        if value_mapping_json is not None:
            feed.value_mapping_json = value_mapping_json

    await session.commit()
    await session.refresh(feed)
    return feed


async def suggest_google_sheet_mapping(
    session: AsyncSession,
    tournament_id: int,
    *,
    source_url: str | None = None,
) -> tuple[models.BalancerRegistrationGoogleSheetFeed | None, list[str], dict[str, Any]]:
    feed = await get_google_sheet_feed(session, tournament_id)
    url = source_url or (feed.source_url if feed else None)
    if not url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google Sheets URL is required")
    rows = await fetch_google_sheet_rows(url)
    headers = rows[0]
    custom_fields = await get_form_custom_field_defs(session, tournament_id)
    return feed, headers, suggest_mapping_from_headers(headers, custom_fields=custom_fields)


def build_mapping_catalog(
    custom_fields: list[CustomFieldDefinition],
    *,
    value_mapping: dict[str, Any] | None = None,
    header_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the frontend mapping catalog (targets, parsers, value maps)."""
    specs = build_target_specs(custom_fields)
    default_value_mapping = build_default_value_mapping()
    saved_value_mapping = value_mapping or {}
    effective_value_mapping = {
        category: {
            **(default_value_mapping.get(category) or {}),
            **(saved_value_mapping.get(category) or {}),
        }
        for category in ("booleans", "roles", "subroles", "role_subroles", "divisions")
    }
    return {
        "targets": [
            {
                "key": spec.key,
                "label": spec.label,
                "group": spec.group,
                "accepted_parsers": list(spec.accepted_parsers),
                "default_parser": spec.default_parser,
                "default_mode": spec.default_mode,
                "default_is_list": spec.default_is_list,
                "multi_column": spec.multi_column,
                "required": spec.required,
            }
            for spec in specs
        ],
        "parsers": [
            {
                "parser": parser.parser,
                "label": parser.label,
                "cardinality": parser.cardinality,
                "produces": parser.produces,
            }
            for parser in PARSER_CATALOG
        ],
        "value_categories": [
            {"category": category, "entries": effective_value_mapping.get(category) or {}}
            for category in ("booleans", "roles", "subroles", "role_subroles", "divisions")
        ],
        "custom_fields": [field_def.model_dump() for field_def in custom_fields],
        "header_keys": header_keys or [],
    }


async def get_mapping_catalog(
    session: AsyncSession,
    tournament_id: int,
    *,
    include_headers: bool = False,
) -> dict[str, Any]:
    await ensure_tournament_exists(session, tournament_id)
    feed = await get_google_sheet_feed(session, tournament_id)
    custom_fields = await get_form_custom_field_defs(session, tournament_id)
    header_keys: list[str] | None = None
    if include_headers and feed is not None:
        if feed.header_row_json:
            header_keys = build_header_keys(feed.header_row_json)
        elif feed.source_url:
            header_keys = await _resolve_header_keys(feed.source_url, feed)
    return build_mapping_catalog(
        custom_fields,
        value_mapping=feed.value_mapping_json if feed else None,
        header_keys=header_keys,
    )


async def preview_google_sheet_mapping(
    session: AsyncSession,
    tournament_id: int,
    *,
    source_url: str | None = None,
    mapping_config_json: dict[str, Any] | None = None,
    value_mapping_json: dict[str, Any] | None = None,
    sample_rows: int = 5,
) -> dict[str, Any]:
    feed = await get_google_sheet_feed(session, tournament_id)
    url = source_url or (feed.source_url if feed else None)
    if not url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google Sheets URL is required")

    limit = max(1, min(int(sample_rows or 1), 50))
    rows = await fetch_google_sheet_rows(url)
    headers = rows[0]
    header_keys = build_header_keys(headers)
    data_rows = rows[1 : 1 + limit]
    grid = await get_tournament_grid(session, tournament_id)
    custom_fields = await get_form_custom_field_defs(session, tournament_id)
    effective_mapping = mapping_config_json or (feed.mapping_config_json if feed else None)
    effective_value_mapping = value_mapping_json or (feed.value_mapping_json if feed else None)

    known_source_keys, known_battle_tag_keys = await _existing_match_keys(session, tournament_id, feed)

    preview_rows: list[dict[str, Any]] = []
    create_count = 0
    update_count = 0
    skip_count = 0
    for index, data_row in enumerate(data_rows):
        result = parse_sheet_row_detailed(
            headers=headers,
            row=data_row,
            mapping_config=effective_mapping,
            value_mapping=effective_value_mapping,
            grid=grid,
            custom_fields=custom_fields,
        )
        fields = result.fields
        source_record_key = fields.get("source_record_key") if fields else None
        battle_tag_key = normalize_battle_tag_key(fields.get("battle_tag")) if fields else None
        disposition = classify_row_disposition(
            source_record_key,
            battle_tag_key,
            known_source_keys=known_source_keys,
            known_battle_tag_keys=known_battle_tag_keys,
        )
        if disposition == "create":
            create_count += 1
        elif disposition == "update":
            update_count += 1
        else:
            skip_count += 1
        preview_rows.append(
            {
                "row_index": index,
                "sample_raw_row": row_to_json(headers, data_row),
                "parsed_fields": serialize_parsed_fields(fields or {}),
                "errors": result.errors,
                "warnings": result.warnings,
                "disposition": disposition,
            }
        )

    first = preview_rows[0] if preview_rows else {}
    return {
        "headers": headers,
        "header_keys": header_keys,
        "rows": preview_rows,
        "create_count": create_count,
        "update_count": update_count,
        "skip_count": skip_count,
        # Back-compat single-row fields (populated from the first row).
        "sample_raw_row": first.get("sample_raw_row", {}),
        "parsed_fields": first.get("parsed_fields", {}),
    }


async def _existing_match_keys(
    session: AsyncSession,
    tournament_id: int,
    feed: models.BalancerRegistrationGoogleSheetFeed | None,
) -> tuple[set[str], set[str]]:
    """Existing source-record keys (bound rows) and battle-tag keys for disposition."""
    battle_tag_result = await session.execute(
        sa.select(models.BalancerRegistration.battle_tag_normalized).where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.battle_tag_normalized.is_not(None),
        )
    )
    battle_tag_keys = set(battle_tag_result.scalars().all())
    source_keys: set[str] = set()
    if feed is not None:
        source_result = await session.execute(
            sa.select(models.BalancerRegistrationGoogleSheetBinding.source_record_key).where(
                models.BalancerRegistrationGoogleSheetBinding.feed_id == feed.id
            )
        )
        source_keys = set(source_result.scalars().all())
    return source_keys, battle_tag_keys


def apply_sheet_fields_to_registration(
    registration: models.BalancerRegistration,
    parsed_fields: dict[str, Any],
    *,
    allow_balancer_overwrite: bool,
) -> None:
    registration.display_name = (
        parsed_fields.get("display_name") or parsed_fields.get("battle_tag") or registration.display_name
    )
    if parsed_fields.get("battle_tag") is not None:
        registration.battle_tag = parsed_fields["battle_tag"]
        registration.battle_tag_normalized = normalize_battle_tag_key(parsed_fields["battle_tag"])
    registration.smurf_tags_json = parsed_fields.get("smurf_tags") or None
    registration.discord_nick = parsed_fields.get("discord_nick")
    registration.twitch_nick = parsed_fields.get("twitch_nick")
    registration.stream_pov = bool(parsed_fields.get("stream_pov", False))
    registration.notes = parsed_fields.get("notes")

    parsed_custom = parsed_fields.get("custom_fields")
    if parsed_custom:
        merged = dict(registration.custom_fields_json or {})
        merged.update(parsed_custom)
        registration.custom_fields_json = merged or None

    if allow_balancer_overwrite:
        registration.admin_notes = parsed_fields.get("admin_notes")
        replace_registration_roles(registration, build_registration_role_payloads(parsed_fields))
        sync_included_balancer_status(registration)


SYNC_ERROR_SAMPLE_LIMIT = 20


@dataclass
class SheetSyncResult:
    feed: models.BalancerRegistrationGoogleSheetFeed
    created: int
    updated: int
    withdrawn: int
    total: int
    skipped: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


async def sync_google_sheet_feed(
    session: AsyncSession,
    tournament_id: int,
) -> SheetSyncResult:
    feed = await require_google_sheet_feed(session, tournament_id)
    grid = await get_tournament_grid(session, tournament_id)
    tournament = await ensure_tournament_exists(session, tournament_id)
    custom_fields = await get_form_custom_field_defs(session, tournament_id)
    now = datetime.now(UTC)

    try:
        rows = await fetch_google_sheet_rows(feed.source_url, sheet_id=feed.sheet_id, gid=feed.gid)
        headers = rows[0]
        mapping_config = feed.mapping_config_json or suggest_mapping_from_headers(headers, custom_fields=custom_fields)
        value_mapping = feed.value_mapping_json or build_default_value_mapping()

        parsed_rows: dict[str, tuple[dict[str, str], dict[str, Any]]] = {}
        skipped = 0
        row_errors: list[dict[str, Any]] = []
        for row_index, row in enumerate(rows[1:]):
            result = parse_sheet_row_detailed(
                headers=headers,
                row=row,
                mapping_config=mapping_config,
                value_mapping=value_mapping,
                grid=grid,
                custom_fields=custom_fields,
            )
            for entry in result.errors:
                if len(row_errors) < SYNC_ERROR_SAMPLE_LIMIT:
                    row_errors.append({**entry, "row_index": row_index})
            if not result.fields:
                skipped += 1
                continue
            parsed_rows[result.fields["source_record_key"]] = (row_to_json(headers, row), result.fields)

        existing_bindings_result = await session.execute(
            sa.select(models.BalancerRegistrationGoogleSheetBinding)
            .where(models.BalancerRegistrationGoogleSheetBinding.feed_id == feed.id)
            .options(
                selectinload(models.BalancerRegistrationGoogleSheetBinding.registration).selectinload(
                    models.BalancerRegistration.roles
                )
            )
        )
        existing_bindings = list(existing_bindings_result.scalars().all())
        bindings_by_key = {binding.source_record_key: binding for binding in existing_bindings}

        # Bulk prefetches for the per-row loop (this sync runs every 5 minutes
        # per tournament; per-row lookups used to cost 2-4 queries even for
        # unchanged rows):
        # 1. Active registrations keyed by normalized battle tag — replaces the
        #    per-new-row reuse query.
        reuse_rows = await session.execute(
            sa.select(models.BalancerRegistration)
            .where(
                models.BalancerRegistration.tournament_id == tournament_id,
                models.BalancerRegistration.deleted_at.is_(None),
                models.BalancerRegistration.battle_tag_normalized.isnot(None),
            )
            .options(selectinload(models.BalancerRegistration.roles))
            .order_by(models.BalancerRegistration.id.asc())
        )
        registrations_by_tag: dict[str, models.BalancerRegistration] = {}
        for reg_row in reuse_rows.scalars().all():
            registrations_by_tag.setdefault(reg_row.battle_tag_normalized, reg_row)

        # 2. Already-known battlenet handles of the linked players — lets
        #    ensure_player_identity below no-op (zero queries) for rows whose
        #    identity is already fully provisioned.
        linked_user_ids = {
            reg_row.user_id for reg_row in registrations_by_tag.values() if reg_row.user_id is not None
        }
        known_handles: set[tuple[int, str]] = set()
        if linked_user_ids:
            handle_rows = await session.execute(
                sa.select(models.SocialAccount.user_id, models.SocialAccount.username_normalized).where(
                    models.SocialAccount.user_id.in_(linked_user_ids),
                    models.SocialAccount.provider == SocialProvider.BATTLENET,
                )
            )
            known_handles = {(user_id, handle) for user_id, handle in handle_rows.all()}

        created = 0
        updated = 0
        withdrawn = 0
        seen_keys: set[str] = set()

        for source_record_key, (raw_row_json, parsed_fields) in parsed_rows.items():
            seen_keys.add(source_record_key)
            binding = bindings_by_key.get(source_record_key)
            registration = binding.registration if binding else None

            if registration is None:
                battle_tag_key = normalize_battle_tag_key(parsed_fields.get("battle_tag"))
                if battle_tag_key:
                    registration = registrations_by_tag.get(battle_tag_key)

            if registration is None:
                # Sheet-sync-created registrations have no registering auth account,
                # so workspace_member_id is left None (mirrors create_manual_registration).
                registration = models.BalancerRegistration(
                    tournament_id=tournament_id,
                    display_name=parsed_fields.get("display_name") or parsed_fields.get("battle_tag"),
                    battle_tag=parsed_fields.get("battle_tag"),
                    battle_tag_normalized=normalize_battle_tag_key(parsed_fields.get("battle_tag")),
                    smurf_tags_json=parsed_fields.get("smurf_tags") or None,
                    discord_nick=parsed_fields.get("discord_nick"),
                    twitch_nick=parsed_fields.get("twitch_nick"),
                    stream_pov=bool(parsed_fields.get("stream_pov", False)),
                    notes=parsed_fields.get("notes"),
                    admin_notes=parsed_fields.get("admin_notes"),
                    custom_fields_json=parsed_fields.get("custom_fields") or None,
                    status="approved",
                    exclude_from_balancer=False,
                    submitted_at=parsed_fields.get("submitted_at") or now,
                )
                replace_registration_roles(registration, build_registration_role_payloads(parsed_fields))
                session.add(registration)
                await session.flush()
                if registration.battle_tag_normalized:
                    registrations_by_tag.setdefault(registration.battle_tag_normalized, registration)
                created += 1
            else:
                allow_balancer_overwrite = registration.balancer_profile_overridden_at is None
                apply_sheet_fields_to_registration(
                    registration,
                    parsed_fields,
                    allow_balancer_overwrite=allow_balancer_overwrite,
                )
                if registration.status == "withdrawn":
                    registration.status = "approved"
                updated += 1

            # Resolve/provision the domain player so sheet-imported registrations
            # carry user_id (mirrors create_registration). Without this, OW-rank
            # lookup — which joins by user_id — finds nothing and the balancer
            # rank-delta UI stays empty. Idempotent: respects an already-linked
            # user_id, so re-syncs and already-linked rows are untouched.
            # known_handles makes the call a zero-query no-op for rows whose
            # identity is already fully provisioned (the common case on the
            # 5-minute re-sync of an unchanged sheet).
            await ensure_player_identity(session, registration, known_handles=known_handles)

            if binding is None:
                binding = models.BalancerRegistrationGoogleSheetBinding(
                    feed_id=feed.id,
                    registration_id=registration.id,
                    source_record_key=source_record_key,
                )
                session.add(binding)
                bindings_by_key[source_record_key] = binding

            binding.raw_row_json = raw_row_json
            binding.parsed_fields_json = serialize_parsed_fields(parsed_fields)
            binding.row_hash = hashlib.sha1(repr(raw_row_json).encode("utf-8")).hexdigest()
            binding.last_seen_at = now

        for binding in existing_bindings:
            if binding.source_record_key in seen_keys:
                continue
            if binding.registration.status != "withdrawn":
                binding.registration.status = "withdrawn"
                withdrawn += 1

        feed.header_row_json = headers
        if feed.mapping_config_json is None:
            feed.mapping_config_json = mapping_config
        if feed.value_mapping_json is None:
            feed.value_mapping_json = value_mapping
        feed.last_synced_at = now
        feed.last_sync_status = "success"
        if skipped or row_errors:
            summary = f"Synced with {skipped} skipped row(s)"
            if row_errors:
                summary += f" and {len(row_errors)} field error(s)"
            feed.last_error = summary
        else:
            feed.last_error = None
        if created or updated or withdrawn:
            register_tournament_realtime_update(session, tournament_id, "structure_changed")
        await session.commit()
        await session.refresh(feed)
        return SheetSyncResult(
            feed=feed,
            created=created,
            updated=updated,
            withdrawn=withdrawn,
            total=len(parsed_rows),
            skipped=skipped,
            errors=row_errors,
        )
    except HTTPException as exc:
        feed.last_synced_at = now
        feed.last_sync_status = "failed"
        feed.last_error = str(exc.detail)
        await session.commit()
        raise
    except httpx.HTTPError as exc:
        feed.last_synced_at = now
        feed.last_sync_status = "failed"
        feed.last_error = str(exc)
        await session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to fetch Google Sheet") from exc


async def sync_due_google_sheet_feeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        result = await session.execute(
            sa.select(models.BalancerRegistrationGoogleSheetFeed)
            .where(models.BalancerRegistrationGoogleSheetFeed.auto_sync_enabled.is_(True))
            .order_by(models.BalancerRegistrationGoogleSheetFeed.id.asc())
        )
        feeds = list(result.scalars().all())

    now = datetime.now(UTC)
    results: list[dict[str, Any]] = []
    for feed in feeds:
        interval = timedelta(
            seconds=max(
                int(feed.auto_sync_interval_seconds or DEFAULT_SYNC_INTERVAL_SECONDS), MIN_SYNC_INTERVAL_SECONDS
            )
        )
        if feed.last_synced_at is not None and feed.last_synced_at > now - interval:
            continue
        async with session_factory() as session:
            try:
                sync_result = await sync_google_sheet_feed(session, feed.tournament_id)
                results.append(
                    {
                        "tournament_id": feed.tournament_id,
                        "status": "success",
                        "created": sync_result.created,
                        "updated": sync_result.updated,
                        "withdrawn": sync_result.withdrawn,
                        "total": sync_result.total,
                        "skipped": sync_result.skipped,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to sync feed for tournament %s", feed.tournament_id)
                results.append(
                    {
                        "tournament_id": feed.tournament_id,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
    return results
