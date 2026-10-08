"""Card action buttons: who the bot acts as, what it calls, and what the card becomes.

The security half is the first class: the bot must never call an action RPC for
a Discord user who has not linked an account, and the identity it acts with is
the one identity-service returned -- never one assembled here. The rest pins
the user-visible contract: refusals worded by their machine code, and a DM card
that loses its spent buttons while a channel post is never touched.
"""

import sys
from pathlib import Path
from typing import Any, get_args
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord  # noqa: E402

from shared.schemas.events import DiscordAction, DiscordCard  # noqa: E402
from shared.schemas.rpc import parse_rpc, rpc_error, rpc_ok  # noqa: E402
from src.cogs.interactions import InteractionsCog  # noqa: E402
from src.interactions import copy  # noqa: E402
from src.interactions import dispatcher as dispatcher_module  # noqa: E402
from src.interactions.actions import ACTIONS, parse_custom_id, parse_setup_target, setup_target  # noqa: E402
from src.interactions.cards import card_view, settle  # noqa: E402
from src.interactions.dispatcher import (  # noqa: E402
    IDENTITY_SUBJECT,
    MIX_CURRENT_SUBJECT,
    MIX_HOSTED_SUBJECT,
    ActionDispatcher,
    Outcome,
)

SITE = "https://owt.example"
IDENTITY = {"sub": 77, "username": "kira", "credential_type": "discord", "workspaces": []}


class _Rpc:
    """Stands in for ``request_rpc``: canned envelopes by subject, calls recorded."""

    def __init__(self, replies: dict[str, Any]) -> None:
        self.replies = replies
        self.calls: list[tuple[str, dict[str, Any]]] = []
        #: One per call, in order: an action that may legitimately take seconds asks for longer.
        self.timeouts: list[float] = []

    async def __call__(self, broker: Any, payload: dict[str, Any], queue: str, *, timeout: float) -> Any:
        self.calls.append((queue, payload))
        self.timeouts.append(timeout)
        reply = self.replies[queue]
        if isinstance(reply, Exception):
            raise reply
        return parse_rpc(reply)

    def subjects(self) -> list[str]:
        return [queue for queue, _ in self.calls]


def _session_maker() -> MagicMock:
    """``async with session_maker() as session`` over a session nothing reads."""
    maker = MagicMock()
    maker.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    maker.return_value.__aexit__ = AsyncMock(return_value=False)
    return maker


def _dispatcher(workspaces: Any = None) -> ActionDispatcher:
    return ActionDispatcher(
        site_url=SITE,
        broker=lambda: object(),
        session_maker=_session_maker() if workspaces is not None else None,
        workspaces=workspaces if workspaces is not None else MagicMock(),
    )


def _invite_card() -> DiscordCard:
    return DiscordCard(
        text="### Team invite",
        answers=[
            {"type": "action", "label": "Accept", "action": "invite.accept", "target": "42", "style": "success"},
            {"type": "action", "label": "Decline", "action": "invite.decline", "target": "42", "style": "danger"},
        ],
        rows=[
            [
                {"type": "link", "label": "View participants", "url": f"{SITE}/tournaments/3/participants"},
                {"type": "action", "label": "🔕", "action": "notifications.menu", "target": "all"},
            ],
        ],
    )


def _mix_state(**overrides: Any) -> dict[str, Any]:
    """The ``self_*`` wire answer: a seated player who may reorder their roles."""
    state: dict[str, Any] = {
        "custom_game_id": 42,
        "name": "Пятничный микс",
        "status": "balanced",
        "self_signup": "pool",
        "self_role_edit": True,
        "seat": {
            "participation": "pool",
            "roles": ["tank", "support"],
            "is_flex": False,
            "ranks": {"tank": 3100, "damage": None, "support": None},
            "divisions": {"tank": {"name": "Gold 3", "slug": "gold-3"}, "damage": None, "support": None},
        },
        "unranked_roles": ["support"],
        "policy": {
            "can_join": False,
            "can_leave": True,
            "can_edit_roles": True,
            "join_blocker": "already_joined",
            "edit_blocker": None,
        },
    }
    state.update(overrides)
    return state


