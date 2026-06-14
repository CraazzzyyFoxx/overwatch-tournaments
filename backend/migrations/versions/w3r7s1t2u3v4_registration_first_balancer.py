"""registration_first_balancer

Revision ID: w3r7s1t2u3v4
Revises: v2q6r0s1t2u3
Create Date: 2026-04-12 15:00:00.000000

"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Any, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "w3r7s1t2u3v4"
down_revision: Union[str, None] = "v2q6r0s1t2u3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLE_ORDER = ("tank", "dps", "support")


def _build_header_keys(headers: list[str] | None) -> list[str]:
    if not headers:
        return []

    seen: dict[str, int] = {}
    keys: list[str] = []
    for index, header in enumerate(headers):
        key_base = (header or "").strip() or f"column_{index}"
        occurrence = seen.get(key_base, 0)
        seen[key_base] = occurrence + 1
        keys.append(key_base if occurrence == 0 else f"{key_base}__{occurrence}")
    return keys


def _build_target(*, parser: str, columns: Iterable[str] | None = None, value: Any | None = None) -> dict[str, Any]:
    if value is not None:
        return {"mode": "constant", "value": value, "parser": parser}

    column_list = [column for column in (columns or []) if column]
    if not column_list:
        return {"mode": "disabled", "parser": parser}

    return {
        "mode": "columns",
        "columns": column_list,
        "parser": parser,
    }


def _column_name(header_keys: list[str], index: int | None) -> str | None:
    if index is None:
        return None
    if index < 0 or index >= len(header_keys):
        return None
    return header_keys[index]


def _column_names(header_keys: list[str], indexes: list[int] | None) -> list[str]:
    names: list[str] = []
    for index in indexes or []:
        column_name = _column_name(header_keys, index)
        if column_name:
            names.append(column_name)
    return names


def _build_legacy_mapping_config(
    column_mapping_json: dict[str, Any] | None,
    header_row_json: list[str] | None,
) -> dict[str, Any] | None:
    if not column_mapping_json and not header_row_json:
        return None

    header_keys = _build_header_keys(header_row_json)
    column_mapping = column_mapping_json or {}

    battle_tag_column = _column_name(header_keys, column_mapping.get("battle_tag"))
    targets = {
        "source_record_key": _build_target(parser="battle_tag", columns=[battle_tag_column] if battle_tag_column else None),
        "display_name": _build_target(parser="string", columns=[battle_tag_column] if battle_tag_column else None),
        "battle_tag": _build_target(parser="battle_tag", columns=[battle_tag_column] if battle_tag_column else None),
        "submitted_at": _build_target(parser="datetime", columns=[_column_name(header_keys, column_mapping.get("timestamp"))]),
        "smurf_tags": _build_target(parser="battle_tag_list", columns=[_column_name(header_keys, column_mapping.get("smurf_tags"))]),
        "discord_nick": _build_target(parser="string", columns=[_column_name(header_keys, column_mapping.get("discord_nick"))]),
        "twitch_nick": _build_target(parser="string", columns=[_column_name(header_keys, column_mapping.get("twitch_nick"))]),
        "stream_pov": _build_target(parser="boolean", columns=[_column_name(header_keys, column_mapping.get("stream_pov"))]),
        "notes": _build_target(parser="join_lines", columns=[_column_name(header_keys, column_mapping.get("notes"))]),
        "source_roles.primary": _build_target(parser="role_token", columns=[_column_name(header_keys, column_mapping.get("primary_role"))]),
        "source_roles.additional": _build_target(parser="role_token_list", columns=_column_names(header_keys, column_mapping.get("additional_roles"))),
    }

    return {"targets": targets}


def _build_legacy_value_mapping(role_mapping_json: dict[str, Any] | None) -> dict[str, Any] | None:
    if not role_mapping_json:
        return None
    return {"roles": role_mapping_json}


def _resolve_rank_from_division_number(
    division_number: int | None,
    tournament_grid_json: dict[str, Any] | None,
    workspace_grid_json: dict[str, Any] | None,
) -> int | None:
    if division_number is None:
        return None

    tiers = (tournament_grid_json or workspace_grid_json or {}).get("tiers")
    if isinstance(tiers, list):
        for tier in tiers:
            try:
                if int(tier["number"]) != int(division_number):
                    continue
                rank_min = int(tier["rank_min"])
                rank_max_raw = tier.get("rank_max")
                if rank_max_raw is None:
                    return rank_min
                return (rank_min + int(rank_max_raw)) // 2
            except (KeyError, TypeError, ValueError):
                continue

    if division_number == 1:
        return 2000
    if 1 <= division_number <= 20:
        return (20 - division_number) * 100 + 49
    return None


def _normalize_role_code(raw_role: Any) -> str | None:
    if not isinstance(raw_role, str):
        return None
    normalized = raw_role.strip().lower()
    if normalized in {"tank", "dps", "support"}:
        return normalized
    if normalized == "damage":
        return "dps"
    return None


def _sorted_role_entries(role_entries_json: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    entries = [entry for entry in (role_entries_json or []) if isinstance(entry, dict)]
    return sorted(entries, key=lambda item: item.get("priority", 999))


def _extract_application_roles(application_row: dict[str, Any]) -> list[dict[str, Any]]:
    roles: list[dict[str, Any]] = []

    primary_role = _normalize_role_code(application_row.get("primary_role"))
    additional_roles = application_row.get("additional_roles_json") or []

    if primary_role:
        roles.append(
            {
                "role": primary_role,
                "subrole": None,
                "is_primary": True,
                "priority": 0,
                "rank_value": None,
                "is_active": True,
            }
        )

    for raw_role in additional_roles:
        role_code = _normalize_role_code(raw_role)
        if not role_code:
            continue
        if any(existing["role"] == role_code for existing in roles):
            continue
        roles.append(
            {
                "role": role_code,
                "subrole": None,
                "is_primary": False,
                "priority": len(roles),
                "rank_value": None,
                "is_active": True,
            }
        )

    return roles


def _parsed_fields_from_application(application_row: dict[str, Any]) -> dict[str, Any]:
    submitted_at = application_row.get("submitted_at")
    return {
        "source_record_key": application_row.get("battle_tag_normalized") or application_row.get("battle_tag"),
        "display_name": application_row.get("battle_tag"),
        "battle_tag": application_row.get("battle_tag"),
        "submitted_at": submitted_at.isoformat() if isinstance(submitted_at, datetime) else None,
        "smurf_tags": application_row.get("smurf_tags_json") or [],
        "discord_nick": application_row.get("discord_nick"),
        "twitch_nick": application_row.get("twitch_nick"),
        "stream_pov": bool(application_row.get("stream_pov", False)),
        "notes": application_row.get("notes"),
        "source_roles": {
            "primary": application_row.get("primary_role"),
            "additional": application_row.get("additional_roles_json") or [],
        },
    }


def _upsert_registration_role(
    bind: sa.Connection,
    registration_role: sa.Table,
    *,
    registration_id: int,
    role: str,
    subrole: str | None,
    is_primary: bool,
    priority: int,
    rank_value: int | None,
    is_active: bool,
) -> None:
    existing = bind.execute(
        sa.select(registration_role.c.id).where(
            registration_role.c.registration_id == registration_id,
            registration_role.c.role == role,
        )
    ).scalar_one_or_none()

    values = {
        "subrole": subrole,
        "is_primary": is_primary,
        "priority": priority,
        "rank_value": rank_value,
        "is_active": is_active,
    }

    if existing is None:
        bind.execute(
            registration_role.insert().values(
                registration_id=registration_id,
                role=role,
                **values,
            )
        )
    else:
        bind.execute(
            registration_role.update()
            .where(registration_role.c.id == existing)
            .values(**values)
        )


def upgrade() -> None:
    op.add_column("registration", sa.Column("display_name", sa.String(length=255), nullable=True), schema="balancer")
    op.add_column(
        "registration",
        sa.Column("exclude_from_balancer", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="balancer",
    )
    op.add_column("registration", sa.Column("exclude_reason", sa.String(length=64), nullable=True), schema="balancer")
    op.add_column("registration", sa.Column("admin_notes", sa.Text(), nullable=True), schema="balancer")
    op.add_column(
        "registration",
        sa.Column("is_flex", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="balancer",
    )
    op.add_column("registration", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True), schema="balancer")
    op.add_column("registration", sa.Column("deleted_by", sa.BigInteger(), nullable=True), schema="balancer")
    op.add_column(
        "registration",
        sa.Column("balancer_profile_overridden_at", sa.DateTime(timezone=True), nullable=True),
        schema="balancer",
    )
    op.create_foreign_key(
        "fk_balancer_registration_deleted_by_auth_user",
        "registration",
        "user",
        ["deleted_by"],
        ["id"],
        source_schema="balancer",
        referent_schema="auth",
        ondelete="SET NULL",
    )

    op.add_column("registration_role", sa.Column("rank_value", sa.Integer(), nullable=True), schema="balancer")
    op.add_column(
        "registration_role",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        schema="balancer",
    )

    op.create_table(
        "registration_google_sheet_feed",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("sheet_id", sa.String(length=255), nullable=False),
        sa.Column("gid", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("auto_sync_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("auto_sync_interval_seconds", sa.Integer(), nullable=False, server_default=sa.text("300")),
        sa.Column("header_row_json", sa.JSON(), nullable=True),
        sa.Column("mapping_config_json", sa.JSON(), nullable=True),
        sa.Column("value_mapping_json", sa.JSON(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tournament_id", name="uq_balancer_registration_google_sheet_feed_tournament"),
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_registration_google_sheet_feed_tournament_id"),
        "registration_google_sheet_feed",
        ["tournament_id"],
        unique=False,
        schema="balancer",
    )

    op.create_table(
        "registration_google_sheet_binding",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feed_id", sa.BigInteger(), nullable=False),
        sa.Column("registration_id", sa.BigInteger(), nullable=False),
        sa.Column("source_record_key", sa.String(length=255), nullable=False),
        sa.Column("raw_row_json", sa.JSON(), nullable=True),
        sa.Column("parsed_fields_json", sa.JSON(), nullable=True),
        sa.Column("row_hash", sa.String(length=128), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["feed_id"], ["balancer.registration_google_sheet_feed.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["registration_id"], ["balancer.registration.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("feed_id", "source_record_key", name="uq_balancer_registration_google_sheet_binding_key"),
        sa.UniqueConstraint("registration_id", name="uq_balancer_registration_google_sheet_binding_registration"),
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_registration_google_sheet_binding_feed_id"),
        "registration_google_sheet_binding",
        ["feed_id"],
        unique=False,
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_registration_google_sheet_binding_registration_id"),
        "registration_google_sheet_binding",
        ["registration_id"],
        unique=False,
        schema="balancer",
    )

    op.drop_index("ix_registration_battle_tag", table_name="registration", schema="balancer")
    op.create_index(
        "uq_balancer_registration_tournament_tag_active",
        "registration",
        ["tournament_id", "battle_tag_normalized"],
        unique=True,
        schema="balancer",
        postgresql_where=sa.text("battle_tag_normalized IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_balancer_registration_tournament_active",
        "registration",
        ["tournament_id", "status", "exclude_from_balancer"],
        unique=False,
        schema="balancer",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    bind = op.get_bind()
    metadata = sa.MetaData()

    registration = sa.Table("registration", metadata, autoload_with=bind, schema="balancer")
    registration_role = sa.Table("registration_role", metadata, autoload_with=bind, schema="balancer")
    google_sheet_feed = sa.Table("registration_google_sheet_feed", metadata, autoload_with=bind, schema="balancer")
    google_sheet_binding = sa.Table("registration_google_sheet_binding", metadata, autoload_with=bind, schema="balancer")
    tournament_sheet = sa.Table("tournament_sheet", metadata, autoload_with=bind, schema="balancer")
    application = sa.Table("application", metadata, autoload_with=bind, schema="balancer")
    player = sa.Table("player", metadata, autoload_with=bind, schema="balancer")
    tournament = sa.Table("tournament", metadata, autoload_with=bind, schema="tournament")
    workspace = sa.Table("workspace", metadata, autoload_with=bind)

    bind.execute(
        registration.update()
        .where(registration.c.display_name.is_(None))
        .values(display_name=registration.c.battle_tag)
    )

    feed_id_by_legacy_sheet_id: dict[int, int] = {}
    legacy_sheet_rows = bind.execute(
        sa.select(tournament_sheet).order_by(tournament_sheet.c.id.asc())
    ).mappings()
    for sheet_row in legacy_sheet_rows:
        inserted_feed_id = bind.execute(
            google_sheet_feed.insert()
            .values(
                tournament_id=sheet_row["tournament_id"],
                source_url=sheet_row["source_url"],
                sheet_id=sheet_row["sheet_id"],
                gid=sheet_row["gid"],
                title=sheet_row["title"],
                auto_sync_enabled=False,
                auto_sync_interval_seconds=300,
                header_row_json=sheet_row["header_row_json"],
                mapping_config_json=_build_legacy_mapping_config(
                    sheet_row["column_mapping_json"],
                    sheet_row["header_row_json"],
                ),
                value_mapping_json=_build_legacy_value_mapping(sheet_row["role_mapping_json"]),
                last_synced_at=sheet_row["last_synced_at"],
                last_sync_status=sheet_row["last_sync_status"],
                last_error=sheet_row["last_error"],
                created_at=sheet_row["created_at"],
                updated_at=sheet_row["updated_at"],
            )
            .returning(google_sheet_feed.c.id)
        ).scalar_one()
        feed_id_by_legacy_sheet_id[int(sheet_row["id"])] = int(inserted_feed_id)

    registration_role_rows = bind.execute(sa.select(registration_role)).mappings().all()
    existing_role_map: dict[tuple[int, str], dict[str, Any]] = {
        (int(row["registration_id"]), str(row["role"])): row for row in registration_role_rows
    }

    existing_registration_by_id: dict[int, dict[str, Any]] = {
        int(row["id"]): row
        for row in bind.execute(sa.select(registration)).mappings().all()
    }
    existing_registration_by_tag: dict[tuple[int, str], int] = {
        (int(row["tournament_id"]), str(row["battle_tag_normalized"])): int(row["id"])
        for row in existing_registration_by_id.values()
        if row["battle_tag_normalized"] and row["deleted_at"] is None
    }

    player_by_application_id: dict[int, dict[str, Any]] = {
        int(row["application_id"]): row
        for row in bind.execute(sa.select(player)).mappings().all()
    }
    tournament_rows = {
        int(row["id"]): row
        for row in bind.execute(sa.select(tournament)).mappings().all()
    }
    workspace_rows = {
        int(row["id"]): row
        for row in bind.execute(sa.select(workspace)).mappings().all()
    }

    application_rows = bind.execute(
        sa.select(application).order_by(application.c.id.asc())
    ).mappings()

    for application_row in application_rows:
        tournament_row = tournament_rows[int(application_row["tournament_id"])]
        workspace_row = workspace_rows[int(tournament_row["workspace_id"])]
        player_row = player_by_application_id.get(int(application_row["id"]))

        registration_id = None
        linked_registration_id = application_row["registration_id"]
        if linked_registration_id is not None and int(linked_registration_id) in existing_registration_by_id:
            registration_id = int(linked_registration_id)
        else:
            battle_tag_key = application_row["battle_tag_normalized"]
            if battle_tag_key:
                registration_id = existing_registration_by_tag.get((int(application_row["tournament_id"]), str(battle_tag_key)))

        if registration_id is None:
            initial_status = "approved" if application_row["is_active"] else "withdrawn"
            registration_id = int(
                bind.execute(
                    registration.insert()
                    .values(
                        tournament_id=application_row["tournament_id"],
                        workspace_id=tournament_row["workspace_id"],
                        auth_user_id=None,
                        user_id=player_row["user_id"] if player_row else None,
                        display_name=application_row["battle_tag"],
                        battle_tag=application_row["battle_tag"],
                        battle_tag_normalized=application_row["battle_tag_normalized"],
                        smurf_tags_json=application_row["smurf_tags_json"],
                        discord_nick=application_row["discord_nick"],
                        twitch_nick=application_row["twitch_nick"],
                        stream_pov=application_row["stream_pov"],
                        notes=application_row["notes"],
                        exclude_from_balancer=False if (player_row is None or player_row["is_in_pool"]) else True,
                        exclude_reason=None if (player_row is None or player_row["is_in_pool"]) else "legacy_pool_excluded",
                        admin_notes=player_row["admin_notes"] if player_row else None,
                        is_flex=bool(player_row["is_flex"]) if player_row else False,
                        custom_fields_json=None,
                        status=initial_status,
                        submitted_at=application_row["submitted_at"] or application_row["created_at"] or datetime.now(timezone.utc),
                        reviewed_at=None,
                        reviewed_by=None,
                        deleted_at=None,
                        deleted_by=None,
                        balancer_profile_overridden_at=None,
                    )
                    .returning(registration.c.id)
                ).scalar_one()
            )
            existing_registration_by_id[registration_id] = bind.execute(
                sa.select(registration).where(registration.c.id == registration_id)
            ).mappings().one()
            if application_row["battle_tag_normalized"]:
                existing_registration_by_tag[
                    (int(application_row["tournament_id"]), str(application_row["battle_tag_normalized"]))
                ] = registration_id
        else:
            update_values: dict[str, Any] = {}
            existing_registration = existing_registration_by_id[registration_id]
            if not existing_registration.get("display_name") and application_row["battle_tag"]:
                update_values["display_name"] = application_row["battle_tag"]
            for field_name in ("battle_tag", "battle_tag_normalized", "discord_nick", "twitch_nick", "notes"):
                if not existing_registration.get(field_name) and application_row.get(field_name) is not None:
                    update_values[field_name] = application_row[field_name]
            if not existing_registration.get("smurf_tags_json") and application_row.get("smurf_tags_json"):
                update_values["smurf_tags_json"] = application_row["smurf_tags_json"]
            if not existing_registration.get("admin_notes") and player_row and player_row.get("admin_notes"):
                update_values["admin_notes"] = player_row["admin_notes"]
            if not existing_registration.get("user_id") and player_row and player_row.get("user_id") is not None:
                update_values["user_id"] = player_row["user_id"]
            if not existing_registration.get("is_flex") and player_row and player_row.get("is_flex"):
                update_values["is_flex"] = True
            if existing_registration.get("status") == "approved" and not application_row["is_active"]:
                update_values["status"] = "withdrawn"
            if player_row and not player_row["is_in_pool"] and not existing_registration.get("exclude_from_balancer"):
                update_values["exclude_from_balancer"] = True
                update_values["exclude_reason"] = "legacy_pool_excluded"
            if update_values:
                bind.execute(
                    registration.update()
                    .where(registration.c.id == registration_id)
                    .values(**update_values)
                )
                existing_registration_by_id[registration_id] = bind.execute(
                    sa.select(registration).where(registration.c.id == registration_id)
                ).mappings().one()

        if application_row["registration_id"] != registration_id:
            bind.execute(
                application.update()
                .where(application.c.id == application_row["id"])
                .values(registration_id=registration_id)
            )

        role_payloads = []
        if player_row and player_row.get("role_entries_json"):
            for index, entry in enumerate(_sorted_role_entries(player_row["role_entries_json"])):
                role_code = _normalize_role_code(entry.get("role"))
                if not role_code:
                    continue
                rank_value = entry.get("rank_value")
                if rank_value is None:
                    rank_value = _resolve_rank_from_division_number(
                        entry.get("division_number"),
                        tournament_row.get("division_grid_json"),
                        workspace_row.get("division_grid_json"),
                    )
                role_payloads.append(
                    {
                        "role": role_code,
                        "subrole": entry.get("subtype"),
                        "is_primary": bool(index == 0 or role_code == _normalize_role_code(player_row.get("primary_role"))),
                        "priority": int(entry.get("priority", index)),
                        "rank_value": rank_value,
                        "is_active": bool(entry.get("is_active", True)),
                    }
                )
        else:
            role_payloads = _extract_application_roles(application_row)

        if not role_payloads:
            continue

        for role_payload in role_payloads:
            role_key = (registration_id, role_payload["role"])
            existing_role = existing_role_map.get(role_key)
            if existing_role is None:
                _upsert_registration_role(
                    bind,
                    registration_role,
                    registration_id=registration_id,
                    role=role_payload["role"],
                    subrole=role_payload["subrole"],
                    is_primary=role_payload["is_primary"],
                    priority=role_payload["priority"],
                    rank_value=role_payload["rank_value"],
                    is_active=role_payload["is_active"],
                )
                existing_role_map[role_key] = {
                    "registration_id": registration_id,
                    "role": role_payload["role"],
                }
            else:
                bind.execute(
                    registration_role.update()
                    .where(registration_role.c.id == existing_role["id"])
                    .values(
                        subrole=role_payload["subrole"],
                        is_primary=role_payload["is_primary"],
                        priority=role_payload["priority"],
                        rank_value=role_payload["rank_value"],
                        is_active=role_payload["is_active"],
                    )
                )

        feed_id = feed_id_by_legacy_sheet_id.get(int(application_row["tournament_sheet_id"]))
        if feed_id is None:
            continue

        source_record_key = application_row["battle_tag_normalized"] or application_row["battle_tag"] or f"legacy-{application_row['id']}"
        existing_binding_id = bind.execute(
            sa.select(google_sheet_binding.c.id).where(
                google_sheet_binding.c.registration_id == registration_id
            )
        ).scalar_one_or_none()
        binding_values = {
            "feed_id": feed_id,
            "registration_id": registration_id,
            "source_record_key": source_record_key,
            "raw_row_json": application_row["raw_row_json"],
            "parsed_fields_json": _parsed_fields_from_application(application_row),
            "row_hash": None,
            "last_seen_at": application_row["synced_at"] or application_row["updated_at"] or application_row["created_at"],
        }
        if existing_binding_id is None:
            bind.execute(google_sheet_binding.insert().values(**binding_values))
        else:
            bind.execute(
                google_sheet_binding.update()
                .where(google_sheet_binding.c.id == existing_binding_id)
                .values(**binding_values)
            )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_balancer_registration_google_sheet_binding_registration_id"),
        table_name="registration_google_sheet_binding",
        schema="balancer",
    )
    op.drop_index(
        op.f("ix_balancer_registration_google_sheet_binding_feed_id"),
        table_name="registration_google_sheet_binding",
        schema="balancer",
    )
    op.drop_table("registration_google_sheet_binding", schema="balancer")

    op.drop_index(
        op.f("ix_balancer_registration_google_sheet_feed_tournament_id"),
        table_name="registration_google_sheet_feed",
        schema="balancer",
    )
    op.drop_table("registration_google_sheet_feed", schema="balancer")

    op.drop_index("ix_balancer_registration_tournament_active", table_name="registration", schema="balancer")
    op.drop_index("uq_balancer_registration_tournament_tag_active", table_name="registration", schema="balancer")
    op.create_index(
        "ix_registration_battle_tag",
        "registration",
        ["tournament_id", "battle_tag_normalized"],
        unique=False,
        schema="balancer",
        postgresql_where=sa.text("battle_tag_normalized IS NOT NULL"),
    )

    op.drop_constraint("fk_balancer_registration_deleted_by_auth_user", "registration", schema="balancer", type_="foreignkey")
    op.drop_column("registration_role", "is_active", schema="balancer")
    op.drop_column("registration_role", "rank_value", schema="balancer")

    op.drop_column("registration", "balancer_profile_overridden_at", schema="balancer")
    op.drop_column("registration", "deleted_by", schema="balancer")
    op.drop_column("registration", "deleted_at", schema="balancer")
    op.drop_column("registration", "is_flex", schema="balancer")
    op.drop_column("registration", "admin_notes", schema="balancer")
    op.drop_column("registration", "exclude_reason", schema="balancer")
    op.drop_column("registration", "exclude_from_balancer", schema="balancer")
    op.drop_column("registration", "display_name", schema="balancer")
