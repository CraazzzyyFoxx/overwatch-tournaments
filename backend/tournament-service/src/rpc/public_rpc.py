"""Public / captain tournament methods over typed RPC.

Serialization:
- captain handlers return custom dicts verbatim.
- registration handlers return plain ``model_dump(mode="json")`` (nulls kept);
  ``RegistrationFormRead | None`` and ``RegistrationRead | None`` may serialize
  to ``None``.
- saved-view writes return ``model_dump(mode="json", exclude_none=True)``; the
  delete returns None.

Commit semantics: every write service called here commits internally
(captain.submit_team_report,
pick_ban_action.perform_pick_ban_action, reg_service.create/update/withdraw/check_in,
encounter service.create_saved_view/delete_saved_view), so the handlers add no
extra commit. The admission gate (``assert_admitted_at``) commits too, before
any write: its provider calls never run inside an open transaction. The
pick-ban state read commits nothing at all: it is a pure read, and the room's
healing belongs to ``encounter.room_reconcile``.

The gateway passes path params as ``data["<name>"]`` (and the primary id as
``data["id"]`` when the RouteSpec sets IDParam), query params as
``data["query"][key] = [values]``, and the JSON body as ``data["payload"]``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from faststream.rabbit import Channel
from faststream.rabbit.annotations import RabbitMessage

from shared import models
from shared.core.enums import PickBanKind, SubscriptionCollectionSource
from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import identity_provider
from shared.rpc.identity import rehydrate_user
from shared.services.chat import (
    HISTORY_DEFAULT,
    ChatMuteInput,
    ChatPostInput,
    ChatRoom,
    ChatSettingsInput,
)
from shared.services.encounter.participants import active_teams
from shared.services.subscriptions.realtime import emit_subscriptions_updated
from shared.services.subscriptions.wiring import build_store
from shared.services.tournament.visibility import ensure_tournament_viewable
from src import schemas
from src.core import db
from src.core.clients import subscription_resolver
from src.rpc._helpers import (
    _dump,
    _identity,
    _path_int,
    _payload,
    _q1,
    _require_id,
    _require_q1,
    _run,
)
from src.schemas.captain import (
    ElectOpenerInput,
    GameClaimIn,
    GameMapSelectInput,
    PickBanActionInput,
    PickBanSubmitInput,
    PickBanUndoInput,
    TeamReportIn,
)
from src.schemas.registration import (
    RegistrationStatusResponse,
    RegistrationSubmit,
    RegistrationUpdate,
    SubscriptionRedeemRequest,
)
from src.schemas.registration_team import (
    RegistrationFreeAgentListResponse,
    RegistrationTeamAcceptRequest,
    RegistrationTeamCheckInRequest,
    RegistrationTeamCreateRequest,
    RegistrationTeamDeclineRequest,
    RegistrationTeamExtendInviteRequest,
    RegistrationTeamInviteCreateRequest,
    RegistrationTeamInviteOfferListResponse,
    RegistrationTeamListResponse,
    RegistrationTeamPlaceMemberRequest,
    RegistrationTeamRedeemSubscriptionRequest,
    RegistrationTeamRenameRequest,
    RegistrationTeamSetManagerRequest,
    serialize_invite,
)
from src.services import visibility_resolvers
from src.services.admission import AdmissionStage
from src.services.bracket.usability import assert_encounter_live
from src.services.encounter import flows as encounter_flows
from src.services.encounter import pick_ban_action as pick_ban_action
from src.services.encounter.captain import ReportResultIn, captain_service, resolve_optional_viewer
from src.services.encounter.chat_access import encounter_chat_service
from src.services.encounter.games import encounter_game_service
from src.services.encounter.map_report import ClaimResultIn, map_report_service
from src.services.encounter.pick_ban_session import pick_ban_session_service
from src.services.encounter.pick_ban_undo import pick_ban_undo_service
from src.services.encounter.replay_codes import replay_codes_by_encounter
from src.services.encounter.report_form import report_form_service
from src.services.encounter.room_owner import ensure_room_viewable, load_room_encounter
from src.services.registration import _common as reg_common
from src.services.registration import audit as reg_audit
from src.services.registration import public_list
from src.services.registration import service as reg_service
from src.services.registration import teams as team_service
from src.services.registration.admission import assert_admitted_at
from src.services.registration.answers import answer_service
from src.services.registration.read_model import AdmissionChips, _resolve_top_heroes_config
from src.services.registration.recheck import assert_recheck_allowed, recheck_registration
from src.services.registration.subscription_codes import redeem_challenge_code
from src.services.registration.subscription_status import (
    assert_redeem_attempt_allowed,
    subscription_status_for_user,
)

# --- helpers -----------------------------------------------------------------


def _optional_identity(data: dict[str, Any]) -> models.AuthUser | None:
    """Rehydrate identity for AuthOptional routes; None when anonymous.

    The gateway injects ``identity`` only when a valid token is present on an
    AuthOptional route, so the absence of the key means the caller is anonymous.
    """
    if not data.get("identity"):
        return None
    return rehydrate_user(data.get("identity"))


def register(broker: Any, logger: Any) -> None:
    # ── captain: identity / result submission ─────────────────────────────

    @broker.subscriber("rpc.tournament.captain_my_role")
    async def _captain_my_role(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            encounter = await captain_service._load_encounter(session, encounter_id)
            try:
                participation, _player_id = await captain_service.captain_seat(session, user, encounter)
            except HTTPException:
                return {"encounter_team_id": None, "slot": None}
            return {"encounter_team_id": participation.id, "slot": participation.slot}

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_submit_report")
    async def _captain_submit_report(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            body = TeamReportIn.model_validate(_payload(data))
            encounter = await captain_service._load_encounter(session, encounter_id)
            # The reporter is the CALLER's seat, never the body's: a captain
            # files their own report and nobody else's.
            participation, player_id = await captain_service.captain_seat(session, user, encounter)
            # submit_team_report commits internally.
            encounter = await captain_service.submit_team_report(
                session,
                encounter_id,
                encounter_team_id=participation.id,
                reporter_user_id=player_id,
                games_played=body.games_played,
                results=[
                    ReportResultIn(
                        encounter_team_id=line.encounter_team_id,
                        score=line.score,
                        placement=line.placement,
                        wins=line.wins,
                    )
                    for line in body.results
                ],
                basis_version=body.basis_version,
                closeness=body.closeness,
                comment=body.comment,
                custom_fields=body.custom_fields,
                map_codes=[(mc.map_index, mc.code) for mc in body.map_codes],
                actor_auth_user_id=user.id,
            )
            reports = await captain_service.get_encounter_reports(session, encounter_id)
            return {
                "id": encounter.id,
                "result_status": encounter.result_status,
                "status": encounter.status,
                "result_source": encounter.result_source,
                "result_version": encounter.result_version,
                "teams": [
                    {"encounter_team_id": seat.id, "score": seat.score, "placement": seat.placement}
                    for seat in await active_teams(session, encounter.id)
                ],
                "closeness": encounter.closeness,
                "reports": reports,
            }

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_reports")
    async def _captain_reports(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Public read: reports are visible to anyone who can view the encounter.
            encounter_id = _require_id(data)
            tournament_id = await visibility_resolvers.visibility_resolvers_service.tournament_id_for_encounter(
                session, encounter_id
            )
            await ensure_tournament_viewable(session, _optional_identity(data), tournament_id)
            # The form config rides this envelope so the report dialog opens with
            # exactly the rules the submit endpoint will enforce, in one round trip.
            return {
                "reports": await captain_service.get_encounter_reports(session, encounter_id),
                "replay_codes": _dump((await replay_codes_by_encounter(session, [encounter_id])).get(encounter_id, [])),
                "form": _dump(await report_form_service.resolve_report_form(session, tournament_id)),
            }

        return await _run(logger, op)

    def _parse_kind(data: dict) -> PickBanKind:
        raw = data.get("kind")
        if raw not in ("map", "hero"):
            raise HTTPException(status_code=422, detail="kind must be 'map' or 'hero'")
        return PickBanKind(raw)

    @broker.subscriber("rpc.tournament.captain_pick_ban_state")
    async def _captain_pick_ban_state(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            kind = _parse_kind(data)
            encounter_id = _require_id(data)
            user = _optional_identity(data)
            encounter = await load_room_encounter(session, encounter_id, for_update=False)
            await ensure_room_viewable(session, user, encounter)
            viewer, viewer_member = await resolve_optional_viewer(session, user, encounter)
            return await pick_ban_action.pick_ban_action_service.get_pick_ban_state(
                session, encounter_id, kind, viewer=viewer, viewer_member=viewer_member
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_pick_ban_act")
    async def _captain_pick_ban_act(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            kind = _parse_kind(data)
            user = _identity(data)
            encounter_id = _require_id(data)
            body = PickBanActionInput.model_validate(_payload(data))
            encounter = await load_room_encounter(session, encounter_id, for_update=True)
            participation, is_captain, own = await captain_service.acting_seat(session, user, encounter, body.member_id)
            # Returns the acting captain's own new state, read as the GET reads
            # it (their own seat first): the room re-renders from the response
            # instead of racing its own refetch.
            state = await pick_ban_action.pick_ban_action_service.perform_pick_ban_action(
                session,
                encounter_id,
                kind,
                participation.id,
                item_id=body.item_id,
                action=body.action,
                target_player_id=body.target_player_id,
                member_id=body.member_id,
                viewer_member=own,
                actor_auth_user_id=user.id,
                locked_encounter=encounter,
            )
            if is_captain:
                return state
            # A member who is not the captain reads the room as themselves, never as their team's captain.
            return await pick_ban_action.pick_ban_action_service.get_pick_ban_state(
                session, encounter_id, kind, viewer=None, viewer_member=own
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_pick_ban_submit")
    async def _captain_pick_ban_submit(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            kind = _parse_kind(data)
            user = _identity(data)
            encounter_id = _require_id(data)
            body = PickBanSubmitInput.model_validate(_payload(data))
            encounter = await load_room_encounter(session, encounter_id, for_update=True)
            participation, _is_captain, own = await captain_service.acting_seat(session, user, encounter, None)
            return await pick_ban_action.pick_ban_action_service.submit_items(
                session,
                encounter_id,
                kind,
                participation.id,
                items=[item.model_dump() for item in body.items],
                lock=body.lock,
                viewer_member=own,
                actor_auth_user_id=user.id,
                locked_encounter=encounter,
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_pick_ban_dispute")
    async def _captain_pick_ban_dispute(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            kind = _parse_kind(data)
            user = _identity(data)
            encounter_id = _require_id(data)
            encounter = await load_room_encounter(session, encounter_id, for_update=True)
            participation, _player_id = await captain_service.captain_seat(session, user, encounter)
            return await pick_ban_action.pick_ban_action_service.dispute_step(
                session, encounter_id, kind, participation.id, actor_auth_user_id=user.id, locked_encounter=encounter
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_pick_ban_elect_opener")
    async def _captain_pick_ban_elect_opener(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            kind = _parse_kind(data)
            user = _identity(data)
            encounter_id = _require_id(data)
            body = ElectOpenerInput.model_validate(_payload(data))
            encounter = await load_room_encounter(session, encounter_id, for_update=True)
            participation, _player_id = await captain_service.captain_seat(session, user, encounter)
            pick_ban = await pick_ban_session_service.get_pick_ban_session(session, encounter_id, kind)
            if pick_ban is None:
                raise HTTPException(status_code=400, detail="No round is awaiting an opener choice")
            await pick_ban_session_service.elect_round_opener(
                session,
                pick_ban,
                first_team_id=body.first_team_id,
                acting_team_id=participation.id,
                actor_auth_user_id=user.id,
            )
            return await pick_ban_action.pick_ban_action_service.get_pick_ban_state(
                session, encounter_id, kind, viewer=participation.id
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_pick_ban_undo")
    async def _captain_pick_ban_undo(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            kind = _parse_kind(data)
            user = _identity(data)
            encounter_id = _require_id(data)
            body = PickBanUndoInput.model_validate(_payload(data))
            encounter = await load_room_encounter(session, encounter_id, for_update=True)
            participation, _player_id = await captain_service.captain_seat(session, user, encounter)
            # Commits internally; returns the resulting undo block (empty
            # `item_ids` once the undo landed and the step it restored is open
            # again).
            return await pick_ban_undo_service.perform_undo(
                session, encounter_id, kind, participation.id, consent=body.consent, actor_auth_user_id=user.id
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_report_game")
    async def _captain_report_game(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            game_id = _path_int(data, "game_id")
            body = GameClaimIn.model_validate(_payload(data))
            encounter = await captain_service._load_encounter(session, encounter_id)
            # The claimant is the CALLER's seat, never the body's: a captain
            # files their own claim and nobody else's.
            participation, player_id = await captain_service.captain_seat(session, user, encounter)
            # Commits internally once every live participation has claimed.
            return await map_report_service.submit_game_claim(
                session,
                game_id,
                claimant_team_id=participation.id,
                reporter_user_id=player_id,
                results=[
                    ClaimResultIn(
                        encounter_team_id=line.encounter_team_id,
                        score=line.score,
                        placement=line.placement,
                        column_values=dict(line.column_values),
                    )
                    for line in body.results
                ],
                basis_version=body.basis_version,
                actor_auth_user_id=user.id,
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_select_game_map")
    async def _captain_select_game_map(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            game_id = _path_int(data, "game_id")
            body = GameMapSelectInput.model_validate(_payload(data))
            encounter = await captain_service._load_encounter(session, encounter_id)
            await assert_encounter_live(session, encounter)
            await captain_service.captain_seat(session, user, encounter)
            # Locked for the same reason a claim locks it: two captains naming a
            # map at once must not both win.
            game = await encounter_game_service.get_game(session, game_id, for_update=True)
            if game is None or game.encounter_id != encounter.id:
                raise HTTPException(status_code=404, detail="Game not found")
            await encounter_game_service.select_map(session, encounter, game, map_id=body.map_id)
            await session.commit()
            lines = (await encounter_game_service.lines_by_game(session, [game])).get(game.id) or []
            claims = (await encounter_game_service.claim_payloads(session, [game]))[game.id]
            return {"game": encounter_game_service.serialize(game, lines, claims)}

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_ready")
    async def _captain_ready(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            encounter = await load_room_encounter(session, encounter_id, for_update=True)
            await assert_encounter_live(session, encounter)
            participation, captain_user_id = await captain_service.captain_seat(session, user, encounter)
            # mark_ready commits internally and signals the other captains'
            # rooms -- nothing polls it while no session exists.
            readiness = await pick_ban_session_service.mark_ready(
                session, encounter, participation.id, captain_user_id, actor_auth_user_id=user.id
            )
            return {"readiness": readiness}

        return await _run(logger, op)

    # ── pre-game room chat (shared room-chat service, chat_* tables) ──────

    @broker.subscriber("rpc.tournament.encounter_chat_history")
    async def _encounter_chat_history(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # AuthOptional: spectators read this room when an organizer has
            # opened it, so an absent identity is a caller, not an error.
            user = _optional_identity(data)
            room = ChatRoom.encounter(_require_id(data))
            envelope = await encounter_chat_service.envelope(
                session,
                user,
                room,
                after_id=_q1(data, "after_id", int),
                limit=_q1(data, "limit", int, HISTORY_DEFAULT),
            )
            return envelope.model_dump(mode="json")

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.encounter_chat_post")
    async def _encounter_chat_post(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            room = ChatRoom.encounter(_require_id(data))
            body = ChatPostInput.model_validate(_payload(data))
            # ChatService commits internally, here and in every write below.
            message = await encounter_chat_service.post(session, user, room, body.body)
            return message.model_dump(mode="json")

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.encounter_chat_delete")
    async def _encounter_chat_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            room = ChatRoom.encounter(_require_id(data))
            await encounter_chat_service.delete(session, user, room, _path_int(data, "message_id"))
            return {"deleted": True}

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.encounter_chat_settings")
    async def _encounter_chat_settings(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            room = ChatRoom.encounter(_require_id(data))
            body = ChatSettingsInput.model_validate(_payload(data))
            settings_read = await encounter_chat_service.set_settings(
                session, user, room, spectators_can_read=body.spectators_can_read
            )
            return settings_read.model_dump(mode="json")

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.encounter_chat_mute_set")
    async def _encounter_chat_mute_set(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            room = ChatRoom.encounter(_require_id(data))
            body = ChatMuteInput.model_validate(_payload(data))
            mute = await encounter_chat_service.set_mute(
                session,
                user,
                room,
                _path_int(data, "target_user_id"),
                minutes=body.minutes,
                reason=body.reason,
            )
            return mute.model_dump(mode="json")

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.encounter_chat_mute_clear")
    async def _encounter_chat_mute_clear(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            room = ChatRoom.encounter(_require_id(data))
            await encounter_chat_service.clear_mute(session, user, room, _path_int(data, "target_user_id"))
            return {"deleted": True}

        return await _run(logger, op)

    # ── public registration (user sign-up) ────────────────────────────────

    @broker.subscriber("rpc.tournament.reg_pub_form")
    async def _reg_pub_form(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Public route — no identity required, but hidden tournaments 404.
            tournament_id = _path_int(data, "tournament_id")
            await ensure_tournament_viewable(session, _optional_identity(data), tournament_id)
            return _dump(await reg_service.registration_service.get_public_form(session, tournament_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_create")
    async def _reg_pub_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await ensure_tournament_viewable(session, user, tournament_id)
            body = RegistrationSubmit.model_validate(_payload(data))
            form = await reg_common._common_service.get_registration_form(session, tournament_id)

            # Admission gate, sign-up stage. Every requirement the tournament armed
            # at `registration` is asked here, in one call; a requirement staged at
            # check-in stays silent by construction rather than by this handler
            # omitting a call. There is no row yet, hence `registration=None` and the
            # acting user as the subject. It commits: no provider call runs inside
            # this request's transaction, and a refusal keeps its fresh verdict.
            #
            # Only `blockers` refuses (see `assert_admitted_at`): a rowless subject
            # is never `ready`, so its `decision` is `not_admitted` and means nothing
            # here. Blocks only what can be decided WITHOUT the patron typing
            # anything -- a provider still satisfiable by a challenge code is
            # deferred to check-in, where that field exists.
            await assert_admitted_at(
                session,
                None,
                tournament_id=tournament_id,
                auth_user_id=user.id,
                stage=AdmissionStage.registration,
                form=form,
            )

            # Full use-case (validation, duplicate check, create, serialize)
            # lives in the service layer; commits internally.
            return _dump(
                await reg_service.registration_service.submit_public_registration(
                    session, tournament_id=tournament_id, auth_user=user, body=body, form=form
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_get_me")
    async def _reg_pub_get_me(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await ensure_tournament_viewable(session, user, tournament_id)
            reg = await reg_service.registration_service.get_registration(session, tournament_id, user.id)
            if reg is None:
                return None
            form = await reg_common._common_service.get_registration_form(session, tournament_id)
            # The registrant's own card goes through the SAME resolver as the
            # participants list and the admin table -- one batch of one row -- so
            # "why am I not admitted" answers identically on every surface.
            admissions = await reg_service.registration_service.resolve_admission_list(session, [reg], form=form)
            return _dump(
                await reg_service.registration_service.build_own_read(
                    session, reg, form=form, chips=AdmissionChips.of(admissions.get(reg.id))
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_update_me")
    async def _reg_pub_update_me(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await ensure_tournament_viewable(session, user, tournament_id)
            body = RegistrationUpdate.model_validate(_payload(data))

            form = await reg_common._common_service.get_registration_form(session, tournament_id)
            if form is None:
                raise HTTPException(status_code=404, detail="Registration form not found")

            reg = await reg_service.registration_service.get_registration(session, tournament_id, user.id)
            if reg is None:
                raise HTTPException(status_code=404, detail="No registration found")

            provider = identity_provider(reg.tournament.discipline)
            schema = reg_service._require_current_schema(form, body.form_version_id)
            hero_catalog, _ = await _resolve_top_heroes_config(session, form, discipline=reg.tournament.discipline)
            values = await answer_service.validate(
                session,
                schema=schema,
                answers=body.answers,
                partial=True,
                enforce_required=True,
                # get_registration eager-loads workspace_member, the
                # registration's only identity anchor.
                player_id=reg.workspace_member.player_id if reg.workspace_member is not None else None,
                workspace_id=form.workspace_id,
                discipline=reg.tournament.discipline,
                hero_catalog=hero_catalog,
                registration=reg,
            )

            # update_registration commits internally, so the audit row is staged
            # BEFORE it and rides the same transaction -- a refused edit leaves no
            # trail of having happened. Same ordering rule the admin RPC follows.
            before, after = reg_audit.profile_changes(reg, {"answers": values})
            if before or after:
                await reg_audit.audit_service.stage(
                    session,
                    action="registration.self_update",
                    actor=user,
                    workspace_id=form.workspace_id,
                    data=data,
                    entity_id=reg.id,
                    entity_label=reg_audit.label(reg, provider=provider),
                    source="player",
                    before=before,
                    after=after,
                )

            updated = await reg_service.registration_service.update_registration(
                session,
                reg,
                tournament=reg.tournament,
                values=values,
                schema=schema,
                hero_catalog=hero_catalog,
                form_version_id=form.current_version_id,
            )
            return _dump(await reg_service.registration_service.build_own_read(session, updated, form=form))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_withdraw_me")
    async def _reg_pub_withdraw_me(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await ensure_tournament_viewable(session, user, tournament_id)
            reg = await reg_service.registration_service.get_registration(session, tournament_id, user.id)
            if reg is None:
                raise HTTPException(status_code=404, detail="No registration found")
            # withdraw_registration commits internally.
            await reg_service.registration_service.withdraw_registration(session, reg)
            return _dump(RegistrationStatusResponse(status="withdrawn", message="Registration withdrawn"))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_check_in")
    async def _reg_pub_check_in(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await ensure_tournament_viewable(session, user, tournament_id)
            reg = await reg_service.registration_service.get_registration(session, tournament_id, user.id)
            if reg is None:
                raise HTTPException(status_code=404, detail="No registration found")
            form = await reg_common._common_service.get_registration_form(session, tournament_id)

            # Admission gate, check-in stage: ONE call, every requirement armed at
            # check-in. Only a CONFIRMED refusal blocks, so a provider outage or a
            # BattleTag nobody has polled yet can never lock somebody out of a live
            # check-in. It commits (see `assert_admitted_at`).
            #
            # The admin path (`registration_admin.py::_reg_check_in`) has NO gate: it
            # IS the organizer's override, and `AdmissionEvaluation.overridden` is what
            # makes using it visible instead of the badge re-deriving a refusal
            # forever. Do not add a gate there, nor an `override=True` parameter here.
            await assert_admitted_at(
                session,
                reg,
                tournament_id=tournament_id,
                auth_user_id=user.id,
                stage=AdmissionStage.check_in,
                form=form,
            )

            # check_in_registration commits internally. The card it answers with is
            # now ``checked_in``, so its Edit affordance turns off with a reason
            # instead of silently vanishing on the next refetch.
            checked_in = await reg_service.registration_service.check_in_registration(
                session,
                reg,
                checked_in_by=user.id,
            )
            return _dump(await reg_service.registration_service.build_own_read(session, checked_in, form=form))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_recheck_me")
    async def _reg_pub_recheck_me(data: dict, msg: RabbitMessage) -> dict:
        """Re-check the caller's profile and subscriptions now, behind a cooldown.

        No body: the client refetches its registration, whose admission then
        carries the fresh subscription verdict (the profile one follows once
        stats-service has fetched the tags).
        """

        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await ensure_tournament_viewable(session, user, tournament_id)
            reg = await reg_service.registration_service.get_registration(session, tournament_id, user.id)
            if reg is None:
                raise HTTPException(status_code=404, detail="No registration found")
            await assert_recheck_allowed(auth_user_id=user.id)
            await recheck_registration(session, reg, auth_user_id=user.id)
            await session.commit()
            return None

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.sub_me")
    async def _sub_me(data: dict, msg: RabbitMessage) -> dict:
        """The caller's own subscription standing for this tournament.

        Read-only and non-forcing: the registration form polls it to render the
        per-provider chips, so it must not spend a provider call per page view.
        """

        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await ensure_tournament_viewable(session, user, tournament_id)
            form = await reg_common._common_service.get_registration_form(session, tournament_id)
            return _dump(
                await subscription_status_for_user(
                    form=form,
                    auth_user_id=user.id,
                    resolver=subscription_resolver(session),
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.sub_redeem_code")
    async def _sub_redeem_code(data: dict, msg: RabbitMessage) -> dict:
        """Redeem a challenge code published in a subscriber-only post.

        Rate-limited per user: this endpoint is a guessing oracle, and the codes
        are short enough to brute-force without a ceiling.
        """

        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await ensure_tournament_viewable(session, user, tournament_id)
            body = SubscriptionRedeemRequest.model_validate(_payload(data))
            form = await reg_common._common_service.get_registration_form(session, tournament_id)
            if form is None:
                raise HTTPException(status_code=404, detail="Registration form not found")

            await assert_redeem_attempt_allowed(workspace_id=form.workspace_id, auth_user_id=user.id)
            await redeem_challenge_code(
                store=build_store(session),
                workspace_id=form.workspace_id,
                auth_user_id=user.id,
                provider=body.provider,
                submitted_code=body.code,
            )
            # Redemption writes the entitlement straight through the store, so the
            # resolver's own signal never fires for it. Staged before the commit
            # that owns the write, like every other publisher.
            await emit_subscriptions_updated(
                session,
                form.workspace_id,
                trigger=SubscriptionCollectionSource.redeem,
            )
            await session.commit()
            return _dump(
                await subscription_status_for_user(
                    form=form,
                    auth_user_id=user.id,
                    resolver=subscription_resolver(session),
                )
            )

        return await _run(logger, op)

    # Isolated QoS: the participants list is the heaviest public read and fans
    # out to every connected viewer after each registration mutation (the
    # realtime invalidation herd). Prefetch 8 keeps a burst of list rebuilds to 8
    # of the process's RPC_PREFETCH_COUNT handler permits, so check-in/register
    # writes still get the rest.
    @broker.subscriber("rpc.tournament.reg_pub_list", channel=Channel(prefetch_count=8))
    async def _reg_pub_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Public route — no identity required. The visibility check is
            # viewer-dependent and runs on this call's own session; the expensive,
            # viewer-agnostic build is coalesced across concurrent callers on
            # sessions of their own, so this one's read-only transaction ends
            # before the wait instead of idling in it.
            tournament_id = _path_int(data, "tournament_id")
            await ensure_tournament_viewable(session, _optional_identity(data), tournament_id)
            await session.commit()
            return _dump(await public_list.coalesced_registration_list(db.async_session_maker, tournament_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_list_public")
    async def _regteam_list_public(data: dict, msg: RabbitMessage) -> dict:
        """The public "Teams" roster for a tournament.

        Distinct from the admin ``regteam_list``: invites are omitted for every
        team except one the caller themselves captains or manages — a public roster
        must not leak who else has been asked and declined, but staff reading their
        own outstanding offers is exactly the person `MyTeamPanel` needs this list
        to answer for. Only the caller's own rejected teams remain visible after
        rejection, so their captain can read the reason even after roster detachment.
        """

        async def op(session: Any) -> Any:
            tournament_id = _path_int(data, "tournament_id")
            user = _optional_identity(data)
            await ensure_tournament_viewable(session, user, tournament_id)
            teams = await team_service.teams_service.list_teams(
                session,
                tournament_id=tournament_id,
                include_terminal=False,
                include_terminal_for_auth_user_id=user.id if user is not None else None,
            )
            staffed = (
                await team_service.teams_service.staffed_team_ids(session, teams, user.id)
                if user is not None
                else set()
            )
            items = await team_service.teams_service.describe_teams(session, teams, private_team_ids=staffed)
            # Free agents ride along: a captain reading this list is exactly the
            # person who can recruit them.
            return _dump(
                RegistrationTeamListResponse(
                    items=items,
                    total=len(items),
                    unassigned_players=await team_service.teams_service.count_unassigned_players(
                        session, tournament_id
                    ),
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_invite_preview")
    async def _regteam_invite_preview(data: dict, msg: RabbitMessage) -> dict:
        """What a link invite says before the holder signs in.

        The only ANONYMOUS invite surface. That is deliberate: a link invite exists
        to reach someone with no account, and demanding they register before seeing
        what they were invited to is backwards. The token is the credential.

        No tournament visibility check: the invite is the grant. A captain of a
        private tournament handing out a link is exactly them choosing to admit
        someone, and running the viewer gate here would refuse the very person the
        link was minted for.
        """

        async def op(session: Any) -> Any:
            token = str(_payload(data).get("token") or "")
            return _dump(await team_service.teams_service.preview_invite(session, token=token))

        return await _run(logger, op)

    # ── public team registration (captain + invitee flows) ─────────────────
    #
    # Every handler here is a *public* surface: the invitee flows in particular are
    # reachable by anyone holding a link. The service layer owns the row lock, the
    # slot decision and the machine error codes; these handlers only translate
    # transport to arguments.

    @broker.subscriber("rpc.tournament.regteam_create")
    async def _regteam_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await ensure_tournament_viewable(session, user, tournament_id)
            body = RegistrationTeamCreateRequest.model_validate(_payload(data))

            # Same gate as solo registration, same stage: the captain is a registrant
            # like any other, so an unsubscribed account cannot slip in by founding a
            # team. The row does not exist yet -- `create_team` makes it below -- so
            # the acting user is the subject.
            await assert_admitted_at(
                session,
                None,
                tournament_id=tournament_id,
                auth_user_id=user.id,
                stage=AdmissionStage.registration,
            )

            team, _registration, issues = await team_service.teams_service.create_team(
                session,
                tournament_id=tournament_id,
                auth_user=user,
                name=body.name,
                slot_code=body.slot_code,
                body=body.registration,
            )
            # The captain sees their own outstanding offers; a public roster does not.
            return _dump(
                await team_service.teams_service.describe_team(session, team, include_invites=True, eligibility=issues)
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_invite")
    async def _regteam_invite(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            team_id = _path_int(data, "team_id")
            body = RegistrationTeamInviteCreateRequest.model_validate(_payload(data))
            ttl = timedelta(days=body.ttl_days) if body.ttl_days is not None else team_service.DEFAULT_INVITE_TTL
            invite, raw_token = await team_service.teams_service.invite_member(
                session,
                team_id=team_id,
                auth_user=user,
                slot_code=body.slot_code,
                is_substitute=body.is_substitute,
                target_registration_id=body.target_registration_id,
                ttl=ttl,
            )
            # The raw token is returned exactly once, here, and never stored or
            # re-served: only its sha256 is persisted.
            return _dump(serialize_invite(invite)) | {"token": raw_token}

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_invite_revoke")
    async def _regteam_invite_revoke(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            await team_service.teams_service.revoke_invite(
                session,
                invite_id=_path_int(data, "invite_id"),
                auth_user=user,
            )
            return None

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_free_agents")
    async def _regteam_free_agents(data: dict, msg: RabbitMessage) -> dict:
        """Who a captain may invite: registrants of this tournament on no team.

        Authenticated but not captain-gated. Everything returned is already on the
        public participants list, so a gate here would be theatre; the account
        requirement exists because the only use of this list is to act on it.
        Visibility-gated like that list (and every sibling public read in this
        file) so a hidden/preview-only tournament's registrant BattleTags stay
        behind the same wall as the rest of it.
        """

        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await ensure_tournament_viewable(session, user, tournament_id)
            items = await team_service.teams_service.list_free_agents(session, tournament_id)
            return _dump(RegistrationFreeAgentListResponse(items=items, total=len(items)))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_my_invites")
    async def _regteam_my_invites(data: dict, msg: RabbitMessage) -> dict:
        """Targeted invites addressed to the caller.

        Scoped to the caller server-side from their token — there is no id in the
        path to tamper with, because "whose invites" is never the client's answer.
        """

        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            items = await team_service.teams_service.list_my_invites(
                session, tournament_id=tournament_id, auth_user=user
            )
            return _dump(RegistrationTeamInviteOfferListResponse(items=items))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_invite_history_public")
    async def _regteam_invite_history_public(data: dict, msg: RabbitMessage) -> dict:
        """Staff reads their own team's full invite history.

        Authorized by captaincy or the manager flag, not by workspace permission —
        the organizer reads the same data through the admin handler. Nothing here
        is new to staff: they issued every row in it, or the captain did.

        Gated by :meth:`assert_staff_of_team`, which deliberately does NOT require
        the team to still be mutable: a rejected or exported team's history is
        exactly what someone opens this to understand.
        """

        async def op(session: Any) -> Any:
            user = _identity(data)
            team_id = _path_int(data, "team_id")
            team = await team_service.teams_service.assert_staff_of_team(session, team_id=team_id, auth_user=user)
            return _dump(
                await team_service.teams_service.list_invite_history(
                    session, team_id=team_id, tournament_id=team.tournament_id
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_accept")
    async def _regteam_accept(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            body = RegistrationTeamAcceptRequest.model_validate(_payload(data))
            # A newcomer passes the sign-up admission gate inside, before the team lock.
            team, _registration_id, issues = await team_service.teams_service.accept_invite(
                session,
                auth_user=user,
                body=body.registration,
                token=body.token,
                invite_id=body.invite_id,
            )
            # An invitee is now a member, so their own offers view is theirs to see.
            return _dump(
                await team_service.teams_service.describe_team(session, team, include_invites=True, eligibility=issues)
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_decline")
    async def _regteam_decline(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            body = RegistrationTeamDeclineRequest.model_validate(_payload(data) or {})
            await team_service.teams_service.decline_invite(
                session,
                auth_user=user,
                token=body.token,
                invite_id=body.invite_id,
            )
            return None

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_kick")
    async def _regteam_kick(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            await team_service.teams_service.kick_member(
                session,
                team_id=_path_int(data, "team_id"),
                registration_id=_path_int(data, "registration_id"),
                auth_user=user,
            )
            return None

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_leave")
    async def _regteam_leave(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            await team_service.teams_service.leave_team(session, team_id=_path_int(data, "team_id"), auth_user=user)
            return None

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_transfer_captain")
    async def _regteam_transfer_captain(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            await team_service.teams_service.transfer_captaincy(
                session,
                team_id=_path_int(data, "team_id"),
                registration_id=_path_int(data, "registration_id"),
                auth_user=user,
            )
            return None

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_disband")
    async def _regteam_disband(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            await team_service.teams_service.disband_team(session, team_id=_path_int(data, "team_id"), auth_user=user)
            return None

        return await _run(logger, op)

    async def _own_team_dump(session: Any, team: Any) -> Any:
        return _dump(await team_service.teams_service.describe_team(session, team, include_invites=True))

    @broker.subscriber("rpc.tournament.regteam_rename")
    async def _regteam_rename(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            body = RegistrationTeamRenameRequest.model_validate(_payload(data))
            team = await team_service.teams_service.rename_team(
                session,
                team_id=_path_int(data, "team_id"),
                auth_user=user,
                name=body.name,
            )
            return await _own_team_dump(session, team)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_place_member")
    async def _regteam_place_member(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            body = RegistrationTeamPlaceMemberRequest.model_validate(_payload(data) or {})
            team = await team_service.teams_service.place_member(
                session,
                team_id=_path_int(data, "team_id"),
                registration_id=_path_int(data, "registration_id"),
                auth_user=user,
                slot_code=body.slot_code,
                is_substitute=body.is_substitute,
                swap_with_registration_id=body.swap_with_registration_id,
            )
            return await _own_team_dump(session, team)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_set_manager")
    async def _regteam_set_manager(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            body = RegistrationTeamSetManagerRequest.model_validate(_payload(data) or {})
            team = await team_service.teams_service.set_member_manager(
                session,
                team_id=_path_int(data, "team_id"),
                registration_id=_path_int(data, "registration_id"),
                auth_user=user,
                is_manager=body.is_manager,
            )
            return await _own_team_dump(session, team)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_extend_invite")
    async def _regteam_extend_invite(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            body = RegistrationTeamExtendInviteRequest.model_validate(_payload(data) or {})
            ttl = timedelta(days=body.ttl_days) if body.ttl_days is not None else None
            invite, raw_token = await team_service.teams_service.extend_invite(
                session,
                team_id=_path_int(data, "team_id"),
                invite_id=_path_int(data, "invite_id"),
                auth_user=user,
                ttl=ttl,
                rotate_token=body.rotate_token,
            )
            return _dump(serialize_invite(invite)) | {"token": raw_token}

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_lock")
    async def _regteam_lock(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            team = await team_service.teams_service.lock_roster(
                session, team_id=_path_int(data, "team_id"), auth_user=user
            )
            return await _own_team_dump(session, team)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_check_in")
    async def _regteam_check_in(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            body = RegistrationTeamCheckInRequest.model_validate(_payload(data) or {})
            team = await team_service.teams_service.check_in_roster(
                session,
                team_id=_path_int(data, "team_id"),
                auth_user=user,
                exclude_registration_ids=body.exclude_registration_ids,
            )
            return await _own_team_dump(session, team)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_cover_subscription")
    async def _regteam_cover_subscription(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            body = RegistrationTeamRedeemSubscriptionRequest.model_validate(_payload(data) or {})
            team = await team_service.teams_service.cover_team_subscription(
                session,
                team_id=_path_int(data, "team_id"),
                auth_user=user,
                code=body.code,
                provider=body.provider,
            )
            return await _own_team_dump(session, team)

        return await _run(logger, op)

    # ── encounter saved-view writes ───────────────────────────────────────

    @broker.subscriber("rpc.tournament.saved_view_create")
    async def _saved_view_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _require_q1(data, "workspace_id", int)
            if not user.is_workspace_member(workspace_id):
                raise HTTPException(status_code=403, detail="Not a member of this workspace")
            body = schemas.EncounterSavedViewCreate.model_validate(_payload(data))
            # save_view commits internally.
            saved_view = await encounter_flows.flows_service.save_view(
                session,
                workspace_id=workspace_id,
                auth_user_id=user.id,
                data=body,
            )
            return _dump(saved_view, exclude_none=True)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.saved_view_delete")
    async def _saved_view_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            saved_view_id = _path_int(data, "saved_view_id")
            workspace_id = _require_q1(data, "workspace_id", int)
            if not user.is_workspace_member(workspace_id):
                raise HTTPException(status_code=403, detail="Not a member of this workspace")
            # delete_saved_view commits internally.
            await encounter_flows.flows_service.delete_saved_view(
                session,
                workspace_id=workspace_id,
                auth_user_id=user.id,
                saved_view_id=saved_view_id,
            )
            return None

        return await _run(logger, op)