def _interaction(*, guild_id: int | None = None, locale: str = "ru", ephemeral: bool = False) -> MagicMock:
    return MagicMock(
        user=MagicMock(id=4242),
        locale=locale,
        guild_id=guild_id,
        message=MagicMock(flags=MagicMock(ephemeral=ephemeral)),
        response=MagicMock(defer=AsyncMock(), send_message=AsyncMock(), send_modal=AsyncMock()),
        followup=MagicMock(send=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


def _reply_text(view: discord.ui.LayoutView) -> str:
    """Every line the coloured container holds: the heading and, past the divider, the details."""
    container, *_rows = view.to_components()
    return "\n".join(child["content"] for child in container["components"] if child["type"] == 10)


class ActingAsTheClickerTests(IsolatedAsyncioTestCase):
    async def test_an_unlinked_discord_user_triggers_no_platform_call(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_error("not_found", "Discord account is not linked")})

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await _dispatcher().perform(4242, "invite.accept", "42")

        self.assertEqual(outcome.status, "not_linked")
        self.assertEqual(rpc.subjects(), [IDENTITY_SUBJECT])

    async def test_the_action_runs_with_the_identity_identity_service_returned(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.tournament.regteam_accept": rpc_ok({"id": 1})})

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await _dispatcher().perform(4242, "invite.accept", "42")

        self.assertEqual(outcome.status, "ok")
        (_, lookup), (subject, body) = rpc.calls
        self.assertEqual(lookup, {"discord_user_id": "4242"})
        self.assertEqual(subject, "rpc.tournament.regteam_accept")
        self.assertEqual(body, {"identity": IDENTITY, "payload": {"invite_id": 42}})

    async def test_a_deactivated_account_is_not_acted_for(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_error("forbidden", "Inactive user")})

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await _dispatcher().perform(4242, "check_in", "3")

        self.assertEqual(outcome.status, "inactive")
        self.assertEqual(rpc.subjects(), [IDENTITY_SUBJECT])

    async def test_a_platform_that_does_not_answer_is_unavailable_not_a_refusal(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.tournament.reg_pub_check_in": TimeoutError()})

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await _dispatcher().perform(4242, "check_in", "3")

        self.assertEqual(outcome.status, "unavailable")

    async def test_a_second_click_inside_the_window_reuses_the_identity(self) -> None:
        """A mix panel is a chain of clicks; asking who the clicker is once covers the lot."""
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.tournament.reg_pub_check_in": rpc_ok({"id": 1})})
        dispatcher = _dispatcher()

        with patch.object(dispatcher_module, "request_rpc", rpc):
            await dispatcher.perform(4242, "check_in", "3")
            await dispatcher.perform(4242, "check_in", "3")

        self.assertEqual(rpc.subjects().count(IDENTITY_SUBJECT), 1)
        self.assertEqual(rpc.subjects().count("rpc.tournament.reg_pub_check_in"), 2)

    async def test_an_unlinked_account_is_asked_again_on_the_next_click(self) -> None:
        """Caching a "not linked" would hide the link the clicker just made."""
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_error("not_found", "Discord account is not linked")})
        dispatcher = _dispatcher()

        with patch.object(dispatcher_module, "request_rpc", rpc):
            await dispatcher.perform(4242, "check_in", "3")
            await dispatcher.perform(4242, "check_in", "3")

        self.assertEqual(rpc.subjects(), [IDENTITY_SUBJECT, IDENTITY_SUBJECT])


