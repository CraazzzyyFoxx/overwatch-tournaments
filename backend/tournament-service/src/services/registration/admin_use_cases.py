from __future__ import annotations

import sqlalchemy as sa

from src import models


class GetRegistrationForm:
    async def execute(self, *, session, tournament_id: int):
        result = await session.execute(
            sa.select(models.BalancerRegistrationForm).where(
                models.BalancerRegistrationForm.tournament_id == tournament_id
            )
        )
        return result.scalar_one_or_none()


class UpsertRegistrationForm:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int, payload):
        tournament = await self._registration_service.ensure_tournament_exists(session, tournament_id)
        result = await session.execute(
            sa.select(models.BalancerRegistrationForm).where(
                models.BalancerRegistrationForm.tournament_id == tournament_id
            )
        )
        form = result.scalar_one_or_none()
        built_in_fields_json = {
            key: value.model_dump(exclude_none=True) for key, value in payload.built_in_fields.items()
        }
        custom_fields_json = [field.model_dump(exclude_none=True) for field in payload.custom_fields]

        if form is None:
            form = models.BalancerRegistrationForm(
                tournament_id=tournament_id,
                workspace_id=tournament.workspace_id,
                is_open=payload.is_open,
                auto_approve=payload.auto_approve,
                opens_at=payload.opens_at,
                closes_at=payload.closes_at,
                built_in_fields_json=built_in_fields_json,
                custom_fields_json=custom_fields_json,
            )
            session.add(form)
        else:
            form.is_open = payload.is_open
            form.auto_approve = payload.auto_approve
            form.opens_at = payload.opens_at
            form.closes_at = payload.closes_at
            form.built_in_fields_json = built_in_fields_json
            form.custom_fields_json = custom_fields_json

        await session.commit()
        await session.refresh(form)
        return form


class ListRegistrations:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(
        self,
        *,
        session,
        tournament_id: int,
        status_filter: str | None = None,
        inclusion_filter: str | None = None,
        source_filter: str | None = None,
        include_deleted: bool = False,
    ):
        return await self._registration_service.list_registrations(
            session,
            tournament_id,
            status_filter=status_filter,
            inclusion_filter=inclusion_filter,
            source_filter=source_filter,
            include_deleted=include_deleted,
        )


class CreateRegistration:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int, payload):
        await self._registration_service.ensure_tournament_exists(session, tournament_id)
        return await self._registration_service.create_manual_registration(
            session,
            tournament_id=tournament_id,
            display_name=payload.display_name,
            battle_tag=payload.battle_tag,
            smurf_tags_json=payload.smurf_tags_json,
            discord_nick=payload.discord_nick,
            twitch_nick=payload.twitch_nick,
            stream_pov=payload.stream_pov,
            notes=payload.notes,
            admin_notes=payload.admin_notes,
            roles=[role.model_dump() for role in payload.roles],
        )


class UpdateRegistration:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, registration_id: int, payload):
        return await self._registration_service.update_registration_profile(
            session,
            registration_id,
            display_name=payload.display_name,
            battle_tag=payload.battle_tag,
            smurf_tags_json=payload.smurf_tags_json,
            discord_nick=payload.discord_nick,
            twitch_nick=payload.twitch_nick,
            stream_pov=payload.stream_pov,
            notes=payload.notes,
            admin_notes=payload.admin_notes,
            status_value=payload.status,
            balancer_status_value=payload.balancer_status,
            roles=[role.model_dump() for role in payload.roles] if payload.roles is not None else None,
            exclude_from_balancer=payload.exclude_from_balancer,
            exclude_reason=payload.exclude_reason,
        )


class ApproveRegistration:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, registration_id: int, user):
        return await self._registration_service.approve_registration(
            session,
            registration_id,
            reviewed_by=user.id,
        )


class RejectRegistration:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, registration_id: int, user):
        return await self._registration_service.reject_registration(
            session,
            registration_id,
            reviewed_by=user.id,
        )


class SetRegistrationExclusion:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, registration_id: int, payload):
        return await self._registration_service.set_registration_exclusion(
            session,
            registration_id,
            exclude_from_balancer=payload.exclude_from_balancer,
            exclude_reason=payload.exclude_reason,
        )


class WithdrawRegistration:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, registration_id: int):
        return await self._registration_service.withdraw_registration(session, registration_id)


class RestoreRegistration:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, registration_id: int):
        return await self._registration_service.restore_registration(session, registration_id)


class DeleteRegistration:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, registration_id: int, user):
        await self._registration_service.soft_delete_registration(
            session,
            registration_id,
            deleted_by=user.id,
        )


class BulkApproveRegistrations:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int, registration_ids: list[int], user):
        return await self._registration_service.bulk_approve_registrations(
            session,
            tournament_id,
            registration_ids,
            reviewed_by=user.id,
        )


class SetBalancerStatus:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, registration_id: int, balancer_status: str):
        return await self._registration_service.set_balancer_status(
            session,
            registration_id,
            balancer_status=balancer_status,
        )


class BulkAddToBalancer:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int, registration_ids: list[int], balancer_status: str):
        return await self._registration_service.bulk_add_to_balancer(
            session,
            tournament_id,
            registration_ids,
            balancer_status=balancer_status,
        )


class ToggleCheckIn:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, registration_id: int, checked_in: bool, user):
        if checked_in:
            return await self._registration_service.check_in_registration(
                session,
                registration_id,
                checked_in_by=user.id,
            )
        return await self._registration_service.uncheck_in_registration(
            session,
            registration_id,
        )


class GetTournamentSheet:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int):
        return await self._registration_service.get_google_sheet_feed(session, tournament_id)


class UpsertTournamentSheet:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int, payload):
        return await self._registration_service.upsert_google_sheet_feed(
            session,
            tournament_id,
            source_url=payload.source_url,
            title=payload.title,
            auto_sync_enabled=payload.auto_sync_enabled,
            auto_sync_interval_seconds=payload.auto_sync_interval_seconds,
            mapping_config_json=payload.mapping_config_json,
            value_mapping_json=payload.value_mapping_json,
        )


class SyncTournamentSheet:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int):
        return await self._registration_service.sync_google_sheet_feed(session, tournament_id)


class SuggestTournamentSheetMapping:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int, payload):
        return await self._registration_service.suggest_google_sheet_mapping(
            session,
            tournament_id,
            source_url=payload.source_url,
        )


class PreviewTournamentSheetMapping:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int, payload):
        return await self._registration_service.preview_google_sheet_mapping(
            session,
            tournament_id,
            source_url=payload.source_url,
            mapping_config_json=payload.mapping_config_json,
            value_mapping_json=payload.value_mapping_json,
            sample_rows=getattr(payload, "sample_rows", 5),
        )


class ExportRegistrationsToUsers:
    def __init__(self, *, registration_service) -> None:
        self._registration_service = registration_service

    async def execute(self, *, session, tournament_id: int):
        return await self._registration_service.export_registrations_to_users(session, tournament_id)
