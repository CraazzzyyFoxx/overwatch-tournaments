"""Google-Sheets feed CRUD, mapping preview and sync orchestration.

Owns everything that talks to the sheet or the feed tables: CSV fetch, feed
upsert/validation, mapping catalog/suggestion/preview, and the periodic sync
(``sync_google_sheet_feed`` / ``sync_due_google_sheet_feeds``). Row parsing
itself lives in ``sheet_parsing``.

Note for tests: ``SheetSyncService`` resolves its *function* collaborators from
*this* module's globals, so patch ``src.services.registration.sheet_sync`` to
intercept e.g. ``fetch_google_sheet_rows`` or ``parse_sheet_row_detailed``. Its
*service* collaborators are objects: the injected ``self.common``
(``_common_service``) and the module-global ``registration_service``, so patch
those objects' methods rather than a module-level name.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from shared import models
from shared.balancer_subrole_catalog import resolve_subrole_catalog
from shared.core import http_status as status
from shared.core.errors import ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import normalize_social_handle
from shared.disciplines import DISCIPLINES, identity_provider
from shared.domain.forms import FormSchema, default_schema, identity_key, schema_from_form
from shared.domain.roster import FlexRoleMode, flex_role_mode_from_schema
from shared.repository import (
    CatalogRoleRepository,
    GoogleSheetBindingRepository,
    GoogleSheetFeedRepository,
    RegistrationRepository,
)
from shared.services.realtime import Resource, Scope, emit
from shared.services.roster import roster_engine
from src.domain.registration.mapping_catalog import (
    PARSER_CATALOG,
    build_target_specs,
    classify_row_disposition,
    schema_custom_fields,
    target_spec_map,
    validate_mapping_config,
    validate_value_mapping_subroles,
)
from src.domain.registration.sheet_parsing import (
    build_default_value_mapping,
    build_registration_role_payloads,
    parse_sheet_row_detailed,
    serialize_parsed_fields,
    suggest_mapping_from_headers,
)
from src.domain.registration.utils import (
    DEFAULT_SYNC_INTERVAL_SECONDS,
    GOOGLE_SHEET_FETCH_TIMEOUT,
    MIN_SYNC_INTERVAL_SECONDS,
    build_csv_export_url,
    build_header_keys,
    extract_sheet_source,
    fetch_csv_rows,
    row_to_json,
)
from src.services.registration._common import (
    RegistrationCommonService,
    _common_service,
    replace_registration_roles,
    root_role_codes,
    sync_included_balancer_status,
)
from src.services.registration.answers import answer_service
from src.services.registration.service import registration_service

logger = logging.getLogger(__name__)

SYNC_ERROR_SAMPLE_LIMIT = 20


def _primary_game_handle_key(answers: Mapping[str, Any], provider: str) -> str | None:
    """Normalized PRIMARY handle of an answer document for the owning ``provider``, or ``None``.

    The key sheet rows are matched against: a registration is the same person as
    a sheet row when their primary handle for the tournament's game agrees.
    """
    handles = answers.get(identity_key(provider)) or []
    return normalize_social_handle(provider, handles[0]) if handles else None


def _row_hash(
    raw_row_json: dict[str, str], parsed_fields_json: dict[str, Any], mode: str, registration: models.Registration
) -> str:
    """What a binding remembers of the apply that wrote it; any change re-applies the row.

    The cells, their parse (so a mapping edit counts) and the flex mode (a mode edit
    rewrites role sets), plus whether the sheet could write the roles at all: pinning
    or unpinning a profile changes what the next apply does with the same row.
    """
    writable = registration.balancer_profile_overridden_at is None
    return hashlib.sha1(repr((raw_row_json, parsed_fields_json, mode, writable)).encode("utf-8")).hexdigest()


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


async def _resolve_header_keys(
    source_url: str,
    feed: models.RegistrationGoogleSheetFeed | None,
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


def build_mapping_catalog(
    schema: FormSchema | None,
    *,
    role_codes: tuple[str, ...],
    value_mapping: dict[str, Any] | None = None,
    header_keys: list[str] | None = None,
    subrole_catalog: dict[str, list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    """Assemble the frontend mapping catalog (targets, parsers, value maps)."""
    specs = build_target_specs(schema, role_codes=role_codes)
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
        "custom_fields": [field_def.model_dump() for field_def in schema_custom_fields(schema)],
        "header_keys": header_keys or [],
        "subrole_catalog": subrole_catalog or {code: [] for code in role_codes},
    }


def apply_sheet_fields_to_registration(
    registration: models.Registration,
    parsed_fields: dict[str, Any],
    values: Mapping[str, Any],
    *,
    schema: FormSchema,
    catalog_roles: Mapping[str, models.CatalogRole],
    allow_balancer_overwrite: bool,
    sheet_ranked_roles: Collection[str],
    mode: FlexRoleMode = "optional",
) -> bool:
    """Write one parsed sheet row onto a registration.

    ``values`` is the row's answers already validated against ``schema``; the
    answer service owns the columns, the identity rows and the custom answers,
    so everything left here is organizer state the form never asks about.

    Returns whether the row's roles were rewritten, i.e. whether its
    ``ready``/``incomplete`` verdict needs recomputing. The recompute itself is
    deferred to one batch at the end of the sync: the verdict comes from the
    roster engine, which needs a session, and asking it per row would put a
    resolve inside a loop that runs every five minutes per tournament.

    Only ranks of ``sheet_ranked_roles`` (the roles the mapping reads a rank
    for) come from the sheet. Every other role keeps the rank it held, because
    autofill and organizers write ``rank_value`` too and a sheet without that
    column has nothing to say about it.
    """
    registration.display_name = parsed_fields.get("display_name") or registration.display_name
    answer_service.apply(registration, values, schema=schema, hero_catalog=None, catalog_roles=catalog_roles)

    if not allow_balancer_overwrite:
        return False
    registration.admin_notes = parsed_fields.get("admin_notes")
    stored_ranks = {role.role: role.rank_value for role in registration.roles}
    replace_registration_roles(
        registration,
        build_registration_role_payloads(
            parsed_fields,
            role_codes=root_role_codes(catalog_roles),
        ),
        catalog_roles=catalog_roles,
        mode=mode,
    )
    for role in registration.roles:
        if role.role not in sheet_ranked_roles:
            role.rank_value = stored_ranks.get(role.role)
    return True


@dataclass
class SheetSyncResult:
    feed: models.RegistrationGoogleSheetFeed
    created: int
    updated: int
    withdrawn: int
    total: int
    skipped: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    # Another sync of this feed held its lock: nothing was applied, counted or stamped.
    locked: bool = False


class SheetSyncService:
    def __init__(
        self,
        *,
        feed_repo: GoogleSheetFeedRepository = GoogleSheetFeedRepository(),
        binding_repo: GoogleSheetBindingRepository = GoogleSheetBindingRepository(),
        registration_repo: RegistrationRepository = RegistrationRepository(),
        common: RegistrationCommonService = _common_service,
    ) -> None:
        self.feed_repo = feed_repo
        self.binding_repo = binding_repo
        self.registration_repo = registration_repo
        self.common = common

    async def _registration_schema(self, session: AsyncSession, tournament_id: int) -> FormSchema:
        """THE schema every sheet operation is written against.

        One resolver, because the mapping catalog, the config validation, the
        suggester, the preview and the sync must agree on which targets exist:
        a catalog that offers a target the validator rejects, or a validator
        that accepts one the sync ignores, is worse than either rule alone.

        A tournament with no form (or no version yet) falls back to the
        discipline's default schema, as ``lifecycle._validated_answers`` does, so
        its sheet still lands every battle tag.
        """
        schema = schema_from_form(await self.common.get_registration_form(session, tournament_id))
        if schema is not None:
            return schema
        tournament = await self.common.ensure_tournament_exists(session, tournament_id)
        return default_schema(identity_provider(tournament.discipline))

    async def get_google_sheet_feed(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.RegistrationGoogleSheetFeed | None:
        return await self.feed_repo.get_by_tournament(session, tournament_id)

    async def require_google_sheet_feed(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.RegistrationGoogleSheetFeed:
        feed = await self.get_google_sheet_feed(session, tournament_id)
        if feed is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Google Sheets feed not configured")
        return feed

    async def _validate_feed_mapping(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        source_url: str,
        existing_feed: models.RegistrationGoogleSheetFeed | None,
        mapping_config_json: dict[str, Any] | None,
        value_mapping_json: dict[str, Any] | None = None,
    ) -> None:
        tournament = await self.common.ensure_tournament_exists(session, tournament_id)
        catalog = await resolve_subrole_catalog(session, tournament.workspace_id, discipline=tournament.discipline)
        schema = await self._registration_schema(session, tournament_id)
        target_specs = target_spec_map(schema, role_codes=tuple(catalog))
        header_keys = await _resolve_header_keys(source_url, existing_feed)
        issues = []
        if mapping_config_json is not None:
            issues.extend(
                validate_mapping_config(
                    mapping_config_json,
                    target_specs=target_specs,
                    header_keys=header_keys,
                    subrole_catalog=catalog,
                )
            )
        if value_mapping_json is not None:
            issues.extend(validate_value_mapping_subroles(value_mapping_json, catalog))
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
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        source_url: str,
        title: str | None,
        auto_sync_enabled: bool,
        auto_sync_interval_seconds: int,
        mapping_config_json: dict[str, Any] | None,
        value_mapping_json: dict[str, Any] | None,
    ) -> models.RegistrationGoogleSheetFeed:
        tournament = await self.common.ensure_tournament_exists(session, tournament_id)
        sheet_id, gid = extract_sheet_source(source_url)
        feed = await self.get_google_sheet_feed(session, tournament_id)
        if mapping_config_json is not None or value_mapping_json is not None:
            await self._validate_feed_mapping(
                session,
                tournament_id,
                source_url=source_url,
                existing_feed=feed,
                mapping_config_json=mapping_config_json,
                value_mapping_json=value_mapping_json,
            )
        if feed is None:
            feed = models.RegistrationGoogleSheetFeed(
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
            await self.feed_repo.create(session, feed)
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
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        source_url: str | None = None,
    ) -> tuple[models.RegistrationGoogleSheetFeed | None, list[str], dict[str, Any]]:
        feed = await self.get_google_sheet_feed(session, tournament_id)
        url = source_url or (feed.source_url if feed else None)
        if not url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google Sheets URL is required")
        rows = await fetch_google_sheet_rows(url)
        headers = rows[0]
        schema = await self._registration_schema(session, tournament_id)
        tournament = await self.common.ensure_tournament_exists(session, tournament_id)
        role_codes = tuple(role.code for role in DISCIPLINES[tournament.discipline].rated_dimension.roles)
        return (
            feed,
            headers,
            suggest_mapping_from_headers(
                headers, schema=schema, role_codes=role_codes, provider=identity_provider(tournament.discipline)
            ),
        )

    async def get_mapping_catalog(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        include_headers: bool = False,
    ) -> dict[str, Any]:
        tournament = await self.common.ensure_tournament_exists(session, tournament_id)
        feed = await self.get_google_sheet_feed(session, tournament_id)
        schema = await self._registration_schema(session, tournament_id)
        header_keys: list[str] | None = None
        if include_headers and feed is not None:
            if feed.header_row_json:
                header_keys = build_header_keys(feed.header_row_json)
            elif feed.source_url:
                header_keys = await _resolve_header_keys(feed.source_url, feed)
        return build_mapping_catalog(
            schema,
            role_codes=tuple(role.code for role in DISCIPLINES[tournament.discipline].rated_dimension.roles),
            value_mapping=feed.value_mapping_json if feed else None,
            header_keys=header_keys,
            subrole_catalog=await resolve_subrole_catalog(
                session, tournament.workspace_id, discipline=tournament.discipline
            ),
        )

    async def preview_google_sheet_mapping(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        source_url: str | None = None,
        mapping_config_json: dict[str, Any] | None = None,
        value_mapping_json: dict[str, Any] | None = None,
        sample_rows: int = 5,
    ) -> dict[str, Any]:
        feed = await self.get_google_sheet_feed(session, tournament_id)
        url = source_url or (feed.source_url if feed else None)
        if not url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google Sheets URL is required")

        limit = max(1, min(int(sample_rows or 1), 50))
        rows = await fetch_google_sheet_rows(url)
        headers = rows[0]
        header_keys = build_header_keys(headers)
        data_rows = rows[1 : 1 + limit]
        grid = await self.common.get_tournament_grid(session, tournament_id)
        schema = await self._registration_schema(session, tournament_id)
        effective_mapping = mapping_config_json or (feed.mapping_config_json if feed else None)
        effective_value_mapping = value_mapping_json or (feed.value_mapping_json if feed else None)
        tournament = await self.common.ensure_tournament_exists(session, tournament_id)
        provider = identity_provider(tournament.discipline)
        subrole_catalog = await resolve_subrole_catalog(
            session, tournament.workspace_id, discipline=tournament.discipline
        )

        known_source_keys, known_handle_keys = await self._existing_match_keys(session, tournament_id, feed, provider)

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
                schema=schema,
                subrole_catalog=subrole_catalog,
                role_codes=tuple(subrole_catalog),
                provider=provider,
            )
            fields = result.fields
            source_record_key = fields.get("source_record_key") if fields else None
            handle_key = _primary_game_handle_key((fields or {}).get("answers") or {}, provider)
            disposition = classify_row_disposition(
                source_record_key,
                handle_key,
                known_source_keys=known_source_keys,
                known_handle_keys=known_handle_keys,
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
            # The first preview row's fields, for single-row consumers.
            "sample_raw_row": first.get("sample_raw_row", {}),
            "parsed_fields": first.get("parsed_fields", {}),
        }

    async def _existing_match_keys(
        self,
        session: AsyncSession,
        tournament_id: int,
        feed: models.RegistrationGoogleSheetFeed | None,
        provider: str,
    ) -> tuple[set[str], set[str]]:
        """Existing source-record keys (bound rows) and primary game handle keys."""
        handle_result = await session.execute(
            sa.select(models.RegistrationIdentity.handle_normalized)
            .join(
                models.Registration,
                models.Registration.id == models.RegistrationIdentity.registration_id,
            )
            .where(
                models.Registration.tournament_id == tournament_id,
                models.Registration.deleted_at.is_(None),
                models.RegistrationIdentity.provider == provider,
                models.RegistrationIdentity.position == 0,
            )
        )
        handle_keys = set(handle_result.scalars().all())
        source_keys: set[str] = set()
        if feed is not None:
            source_keys = set(await self.binding_repo.list_source_record_keys(session, feed.id))
        return source_keys, handle_keys

    async def _list_auto_sync_feeds(
        self,
        session: AsyncSession,
    ) -> list[models.RegistrationGoogleSheetFeed]:
        """Every feed with auto-sync on, oldest id first (the scheduler's sweep set)."""
        result = await session.execute(
            self.feed_repo.select()
            .where(models.RegistrationGoogleSheetFeed.auto_sync_enabled.is_(True))
            .order_by(models.RegistrationGoogleSheetFeed.id.asc())
        )
        return list(result.scalars().all())

    async def _validated_row_answers(
        self,
        session: AsyncSession,
        parsed_fields: dict[str, Any],
        *,
        schema: FormSchema,
        workspace_id: int,
        discipline: str,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """One row's answers validated against the form, or ``None`` + its errors.

        The organizer profile: partial (an unmapped question is untouched, a
        mapped-and-empty cell clears), requirements off, and no OAuth gate --
        nobody's proof backs what a spreadsheet says.

        The answers arrive already restricted to questions the schema declares,
        because the target set the parser works from IS derived from that schema
        (``mapping_catalog.build_target_specs``). Nothing is filtered here: a key
        this rejects as unknown would be a genuine disagreement between the two,
        and the row error it raises is the right way to hear about it.

        A row whose answers do not normalise comes back as ``None`` plus its
        field errors, and the caller leaves it unwritten rather than
        half-written.
        """
        answers = parsed_fields.get("answers") or {}
        try:
            values = await answer_service.validate(
                session,
                schema=schema,
                answers=answers,
                partial=True,
                enforce_required=False,
                player_id=None,
                workspace_id=workspace_id,
                discipline=discipline,
                hero_catalog=None,
            )
        except ApiHTTPException as exc:
            return None, [
                {
                    "target": detail.get("field"),
                    "column": None,
                    "message": detail.get("msg") or "",
                    "code": detail.get("code"),
                }
                for detail in exc.detail
            ]
        return values, []

    async def sync_google_sheet_feed(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> SheetSyncResult:
        feed = await self.require_google_sheet_feed(session, tournament_id)
        now = datetime.now(UTC)
        # The fetch can take GOOGLE_SHEET_FETCH_TIMEOUT: end the transaction before it
        # (committing whatever the caller staged) so no pooled connection waits on Google.
        await session.commit()

        try:
            rows = await fetch_google_sheet_rows(feed.source_url, sheet_id=feed.sheet_id, gid=feed.gid)
            # The scheduler and the sheet_sync RPC can reach one feed at once; the
            # loser skips rather than race the winner's inserts. The two-key form
            # is its own lock space, apart from every one-key lock in the codebase.
            if not await session.scalar(
                sa.select(sa.func.pg_try_advisory_xact_lock(sa.func.hashtext("registration.sheet_sync"), feed.id))
            ):
                return SheetSyncResult(feed=feed, created=0, updated=0, withdrawn=0, total=0, locked=True)
            grid = await self.common.get_tournament_grid(session, tournament_id)
            tournament = await self.common.ensure_tournament_exists(session, tournament_id)
            form = await self.common.get_registration_form(session, tournament_id)
            # A feed can be configured before anyone opens the form builder. The
            # shipped default question set then stands in as the sheet's answer
            # vocabulary, so an import still lands the battle tag -- the row's own
            # identity -- instead of writing nothing at all. Same fallback as
            # ``_registration_schema``, spelled out because the sync needs the form
            # row itself for ``current_version_id``.
            provider = identity_provider(tournament.discipline)
            schema = schema_from_form(form) or default_schema(provider)
            # The sheet sync is the one role-write path that does not go through the form. In a
            # non-optional flex mode a sheet row must land with the same role set as any
            # other, so the mode is resolved once per sync rather than per row.
            mode = flex_role_mode_from_schema(schema)
            catalog_roles = await CatalogRoleRepository().rated_rows(
                session, discipline=tournament.discipline, workspace_id=tournament.workspace_id
            )
            role_codes = tuple(role.code for role in DISCIPLINES[tournament.discipline].rated_dimension.roles)

            headers = rows[0]
            mapping_config = feed.mapping_config_json or suggest_mapping_from_headers(
                headers, schema=schema, role_codes=role_codes, provider=provider
            )
            value_mapping = feed.value_mapping_json or build_default_value_mapping()
            targets = mapping_config.get("targets") or {}
            # Roles whose rank the mapping reads off the sheet (a target ``get_selector_values``
            # reads: columns or a constant). Any other role keeps the rank it already holds.
            sheet_ranked_roles = {
                code
                for code in role_codes
                for key in (f"roles.{code}.rank_value", f"roles.{code}.division_input")
                if targets.get(key) and targets[key].get("mode") not in ("disabled", "auto")
            }
            subrole_catalog = await resolve_subrole_catalog(
                session, tournament.workspace_id, discipline=tournament.discipline
            )

            parsed_rows: dict[str, tuple[int, dict[str, str], dict[str, Any]]] = {}
            skipped = 0
            row_errors: list[dict[str, Any]] = []
            for row_index, row in enumerate(rows[1:]):
                result = parse_sheet_row_detailed(
                    headers=headers,
                    row=row,
                    mapping_config=mapping_config,
                    value_mapping=value_mapping,
                    grid=grid,
                    schema=schema,
                    subrole_catalog=subrole_catalog,
                    role_codes=role_codes,
                    provider=provider,
                )
                for entry in result.errors:
                    if len(row_errors) < SYNC_ERROR_SAMPLE_LIMIT:
                        row_errors.append({**entry, "row_index": row_index})
                if not result.fields:
                    skipped += 1
                    continue
                parsed_rows[result.fields["source_record_key"]] = (row_index, row_to_json(headers, row), result.fields)

            existing_bindings = list(
                await self.binding_repo.list_by_feed(
                    session,
                    feed.id,
                    options=[
                        selectinload(models.RegistrationGoogleSheetBinding.registration).selectinload(
                            models.Registration.roles
                        ),
                        # Pre-warm the identity map so ensure_player_identity's member
                        # lookup below is query-free for already-anchored rows.
                        selectinload(models.RegistrationGoogleSheetBinding.registration).selectinload(
                            models.Registration.workspace_member
                        ),
                        # ``answer_service.apply`` upserts identity rows in place;
                        # the relationship is never lazy-loadable in async code.
                        selectinload(models.RegistrationGoogleSheetBinding.registration).selectinload(
                            models.Registration.identities
                        ),
                    ],
                )
            )
            bindings_by_key = {binding.source_record_key: binding for binding in existing_bindings}

            # Bulk prefetches for the per-row loop, so a changed row costs no
            # lookups of its own (unchanged rows are skipped before any):
            # 1. Active registrations keyed by normalized primary game handle.
            reuse_rows = await session.execute(
                self.registration_repo.select()
                .where(
                    models.Registration.tournament_id == tournament_id,
                    models.Registration.deleted_at.is_(None),
                )
                .options(
                    selectinload(models.Registration.roles),
                    # The member is the registration's identity anchor; loading it
                    # here keeps ensure_player_identity's lookup query-free.
                    selectinload(models.Registration.workspace_member),
                    selectinload(models.Registration.identities),
                )
                .order_by(models.Registration.id.asc())
            )
            registrations_by_handle: dict[str, models.Registration] = {}
            for reg_row in reuse_rows.scalars().all():
                identity = reg_row.primary_game_identity(provider=provider)
                if identity is not None:
                    registrations_by_handle.setdefault(identity.handle_normalized, reg_row)

            # 2. Already-known social handles of the anchored players — lets
            #    ensure_player_identity below no-op (zero queries) for rows whose
            #    identity is already fully provisioned.
            linked_player_ids = {
                reg_row.workspace_member.player_id
                for reg_row in registrations_by_handle.values()
                if reg_row.workspace_member is not None
            }
            known_handles: set[tuple[int, str, str]] = set()
            if linked_player_ids:
                handle_rows = await session.execute(
                    sa.select(
                        models.SocialAccount.user_id,
                        models.SocialAccount.provider,
                        models.SocialAccount.username_normalized,
                    ).where(models.SocialAccount.user_id.in_(linked_player_ids))
                )
                known_handles = {(player_id, provider, handle) for player_id, provider, handle in handle_rows.all()}

            created = 0
            updated = 0
            withdrawn = 0
            seen_keys: set[str] = set()
            # Rows whose roles the sync rewrote: their ready/incomplete verdict is
            # recomputed once, below, from the engine's rosters.
            resync_status_by_id: dict[int, models.Registration] = {}

            for source_record_key, (row_index, raw_row_json, parsed_fields) in parsed_rows.items():
                # Seen BEFORE validation: a row the sheet still carries must not
                # be withdrawn just because one of its cells no longer parses.
                seen_keys.add(source_record_key)
                binding = bindings_by_key.get(source_record_key)
                parsed_fields_json = serialize_parsed_fields(parsed_fields)
                # Applied as-is last time: nothing to validate, write or count. A
                # withdrawn registration is re-applied, so a row back on the sheet restores it.
                if (
                    binding is not None
                    and binding.row_hash == _row_hash(raw_row_json, parsed_fields_json, mode, binding.registration)
                    and binding.registration.status != "withdrawn"
                ):
                    continue
                values, answer_errors = await self._validated_row_answers(
                    session,
                    parsed_fields,
                    schema=schema,
                    workspace_id=tournament.workspace_id,
                    discipline=tournament.discipline,
                )
                if values is None:
                    for entry in answer_errors:
                        if len(row_errors) < SYNC_ERROR_SAMPLE_LIMIT:
                            row_errors.append({**entry, "row_index": row_index})
                    skipped += 1
                    continue

                registration = binding.registration if binding else None

                if registration is None:
                    handle_key = _primary_game_handle_key(values, provider)
                    if handle_key:
                        registration = registrations_by_handle.get(handle_key)

                if registration is None:
                    # Sheet-sync-created registrations have no registering auth account;
                    # their workspace_member anchor is provisioned from the game handle by
                    # ensure_player_identity below.
                    registration = models.Registration(
                        tournament_id=tournament_id,
                        form_version_id=form.current_version_id if form is not None else None,
                        display_name=parsed_fields.get("display_name"),
                        admin_notes=parsed_fields.get("admin_notes"),
                        status="approved",
                        submitted_at=parsed_fields.get("submitted_at") or now,
                        identities=[],
                    )
                    answer_service.apply(
                        registration, values, schema=schema, hero_catalog=None, catalog_roles=catalog_roles
                    )
                    replace_registration_roles(
                        registration,
                        build_registration_role_payloads(parsed_fields, role_codes=role_codes),
                        catalog_roles=catalog_roles,
                        mode=mode,
                    )
                    await self.registration_repo.create(session, registration)
                    new_identity = registration.primary_game_identity(provider=provider)
                    if new_identity is not None:
                        registrations_by_handle.setdefault(new_identity.handle_normalized, registration)
                    created += 1
                else:
                    allow_balancer_overwrite = registration.balancer_profile_overridden_at is None
                    if apply_sheet_fields_to_registration(
                        registration,
                        parsed_fields,
                        values,
                        schema=schema,
                        catalog_roles=catalog_roles,
                        allow_balancer_overwrite=allow_balancer_overwrite,
                        sheet_ranked_roles=sheet_ranked_roles,
                        mode=mode,
                    ):
                        resync_status_by_id[registration.id] = registration
                    if registration.status == "withdrawn":
                        registration.status = "approved"
                    updated += 1

                # Anchor sheet-imported registrations on a workspace_member: OW-rank
                # lookup resolves the player via workspace_member.player_id, so an
                # unanchored row leaves the balancer rank-delta UI empty. Idempotent
                # for already-anchored rows; known_handles makes it a zero-query no-op
                # for rows whose identity is already fully provisioned.
                await registration_service.ensure_player_identity(
                    session,
                    registration,
                    provider=provider,
                    workspace_id=tournament.workspace_id,
                    known_handles=known_handles,
                )

                row_hash = _row_hash(raw_row_json, parsed_fields_json, mode, registration)
                if binding is None:
                    # Every column is set up front so the insert is one statement:
                    # the repository's create() flushes, and assigning after it would
                    # trade that INSERT for an INSERT plus an UPDATE per new row.
                    binding = models.RegistrationGoogleSheetBinding(
                        feed_id=feed.id,
                        registration_id=registration.id,
                        source_record_key=source_record_key,
                        raw_row_json=raw_row_json,
                        parsed_fields_json=parsed_fields_json,
                        row_hash=row_hash,
                        last_seen_at=now,
                    )
                    await self.binding_repo.create(session, binding)
                    bindings_by_key[source_record_key] = binding
                else:
                    binding.raw_row_json = raw_row_json
                    binding.parsed_fields_json = parsed_fields_json
                    binding.row_hash = row_hash
                    binding.last_seen_at = now

            for binding in existing_bindings:
                if binding.source_record_key in seen_keys:
                    continue
                if binding.registration.status != "withdrawn":
                    binding.registration.status = "withdrawn"
                    withdrawn += 1

            if resync_status_by_id:
                # One resolve for every row the sync rewrote. Re-read through the
                # engine because the rows above were loaded for the sync's own
                # purposes; autoflush publishes the role writes first, so the
                # verdict is the one this sync just produced.
                rosters = await roster_engine.for_tournament(
                    session,
                    tournament_id,
                    registration_ids=list(resync_status_by_id),
                    include_deleted=True,
                )
                for registration_id, registration in resync_status_by_id.items():
                    sync_included_balancer_status(registration, rosters.get(registration_id))

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
                await emit(
                    session,
                    scope=Scope.tournament(tournament_id),
                    invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
                )
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
            # The rows applied before the failure must not ride the stamp's commit.
            await session.rollback()
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


sheet_sync_service = SheetSyncService()


async def sync_due_google_sheet_feeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[dict[str, Any]]:
    """Scheduler entrypoint: sync every feed whose interval has elapsed.

    Function-shaped on purpose — it takes a *session factory*, not a session, and
    owns one unit of work per feed, so it is the caller of the service rather than
    a method on it.
    """
    async with session_factory() as session:
        feeds = await sheet_sync_service._list_auto_sync_feeds(session)

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
                sync_result = await sheet_sync_service.sync_google_sheet_feed(session, feed.tournament_id)
                results.append(
                    {
                        "tournament_id": feed.tournament_id,
                        "status": "locked" if sync_result.locked else "success",
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