class ButtonContractTests(IsolatedAsyncioTestCase):
    def test_every_action_the_card_contract_allows_is_one_the_bot_answers(self) -> None:
        self.assertEqual(set(ACTIONS), set(get_args(DiscordAction)))

    def test_only_well_formed_buttons_reach_an_action(self) -> None:
        self.assertEqual(parse_custom_id("owt:invite.accept:42"), ("invite.accept", "42"))
        self.assertEqual(parse_custom_id("owt:notifications.mute:all"), ("notifications.mute", "all"))
        for refused in (
            "owt:invite.accept:abc",  # an id that is not one
            "owt:notifications.mute:team",  # muting is all or nothing
            "owt:admin.delete:1",  # an action that is not on the list
            "someone-else:button",
            None,
        ):
            self.assertIsNone(parse_custom_id(refused), refused)

    async def test_a_refusal_is_worded_by_its_machine_code(self) -> None:
        error = rpc_error(
            "conflict",
            "This invite has expired",
            {"fields": [{"field": None, "msg": "This invite has expired", "code": "invite_expired"}]},
        )
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.tournament.regteam_accept": error})
        dispatcher = _dispatcher()

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await dispatcher.perform(4242, "invite.accept", "42")

        self.assertEqual((outcome.status, outcome.code), ("failed", "invite_expired"))
        self.assertIn("Срок приглашения истёк", _reply_text(dispatcher.reply(outcome, "invite.accept", "ru")))


class CardLayoutTests(IsolatedAsyncioTestCase):
    """What the coloured container holds, and in which order."""

    async def test_a_cards_own_picture_hangs_under_its_text(self) -> None:
        """``image_url`` is the card's subject (an encounter's OpenGraph image),
        so it is a full-width gallery below the details, not the thumbnail."""
        plain = card_view(DiscordCard(text="### Match", details="**Starts:** soon"))
        with_image = card_view(
            DiscordCard(text="### Match", details="**Starts:** soon", image_url="https://og.example/5.png")
        )

        (bare,) = plain.to_components()
        (container,) = with_image.to_components()
        # 10 text, 14 separator, 12 media gallery.
        self.assertEqual([child["type"] for child in bare["components"]], [10, 14, 10])
        self.assertEqual([child["type"] for child in container["components"]], [10, 14, 10, 12])
        gallery = container["components"][-1]
        self.assertEqual([item["media"]["url"] for item in gallery["items"]], ["https://og.example/5.png"])


