"""Public / captain tournament methods over typed RPC.

Each handler preserves the contract of the former HTTP route it replaced (the
``src/routes/`` HTTP service has been decommissioned): it rehydrates the
gateway-injected identity where a user was required, validates the SAME body
schema, calls the SAME service function with the SAME args, and serializes the
SAME way the route returned. The request schemas and read-model builders now
live in ``src/schemas/{captain,registration,registration_build}.py``.

Serialization parity:
- captain handlers return custom dicts -> returned verbatim.
- registration handlers do NOT use ``response_model_exclude_none`` -> plain
  ``model_dump(mode="json")`` (keep nulls). ``RegistrationFormRead | None`` and
  ``RegistrationRead | None`` may serialize to ``None``.
- saved-view writes DID use ``response_model_exclude_none=True`` ->
  ``model_dump(mode="json", exclude_none=True)``; the delete returns 204 -> None.

Commit semantics: every write service called here commits internally
(captain.submit_captain_report,
pick_ban_action.perform_pick_ban_action, reg_service.create/update/withdraw/check_in,
encounter service.upsert_saved_view/delete_saved_view), so the handlers add no
extra commit. The pick-ban state read also commits when it lazily creates the
encounter's session (pick_ban_session.ensure_pick_ban_session).


The gateway passes path params as ``data["<name>"]`` (and the primary id as
``data["id"]`` when the RouteSpec sets IDParam), query params as
``data["query"][key] = [values]``, and the JSON body as ``data["payload"]``.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from cashews import cache
from faststream.rabbit import Channel
from faststream.rabbit.annotations import RabbitMessage

from shared.balancer_registration_statuses import get_status_metas_map
from shared.balancer_subrole_catalog import resolve_subrole_catalog
from shared.core.enums import PickBanKind, SubscriptionCollectionSource
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import rehydrate_user
from shared.services.admission import AdmissionStage
from shared.services.subscriptions.realtime import emit_subscriptions_updated
from shared.services.subscriptions.wiring import build_resolver, build_store
from shared.services.tournament.visibility import assert_tournament_viewable
from src import models, schemas
from src.core import db
from src.core.broker import optional_broker
from src.core.config import settings
from src.rpc._helpers import (
    _dump,
    _identity,
    _path_int,
    _payload,
    _require_id,
    _require_q1,
    _run,
)
from src.schemas.captain import (
    CaptainReportSubmission,
    ElectOpenerInput,
    MapReportInput,
    PickBanActionInput,
    PickBanUndoInput,
    resolve_optional_viewer_side,
)
from src.schemas.registration import (
    RegistrationCreate,
    RegistrationStatusResponse,
    RegistrationUpdate,
    SubscriptionRedeemRequest,
)
from src.schemas.registration_build import (
    AdmissionChips,
    _form_to_read,
    _public_rosters,
    _reg_to_read,
    _resolve_tournament_workspace,
)
from src.schemas.registration_team import (
    RegistrationFreeAgentListResponse,
    RegistrationTeamAcceptRequest,
    RegistrationTeamCreateRequest,
    RegistrationTeamInviteCreateRequest,
    RegistrationTeamInviteOfferListResponse,
    RegistrationTeamListResponse,
    serialize_invite,
)
from src.services import visibility_resolvers
from src.services.encounter import flows as encounter_flows
from src.services.encounter import pick_ban_action as pick_ban_action
from src.services.encounter.captain import captain_service
from src.services.encounter.map_report import map_report_service
from src.services.encounter.pick_ban_session import pick_ban_session_service
from src.services.encounter.pick_ban_undo import pick_ban_undo_service
from src.services.encounter.report_form import report_form_service
from src.services.registration import _common as reg_common
from src.services.registration import service as reg_service
from src.services.registration import subscription_config
from src.services.registration import teams as team_service
from src.services.registration.admission import assert_admitted_at
from src.services.registration.subscription_codes import redeem_challenge_code
from src.services.registration.subscription_status import (
    assert_redeem_attempt_allowed,
    subscription_status_for_user,
)
from src.services.registration.validation import (
    validate_registration_input,
    validation_service,
)
from src.services.registration.windows import windows_service


def _subscription_resolver(session: Any) -> Any:
    """Resolver wired with this service's provider credentials.

    Built per request: the Discord strategy memoizes a guild's role list, and that
    memo must not outlive the request that filled it.
    """
    return build_resolver(
        session,
        discord_bot_token=settings.discord_token,
        twitch_client_id=settings.twitch_client_id,
        broker=optional_broker(),
        proxy=settings.proxy_url,
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


# Coalesces concurrent rebuilds of the public registration list for the same
# tournament. A registration mutation notifies every connected viewer at once
# (the "realtime invalidation herd" -- see the channel comment on
# ``_reg_pub_list`` below), so without this a burst of N viewers refetching
# after one mutation triggers N identical, expensive read-model builds that
# queue behind the channel's ``prefetch_count`` -- the actual driver of this
# endpoint's p95 tail latency. Followers join the leader's task instead of
# starting their own: still exactly one live DB read per burst, just shared by
# everyone asking for the same tournament_id at the same instant. Keyed by
# tournament_id only -- the viewer-dependent visibility check always runs on
# the caller's own session before this is ever reached (see
# ``assert_tournament_viewable``'s cache note), so a hidden tournament's gate
# is never skipped for a follower.
_reg_pub_list_inflight: dict[int, asyncio.Task[Any]] = {}


@cache(
    ttl=settings.tournaments_cache_ttl,
    key="registration_list:{tournament_id}:",
    prefix="fastapi:",
)
async def _build_registration_list(tournament_id: int) -> Any:
    async with db.async_session_maker() as session:
        return await reg_service.registration_service.build_public_registration_list(
            session, tournament_id=tournament_id
        )


async def _coalesced_registration_list(tournament_id: int) -> Any:
    task = _reg_pub_list_inflight.get(tournament_id)
    if task is None:
        task = asyncio.create_task(_build_registration_list(tournament_id))
        _reg_pub_list_inflight[tournament_id] = task

        def _cleanup(done: asyncio.Task[Any]) -> None:
            if _reg_pub_list_inflight.get(tournament_id) is done:
                del _reg_pub_list_inflight[tournament_id]

        task.add_done_callback(_cleanup)
    # Shielded: a follower's own cancellation (its caller disconnected/timed
    # out) must not cancel the shared build out from under every other
    # follower -- and unlike a plain ``await task``, ``Task.cancel()`` DOES
    # propagate into whatever future a task is currently awaiting.
    return await asyncio.shield(task)


def register(broker: Any, logger: Any) -> None:
    # ── captain: identity / result submission ─────────────────────────────

    @broker.subscriber("rpc.tournament.captain_my_role")
    async def _captain_my_role(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            encounter = await captain_service._load_encounter(session, encounter_id)
            try:
                side = await captain_service.resolve_captain_side(session, user, encounter)
            except HTTPException:
                side = None
            return {"side": side}

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_submit_report")
    async def _captain_submit_report(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            body = CaptainReportSubmission.model_validate(_payload(data))
            # submit_captain_report commits internally; route returns a custom dict.
            encounter = await captain_service.submit_captain_report(
                session,
                user,
                encounter_id,
                home_score=body.home_score,
                away_score=body.away_score,
                closeness=body.closeness,
                map_codes=[(mc.map_index, mc.code) for mc in body.map_codes],
                comment=body.comment,
                custom_fields=body.custom_fields,
            )
            reports = await captain_service.get_encounter_reports(session, encounter_id)
            return {
                "id": encounter.id,
                "result_status": encounter.result_status,
                "status": encounter.status,
                "home_score": encounter.home_score,
                "away_score": encounter.away_score,
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
            await assert_tournament_viewable(session, _optional_identity(data), tournament_id)
            # The form config rides this envelope so the report dialog opens with
            # exactly the rules the submit endpoint will enforce, in one round trip.
            return {
                "reports": await captain_service.get_encounter_reports(session, encounter_id),
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
            tournament_id = await visibility_resolvers.visibility_resolvers_service.tournament_id_for_encounter(
                session, encounter_id
            )
            await assert_tournament_viewable(session, user, tournament_id)
            encounter = await captain_service._load_encounter(session, encounter_id)
            viewer_side = await resolve_optional_viewer_side(session, user, encounter)
            return await pick_ban_action.pick_ban_action_service.get_pick_ban_state(
                session, encounter_id, kind, viewer_side=viewer_side
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_pick_ban_act")
    async def _captain_pick_ban_act(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            kind = _parse_kind(data)
            user = _identity(data)
            encounter_id = _require_id(data)
            body = PickBanActionInput.model_validate(_payload(data))
            encounter = await captain_service._load_encounter(session, encounter_id)
            captain_side = await captain_service.resolve_captain_side(session, user, encounter)
            entry = await pick_ban_action.pick_ban_action_service.perform_pick_ban_action(
                session, encounter_id, kind, captain_side, body.item_id, body.action
            )
            return pick_ban_action.serialize_pick_ban_entry(entry)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_pick_ban_elect_opener")
    async def _captain_pick_ban_elect_opener(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            kind = _parse_kind(data)
            user = _identity(data)
            encounter_id = _require_id(data)
            body = ElectOpenerInput.model_validate(_payload(data))
            encounter = await captain_service._load_encounter(session, encounter_id)
            captain_side = await captain_service.resolve_captain_side(session, user, encounter)
            pick_ban = await pick_ban_session_service.get_pick_ban_session(session, encounter_id, kind)
            if pick_ban is None:
                raise HTTPException(status_code=400, detail="No round is awaiting an opener choice")
            await pick_ban_session_service.elect_round_opener(
                session, pick_ban, first_side=body.first_side, acting_side=captain_side
            )
            return pick_ban_action.serialize_pick_ban_session(pick_ban)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_pick_ban_undo")
    async def _captain_pick_ban_undo(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            kind = _parse_kind(data)
            user = _identity(data)
            encounter_id = _require_id(data)
            body = PickBanUndoInput.model_validate(_payload(data))
            encounter = await captain_service._load_encounter(session, encounter_id)
            captain_side = await captain_service.resolve_captain_side(session, user, encounter)
            # Commits internally; returns the resulting undo block (empty
            # `item_ids` once the undo landed and the step it restored is open
            # again).
            return await pick_ban_undo_service.perform_undo(
                session, encounter_id, kind, captain_side, consent=body.consent
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_report_map")
    async def _captain_report_map(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            map_id = _path_int(data, "map_id")
            body = MapReportInput.model_validate(_payload(data))
            encounter = await captain_service._load_encounter(session, encounter_id)
            captain_side = await captain_service.resolve_captain_side(session, user, encounter)
            team_id = encounter.home_team_id if captain_side == "home" else encounter.away_team_id
            return await map_report_service.submit_map_report(
                session,
                encounter,
                map_id=map_id,
                team_id=team_id,
                reporter_user_id=user.id,
                home_score=body.home_score,
                away_score=body.away_score,
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_ready")
    async def _captain_ready(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            encounter = await captain_service._load_encounter(session, encounter_id)
            captain_side, captain_user_id, _team_id = await captain_service.resolve_captain_identity(
                session, user, encounter
            )
            # mark_ready commits internally.
            readiness = await pick_ban_session_service.mark_ready(session, encounter, captain_side, captain_user_id)
            return {"readiness": readiness}

        return await _run(logger, op)

    # ── public registration (user sign-up) ────────────────────────────────

    @broker.subscriber("rpc.tournament.reg_pub_form")
    async def _reg_pub_form(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Public route — no identity required, but hidden tournaments 404.
            tournament_id = _path_int(data, "tournament_id")
            await assert_tournament_viewable(session, _optional_identity(data), tournament_id)
            form = await reg_common._common_service.get_registration_form(session, tournament_id)
            if form is None:
                return None
            subrole_catalog = await resolve_subrole_catalog(session, form.workspace_id)
            # The rule is the workspace's now; fetched once here so the sync serializer
            # below stays free of round trips.
            requirement = await subscription_config.subscription_config_service.load_workspace_requirement_blob(
                session, form.workspace_id
            )
            is_open = await windows_service.load_registration_open(session, tournament_id)
            return _dump(
                _form_to_read(
                    form,
                    is_open=is_open,
                    subrole_catalog=subrole_catalog,
                    subscription_requirement=requirement,
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_create")
    async def _reg_pub_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await assert_tournament_viewable(session, user, tournament_id)
            body = RegistrationCreate.model_validate(_payload(data))

            # Admission gate, sign-up stage. Every requirement the tournament armed
            # at `registration` is asked here, in one call; a requirement staged at
            # check-in stays silent by construction rather than by this handler
            # omitting a call. There is no row yet, hence `registration=None` and the
            # acting user as the subject.
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
            )

            # Full use-case (validation, duplicate check, create, serialize)
            # lives in the service layer; commits internally.
            return _dump(
                await reg_service.registration_service.submit_public_registration(
                    session, tournament_id=tournament_id, auth_user=user, body=body
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_get_me")
    async def _reg_pub_get_me(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await assert_tournament_viewable(session, user, tournament_id)
            reg = await reg_service.registration_service.get_registration(session, tournament_id, user.id)
            if reg is None:
                return None
            form = await reg_common._common_service.get_registration_form(session, tournament_id)
            show_ranks = form.show_ranks if form is not None else False
            # The registrant's own card goes through the SAME resolver as the
            # participants list and the admin table -- one batch of one row. That is
            # the point of the layer: this handler used to resolve the profile
            # verdict and the subscription verdicts itself, with its own two calls,
            # and "why am I not admitted" was therefore answerable differently here
            # than on the list the player was reading it next to.
            admissions = await reg_service.registration_service.resolve_admission_list(session, [reg], form=form)
            chips = AdmissionChips.of(admissions.get(reg.id))
            workspace_id = (
                form.workspace_id if form is not None else await _resolve_tournament_workspace(session, tournament_id)
            )
            status_meta_map = await get_status_metas_map(session, workspace_id=workspace_id)
            return _dump(
                _reg_to_read(
                    reg,
                    workspace_id=workspace_id,
                    status_meta_map=status_meta_map,
                    show_ranks=show_ranks,
                    admission=chips.admission,
                    profiles_open=chips.profiles_open,
                    subscription_outcome=chips.subscription_outcome,
                    subscription_verdicts=chips.subscription_verdicts,
                    roster=(await _public_rosters(session, [reg])).get(reg.id),
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_update_me")
    async def _reg_pub_update_me(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await assert_tournament_viewable(session, user, tournament_id)
            body = RegistrationUpdate.model_validate(_payload(data))

            form = await reg_common._common_service.get_registration_form(session, tournament_id)
            if form is None:
                raise HTTPException(status_code=404, detail="Registration form not found")

            reg = await reg_service.registration_service.get_registration(session, tournament_id, user.id)
            if reg is None:
                raise HTTPException(status_code=404, detail="No registration found")

            validate_registration_input(form, body, partial=True)
            await validation_service.validate_verified_identity(
                session,
                form=form,
                payload=body,
                # get_registration eager-loads workspace_member (the
                # registration's only identity anchor since dbarch02).
                player_id=reg.workspace_member.player_id if reg.workspace_member is not None else None,
                partial=True,
            )

            # update_registration commits internally.
            updated = await reg_service.registration_service.update_registration(
                session,
                reg,
                **body.model_dump(exclude_unset=True),
            )
            status_meta_map = await get_status_metas_map(session, workspace_id=form.workspace_id)
            return _dump(
                _reg_to_read(
                    updated,
                    workspace_id=form.workspace_id,
                    status_meta_map=status_meta_map,
                    show_ranks=form.show_ranks,
                    roster=(await _public_rosters(session, [updated])).get(updated.id),
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_withdraw_me")
    async def _reg_pub_withdraw_me(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await assert_tournament_viewable(session, user, tournament_id)
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
            await assert_tournament_viewable(session, user, tournament_id)
            reg = await reg_service.registration_service.get_registration(session, tournament_id, user.id)
            if reg is None:
                raise HTTPException(status_code=404, detail="No registration found")

            # Admission gate, check-in stage: ONE call, every requirement. The
            # profile rule used to be an inline `if` right here and the subscription
            # rule a call into another module, so "what refuses a check-in" could
            # only be answered by reading two places and trusting there was no
            # third. Both are registry entries now, and adding a requirement needs
            # no edit to this handler at all.
            #
            # Only a CONFIRMED refusal blocks, so a provider outage or a BattleTag
            # nobody has polled yet can never lock somebody out of a live check-in.
            #
            # The admin path (`registration_admin.py::_reg_check_in`) deliberately
            # has NO gate: it IS the organizer's override mechanism, and
            # `AdmissionEvaluation.overridden` is what finally makes the result of
            # using it visible instead of the badge re-deriving a refusal forever
            # (D2/D4). Do not add a gate there, and do not add an `override=True`
            # parameter here -- a parameter whose only job is to skip the call is
            # the same call written twice.
            await assert_admitted_at(
                session,
                reg,
                tournament_id=tournament_id,
                auth_user_id=user.id,
                stage=AdmissionStage.check_in,
            )

            form = await reg_common._common_service.get_registration_form(session, tournament_id)

            # check_in_registration commits internally.
            checked_in = await reg_service.registration_service.check_in_registration(
                session,
                reg,
                checked_in_by=user.id,
            )
            workspace_id = await _resolve_tournament_workspace(session, tournament_id)
            status_meta_map = await get_status_metas_map(session, workspace_id=workspace_id)
            return _dump(
                _reg_to_read(
                    checked_in,
                    workspace_id=workspace_id,
                    status_meta_map=status_meta_map,
                    show_ranks=form.show_ranks if form else False,
                    roster=(await _public_rosters(session, [checked_in])).get(checked_in.id),
                )
            )

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
            await assert_tournament_viewable(session, user, tournament_id)
            form = await reg_common._common_service.get_registration_form(session, tournament_id)
            return _dump(
                await subscription_status_for_user(
                    form=form,
                    auth_user_id=user.id,
                    resolver=_subscription_resolver(session),
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
            await assert_tournament_viewable(session, user, tournament_id)
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
                    resolver=_subscription_resolver(session),
                )
            )

        return await _run(logger, op)

    # Isolated QoS: the participants list is the heaviest public read and fans
    # out to every connected viewer after each registration mutation (the
    # realtime invalidation herd). On its own channel a burst of list rebuilds
    # can no longer occupy the default channel's RPC_PREFETCH_COUNT slots and
    # starve the write RPCs (check-in/register) queued behind it — mirrors
    # recalculation_events._EVENTS_CHANNEL.
    @broker.subscriber("rpc.tournament.reg_pub_list", channel=Channel(prefetch_count=8))
    async def _reg_pub_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Public route — no identity required. The visibility check is
            # viewer-dependent and always runs on this call's own session; the
            # (expensive, viewer-agnostic) read-model build below is coalesced
            # across concurrent callers -- see ``_coalesced_registration_list``.
            tournament_id = _path_int(data, "tournament_id")
            await assert_tournament_viewable(session, _optional_identity(data), tournament_id)
            return _dump(await _coalesced_registration_list(tournament_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_list_public")
    async def _regteam_list_public(data: dict, msg: RabbitMessage) -> dict:
        """The public "Teams" roster for a tournament.

        Distinct from the admin ``regteam_list``: invites are omitted for every
        team except one the caller themselves captains — a public roster must not
        leak who else has been asked and declined, but a captain reading their own
        outstanding offers is exactly the person `MyTeamPanel` needs this list to
        answer for. Terminal teams are omitted too — a rejected team is not part
        of the field.
        """

        async def op(session: Any) -> Any:
            tournament_id = _path_int(data, "tournament_id")
            user = _optional_identity(data)
            await assert_tournament_viewable(session, user, tournament_id)
            pairs = await team_service.teams_service.list_teams(
                session, tournament_id=tournament_id, include_terminal=False
            )
            items = [
                await team_service.teams_service.describe_team(
                    session,
                    team,
                    include_invites=user is not None
                    and await team_service.teams_service.is_team_captain(session, team, user.id),
                )
                for team, _occupancy in pairs
            ]
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
    # transport to arguments. See docs/plans/2026-08-20-team-registration.md §4.

    @broker.subscriber("rpc.tournament.regteam_create")
    async def _regteam_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            await assert_tournament_viewable(session, user, tournament_id)
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

            team, _registration = await team_service.teams_service.create_team(
                session,
                tournament_id=tournament_id,
                auth_user=user,
                name=body.name,
                slot_code=body.slot_code,
                body=body.registration,
            )
            # The captain sees their own outstanding offers; a public roster does not.
            return _dump(await team_service.teams_service.describe_team(session, team, include_invites=True))

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
        """

        async def op(session: Any) -> Any:
            _identity(data)
            tournament_id = _path_int(data, "tournament_id")
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
        """A captain reads their own team's full invite history.

        Authorized by captaincy, not by workspace permission — the organizer reads
        the same data through the admin handler. Nothing here is new to a captain:
        they issued every row in it.

        Gated by :func:`assert_captain_of_team`, which deliberately does NOT require
        the team to still be mutable: a rejected or exported team's history is
        exactly what someone opens this to understand.
        """

        async def op(session: Any) -> Any:
            user = _identity(data)
            team_id = _path_int(data, "team_id")
            await team_service.teams_service.assert_captain_of_team(session, team_id=team_id, auth_user=user)
            return _dump(await team_service.teams_service.list_invite_history(session, team_id=team_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_accept")
    async def _regteam_accept(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            body = RegistrationTeamAcceptRequest.model_validate(_payload(data))
            team, _registration = await team_service.teams_service.accept_invite(
                session,
                auth_user=user,
                body=body.registration,
                token=body.token,
                invite_id=body.invite_id,
            )
            # An invitee is now a member, so their own offers view is theirs to see.
            return _dump(await team_service.teams_service.describe_team(session, team, include_invites=True))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_decline")
    async def _regteam_decline(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            payload = _payload(data) or {}
            await team_service.teams_service.decline_invite(
                session,
                auth_user=user,
                token=payload.get("token"),
                invite_id=payload.get("invite_id"),
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

    # ── encounter saved-view writes ───────────────────────────────────────

    @broker.subscriber("rpc.tournament.saved_view_create")
    async def _saved_view_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _require_q1(data, "workspace_id", int)
            if not user.is_workspace_member(workspace_id):
                raise HTTPException(status_code=403, detail="Not a member of this workspace")
            body = schemas.EncounterSavedViewCreate.model_validate(_payload(data))
            # upsert_saved_view commits internally; route uses response_model_exclude_none=True.
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
            # delete_saved_view commits internally; route returns 204 (no body).
            await encounter_flows.flows_service.delete_saved_view(
                session,
                workspace_id=workspace_id,
                auth_user_id=user.id,
                saved_view_id=saved_view_id,
            )
            return None

        return await _run(logger, op)