class CardAfterTheClickTests(IsolatedAsyncioTestCase):
    async def test_settling_removes_only_the_spent_buttons(self) -> None:
        settled = settle(card_view(_invite_card()), retire=ACTIONS["invite.accept"].settles, note="-# accepted")

        container, remaining = settled.to_components()
        labels = [button["label"] for button in remaining["components"]]
        self.assertEqual(labels, ["View participants", "🔕"])
        # The spent row leaves the card entirely; only the heading and the note remain.
        _heading, note = container["components"]
        self.assertEqual(note["content"], "-# accepted")

    async def test_a_dm_card_loses_its_spent_buttons_and_a_channel_post_is_never_edited(self) -> None:
        replies = {IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.tournament.regteam_accept": rpc_ok({"id": 1})}
        dm, post = _interaction(guild_id=None), _interaction(guild_id=555)

        with (
            patch.object(dispatcher_module, "request_rpc", _Rpc(replies)),
            patch.object(discord.ui.LayoutView, "from_message", side_effect=lambda *a, **k: card_view(_invite_card())),
        ):
            await _dispatcher().handle(dm, "invite.accept", "42")
            await _dispatcher().handle(post, "invite.accept", "42")

        for interaction in (dm, post):
            interaction.response.defer.assert_awaited_once()
            self.assertTrue(interaction.followup.send.await_args.kwargs["ephemeral"])
        container, *_rows = dm.edit_original_response.await_args.kwargs["view"].to_components()
        self.assertIn("Вы приняли приглашение", container["components"][-1]["content"])
        post.edit_original_response.assert_not_awaited()

    async def test_a_retired_button_is_answered_instead_of_failing_silently(self) -> None:
        dispatcher = MagicMock(handle=AsyncMock())
        cog = InteractionsCog(MagicMock(action_dispatcher=dispatcher))
        stale = _interaction(locale="en-US")
        stale.type = discord.InteractionType.component
        stale.data = {"custom_id": "owt:admin.delete:1"}
        foreign = _interaction()
        foreign.type = discord.InteractionType.component
        foreign.data = {"custom_id": "poll:vote:1"}

        await cog.on_interaction(stale)
        await cog.on_interaction(foreign)

        dispatcher.handle.assert_not_awaited()
        self.assertIn("no longer works", stale.response.send_message.await_args.args[0])
        foreign.response.send_message.assert_not_awaited()


class MuteEverythingTests(IsolatedAsyncioTestCase):
    """The card only carries a small trigger; the switch itself is shown to the reader alone."""

    async def test_the_trigger_opens_a_private_prompt_without_touching_the_platform(self) -> None:
        rpc = _Rpc({})
        dm = _interaction()

        with patch.object(dispatcher_module, "request_rpc", rpc):
            await _dispatcher().handle(dm, "notifications.menu", "all")

        self.assertEqual(rpc.calls, [])
        sent = dm.followup.send.await_args.kwargs
        self.assertTrue(sent["ephemeral"])
        _container, row = sent["view"].to_components()
        custom_ids = [b.get("custom_id") for b in row["components"]]
        self.assertIn("owt:notifications.mute:all", custom_ids)

    async def test_muting_switches_every_group_off_and_answers_in_place(self) -> None:
        replies = {IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.app.notification_preferences_update": rpc_ok({})}
        rpc = _Rpc(replies)
        prompt = _interaction(ephemeral=True)

        with patch.object(dispatcher_module, "request_rpc", rpc):
            await _dispatcher().handle(prompt, "notifications.mute", "all")

        (_, body) = rpc.calls[-1]
        self.assertEqual(
            body["payload"], {"discord_dm": {"tournament": False, "matches": False, "team": False, "staff": False}}
        )
        # The prompt becomes the answer rather than gaining a second reply beneath it.
        prompt.followup.send.assert_not_awaited()
        self.assertIn("отключены", _reply_text(prompt.edit_original_response.await_args.kwargs["view"]))


class SeatFormTests(IsolatedAsyncioTestCase):
    """The seat form: what the button carries into it, and what the submit becomes on the wire."""

    def test_the_setup_target_carries_the_whole_form_both_ways(self) -> None:
        """A modal must be the first answer to a click, so the form is opened
        from the target alone -- it has to survive the round trip exactly."""
        for roles, is_flex in (
            (["tank", "support"], True),
            (["damage"], False),
            (["support", "damage", "tank"], True),
            (None, False),  # every ranked role
            ([], True),  # nothing picked yet
        ):
            target = setup_target(42, roles, is_flex)
            self.assertEqual(parse_setup_target(target), (42, roles, is_flex), target)
            self.assertEqual(parse_custom_id(f"owt:mix.setup:{target}"), ("mix.setup", target))
        self.assertEqual(setup_target(42, ["tank", "support"], True), "42-ts-1")
        self.assertEqual(setup_target(42, None, False), "42-a-0")
        self.assertEqual(setup_target(42, [], False), "42-x-0")

    def test_a_forged_setup_target_never_reaches_an_action(self) -> None:
        for refused in ("owt:mix.setup:42-tt-1", "owt:mix.setup:42-tz-1", "owt:mix.setup:42", "owt:mix.setup:42-ts-2"):
            self.assertIsNone(parse_custom_id(refused), refused)

    async def test_the_form_opens_on_the_click_itself_and_calls_nothing(self) -> None:
        rpc = _Rpc({})
        cog = InteractionsCog(MagicMock(action_dispatcher=_dispatcher()))
        click = _interaction(ephemeral=True)
        click.type = discord.InteractionType.component
        click.data = {"custom_id": "owt:mix.setup:42-ts-1"}

        with patch.object(dispatcher_module, "request_rpc", rpc):
            await cog.on_interaction(click)

        self.assertEqual(rpc.calls, [])
        # Discord takes a modal only as the *first* response: a defer would lose it.
        click.response.defer.assert_not_awaited()
        (modal,) = click.response.send_modal.await_args.args
        form = modal.to_dict()
        self.assertEqual(form["custom_id"], "owt:mix.seat_set:42")
        self.assertEqual(form["title"], "Моё место")
        fields = {label["component"]["custom_id"]: label["component"] for label in form["components"]}
        self.assertEqual(list(fields), ["role1", "role2", "role3", "flex"])
        # Opened filled in: tank first, support second, nothing third, flex on.
        picked = {
            name: [option["value"] for option in field["options"] if option["default"]]
            for name, field in fields.items()
            if field["type"] == 21
        }
        self.assertEqual(picked, {"role1": ["tank"], "role2": ["support"], "role3": ["none"]})
        self.assertTrue(fields["flex"]["default"])

    async def test_the_submitted_form_becomes_one_self_update(self) -> None:
        """The three slots are a priority order, so it is kept; a role ticked
        twice is one role, and the empty slots simply do not appear."""
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.balancer.custom.self_update": rpc_ok(_mix_state())})
        cog = InteractionsCog(MagicMock(action_dispatcher=_dispatcher()))
        submit = _interaction(ephemeral=True)
        submit.type = discord.InteractionType.modal_submit
        submit.data = {
            "custom_id": "owt:mix.seat_set:42",
            "components": [
                {"type": 18, "component": {"type": 21, "custom_id": "role1", "value": "support"}},
                {"type": 18, "component": {"type": 21, "custom_id": "role2", "value": "tank"}},
                {"type": 18, "component": {"type": 21, "custom_id": "role3", "value": "support"}},
                {"type": 18, "component": {"type": 23, "custom_id": "flex", "value": True}},
            ],
        }

        with patch.object(dispatcher_module, "request_rpc", rpc):
            await cog.on_interaction(submit)

        subject, body = rpc.calls[-1]
        self.assertEqual(subject, "rpc.balancer.custom.self_update")
        self.assertEqual(body["custom_game_id"], 42)
        self.assertEqual(body["payload"], {"roles": ["support", "tank"], "is_flex": True})
        # The form was opened from a panel only the clicker sees: the answer
        # replaces that panel instead of stacking another reply under it.
        submit.followup.send.assert_not_awaited()
        self.assertIn("Пятничный микс", _reply_text(submit.edit_original_response.await_args.kwargs["view"]))

    async def test_every_ranked_role_clears_the_order(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.balancer.custom.self_update": rpc_ok(_mix_state())})

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await _dispatcher().perform(
                4242, "mix.seat_set", "42", {"role1": "all", "role2": "none", "role3": "none", "flex": "0"}
            )

        self.assertEqual(outcome.status, "ok")
        self.assertEqual(rpc.calls[-1][1]["payload"], {"roles": None, "is_flex": False})

    async def test_a_value_the_bot_never_minted_is_refused_before_any_call(self) -> None:
        rpc = _Rpc({})
        dispatcher = _dispatcher()

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await dispatcher.perform(4242, "mix.seat_set", "42", {"role1": "healer", "flex": "1"})

        self.assertEqual((outcome.status, outcome.code), ("failed", "bad_values"))
        self.assertEqual(rpc.calls, [])
        self.assertIn("разобрать выбор ролей", _reply_text(dispatcher.reply(outcome, "mix.seat_set", "ru")))


class MixSelfSignupTests(IsolatedAsyncioTestCase):
    """The seat panel: which controls the policy allows, and what the card says."""

    async def test_the_panel_offers_the_form_only_while_roles_are_editable(self) -> None:
        dispatcher = _dispatcher()

        editable = dispatcher.reply(Outcome("ok", _mix_state()), "mix.roles", "ru")

        _container, buttons = editable.to_components()
        self.assertEqual(
            [button["custom_id"] for button in buttons["components"]],
            ["owt:mix.setup:42-ts-0", "owt:mix.leave:42"],
        )

        locked = dispatcher.reply(
            Outcome(
                "ok",
                _mix_state(
                    self_role_edit=False,
                    policy={
                        "can_join": False,
                        "can_leave": True,
                        "can_edit_roles": False,
                        "join_blocker": "already_joined",
                        "edit_blocker": "role_edit_off",
                    },
                ),
            ),
            "mix.roles",
            "ru",
        )

        _container, only_row = locked.to_components()
        self.assertEqual([button["custom_id"] for button in only_row["components"]], ["owt:mix.leave:42"])
        self.assertIn("не разрешил игрокам менять роли", _reply_text(locked))

    def test_the_panel_names_every_role_once_with_its_division(self) -> None:
        """Read against ``copy`` rather than the view: a shortcode is swapped
        for the uploaded emoji on the way out, and there is none in a test."""
        head, details = copy.mix_text("ru", _mix_state())

        self.assertIn("Пятничный микс", head)
        self.assertIn(":owt_ok: Вы в пуле", head)
        self.assertIn("① :owt_tank: Танк — :owt_div_gold_3: Gold 3 · 3100", details)
        self.assertIn("② :owt_support: Саппорт — без ранга", details)
        # The role they did *not* pick is still on the card, so the panel
        # answers "and the others?" without a second click.
        self.assertIn("   :owt_damage: Дамаг — не играете", details)
        self.assertIn(":owt_flex: Флекс: выкл", details)
        self.assertIn("-# :owt_warn: Нет ранга: Саппорт", details)

        every_ranked = _mix_state()
        every_ranked["seat"]["roles"] = None
        _head, all_details = copy.mix_text("ru", every_ranked)
        self.assertIn("все роли с рангом", all_details)
        self.assertIn(":owt_tank: Танк — :owt_div_gold_3: Gold 3 · 3100", all_details)
        self.assertNotIn("①", all_details)

        no_seat_head, _details = copy.mix_text("ru", _mix_state(seat=None))
        self.assertIn("Вы не записаны на этот микс.", no_seat_head)

    async def test_the_card_names_the_lobby_only_when_the_mix_runs_several(self) -> None:
        """With more than one lobby "you are signed up" is not enough: a player
        has to know which of the games is theirs, or whether they have a seat yet."""
        dispatcher = _dispatcher()

        one_lobby = _reply_text(dispatcher.reply(Outcome("ok", _mix_state()), "mix.roles", "ru"))
        self.assertNotIn("Лобби", one_lobby)

        seated = _mix_state(lobby_count=2)
        seated["seat"]["current_lobby"] = 1
        self.assertIn("Лобби B", _reply_text(dispatcher.reply(Outcome("ok", seated), "mix.roles", "ru")))

        third = _mix_state(lobby_count=4)
        third["seat"]["current_lobby"] = 2
        self.assertIn("Лобби C", _reply_text(dispatcher.reply(Outcome("ok", third), "mix.roles", "ru")))

        waiting = _mix_state(lobby_count=2)
        waiting["seat"]["current_lobby"] = None
        self.assertIn("Ждёте места", _reply_text(dispatcher.reply(Outcome("ok", waiting), "mix.roles", "ru")))

        english = _mix_state(lobby_count=2)
        english["seat"]["current_lobby"] = 0
        self.assertIn("Lobby A", _reply_text(dispatcher.reply(Outcome("ok", english), "mix.roles", "en")))

    async def test_a_missing_battlenet_link_is_named_and_points_at_the_profile(self) -> None:
        rpc = _Rpc(
            {
                IDENTITY_SUBJECT: rpc_ok(IDENTITY),
                "rpc.balancer.custom.self_join": rpc_error("forbidden", "battlenet_not_linked"),
            }
        )
        dispatcher = _dispatcher()

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await dispatcher.perform(4242, "mix.join", "42")

        self.assertEqual((outcome.status, outcome.message), ("failed", "battlenet_not_linked"))
        view = dispatcher.reply(outcome, "mix.join", "ru")
        _container, row = view.to_components()
        self.assertIn("Battle.net", _reply_text(view))
        self.assertEqual([button["url"] for button in row["components"]], [f"{SITE}/?settings=profile"])

    async def test_a_closed_signup_is_worded_without_a_profile_link(self) -> None:
        rpc = _Rpc(
            {
                IDENTITY_SUBJECT: rpc_ok(IDENTITY),
                "rpc.balancer.custom.self_join": rpc_error("conflict", "signup_closed"),
            }
        )
        dispatcher = _dispatcher()

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await dispatcher.perform(4242, "mix.join", "42")

        view = dispatcher.reply(outcome, "mix.join", "ru")
        self.assertEqual(len(view.to_components()), 1)
        self.assertIn("Запись на этот микс закрыта", _reply_text(view))


class CurrentMixCommandTests(IsolatedAsyncioTestCase):
    """``/mix``: the same seat panel, found from the guild instead of from a button."""

    async def test_the_command_reads_the_workspace_off_the_guild_and_shows_the_seat(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), MIX_CURRENT_SUBJECT: rpc_ok(_mix_state())})
        workspaces = MagicMock(list_ids_by_discord_guild=AsyncMock(return_value=[7]))
        command = _interaction(guild_id=555)

        with patch.object(dispatcher_module, "request_rpc", rpc):
            await _dispatcher(workspaces=workspaces).show_current_mix(command)

        command.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        self.assertEqual(workspaces.list_ids_by_discord_guild.await_args.args[1], "555")
        subject, body = rpc.calls[-1]
        self.assertEqual(subject, MIX_CURRENT_SUBJECT)
        self.assertEqual(body, {"identity": IDENTITY, "workspace_id": 7})
        sent = command.followup.send.await_args.kwargs
        self.assertTrue(sent["ephemeral"])
        self.assertIn("Пятничный микс", _reply_text(sent["view"]))

    async def test_no_open_mix_is_said_plainly_instead_of_as_a_failure(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), MIX_CURRENT_SUBJECT: rpc_error("not_found", "no mix")})
        workspaces = MagicMock(list_ids_by_discord_guild=AsyncMock(return_value=[7]))
        command = _interaction(guild_id=555)

        with patch.object(dispatcher_module, "request_rpc", rpc):
            await _dispatcher(workspaces=workspaces).show_current_mix(command)

        self.assertIn("Сейчас нет открытого микса", _reply_text(command.followup.send.await_args.kwargs["view"]))

    async def test_a_guild_wired_to_no_workspace_asks_the_platform_nothing(self) -> None:
        rpc = _Rpc({})
        workspaces = MagicMock(list_ids_by_discord_guild=AsyncMock(return_value=[]))
        command = _interaction(guild_id=555)

        with patch.object(dispatcher_module, "request_rpc", rpc):
            await _dispatcher(workspaces=workspaces).show_current_mix(command)

        self.assertEqual(rpc.calls, [])
        self.assertIn("Сейчас нет открытого микса", _reply_text(command.followup.send.await_args.kwargs["view"]))


def _report(**overrides: Any) -> dict[str, Any]:
    """What a voice move answers with: the count, then a row per person."""
    report: dict[str, Any] = {
        "moved": 1,
        "results": [
            {"workspace_member_id": 1, "name": "Ana", "status": "moved", "channel_id": "900"},
            {"workspace_member_id": 2, "name": "Bob", "status": "not_in_voice", "channel_id": None},
        ],
    }
    report.update(overrides)
    return report


class VoiceControlsTests(IsolatedAsyncioTestCase):
    """The lineup card's voice buttons and ``/mix move|return``: one call, one report."""

    def test_a_voice_button_names_one_mix_and_one_lobby_or_all_of_them(self) -> None:
        self.assertEqual(parse_custom_id("owt:voice.move:42-0"), ("voice.move", "42-0"))
        self.assertEqual(parse_custom_id("owt:voice.return:42-all"), ("voice.return", "42-all"))
        for refused in ("owt:voice.move:42-6", "owt:voice.move:42", "owt:voice.move:all-0"):
            self.assertIsNone(parse_custom_id(refused), refused)

    async def test_moving_every_lobby_is_one_call_with_room_for_discords_rate_limit(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.balancer.custom.voice_move": rpc_ok(_report())})

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await _dispatcher().perform(4242, "voice.move", "42-all")

        self.assertEqual(outcome.status, "ok")
        self.assertEqual(
            rpc.calls[-1],
            (
                "rpc.balancer.custom.voice_move",
                {"identity": IDENTITY, "custom_game_id": 42, "payload": {"lobby_index": None}},
            ),
        )
        self.assertEqual(rpc.timeouts[-1], 40.0)

    async def test_the_slash_command_moves_one_lobby_and_answers_the_host_alone(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.balancer.custom.voice_return": rpc_ok(_report())})
        command = _interaction(guild_id=555)

        with patch.object(dispatcher_module, "request_rpc", rpc):
            await _dispatcher().run_voice(command, "voice.return", 42, "1")

        command.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        subject, body = rpc.calls[-1]
        self.assertEqual(subject, "rpc.balancer.custom.voice_return")
        self.assertEqual(body, {"identity": IDENTITY, "custom_game_id": 42, "payload": {"lobby_index": 1}})
        self.assertTrue(command.followup.send.await_args.kwargs["ephemeral"])

    def test_the_report_counts_who_moved_and_names_everyone_who_did_not(self) -> None:
        text = _reply_text(_dispatcher().reply(Outcome("ok", data=_report()), "voice.move", "ru"))

        self.assertIn("Перенесено: 1", text)
        self.assertIn("**Не в войсе:** Bob", text)

    def test_a_mix_without_a_general_voice_is_told_what_to_fix(self) -> None:
        outcome = Outcome("failed", code="general_voice_not_configured", message="general voice is not configured")

        text = _reply_text(_dispatcher().reply(outcome, "voice.return", "ru"))

        self.assertIn("У микса не выбран общий войс.", text)

    async def test_autocomplete_offers_the_open_mixes_matching_what_was_typed(self) -> None:
        hosted = [
            {"id": 12, "name": "Пятничный микс", "lobby_count": 2},
            {"id": 11, "name": "Training", "lobby_count": 1},
        ]
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), MIX_HOSTED_SUBJECT: rpc_ok(hosted)})
        workspaces = MagicMock(list_ids_by_discord_guild=AsyncMock(return_value=[7]))

        with patch.object(dispatcher_module, "request_rpc", rpc):
            choices = await _dispatcher(workspaces=workspaces).hosted_mixes(_interaction(guild_id=555), "TRAIN")

        self.assertEqual([(choice.name, choice.value) for choice in choices], [("Training", 11)])
        self.assertEqual(rpc.calls[-1][1], {"identity": IDENTITY, "workspace_id": 7})

    async def test_autocomplete_offers_nothing_when_the_platform_refuses(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), MIX_HOSTED_SUBJECT: rpc_error("internal", "boom")})
        workspaces = MagicMock(list_ids_by_discord_guild=AsyncMock(return_value=[7]))

        with patch.object(dispatcher_module, "request_rpc", rpc):
            choices = await _dispatcher(workspaces=workspaces).hosted_mixes(_interaction(guild_id=555), "")

        self.assertEqual(choices, [])
