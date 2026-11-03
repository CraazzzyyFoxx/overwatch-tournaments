"""The voice reconciler's decisions: plan + rows + what Discord shows -> operations, with no Discord at all.

Stdlib unittest over plain values (``src.services.voice_diff`` is pure).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import TestCase

import discord

from shared.schemas.voice import VoicePlan, VoicePlanChannel
from src.services import voice_diff as vd

EVERYONE, BOT = 100, 1


def plan(*channels: VoicePlanChannel, **fields) -> VoicePlan:
    fields = {
        "tournament_id": 5,
        "tournament_name": "Cup",
        "guild_id": "9",
        "enabled": True,
        "private": False,
        **fields,
    }
    return VoicePlan(channels=list(channels), **fields)


def hub() -> VoicePlanChannel:
    return VoicePlanChannel(slot_key="hub", kind="hub", name="Общий · Cup", position=0)


def team(n: int, *members: str, name: str | None = None) -> VoicePlanChannel:
    return VoicePlanChannel(
        slot_key=f"team:{n}",
        kind="team",
        name=name or f"Team {n}",
        position=n,
        team_id=n,
        member_discord_ids=list(members),
    )


def seen(*channels: vd.SeenChannel, roles: tuple[int, ...] = (), members: frozenset[int] | None = None) -> vd.Seen:
    return vd.Seen(
        channels={c.id: c for c in channels},
        everyone_id=EVERYONE,
        bot_id=BOT,
        role_ids=frozenset({EVERYONE, *roles}),
        member_ids=members,
    )


def category(id_: int, name: str, position: int = 0) -> vd.SeenChannel:
    return vd.SeenChannel(id_, name, is_category=True, position=position)


def voice(id_: int, name: str, parent: int, position: int = 0, **fields) -> vd.SeenChannel:
    fields.setdefault("synced", True)
    return vd.SeenChannel(id_, name, parent_id=parent, position=position, **fields)


def own_category(id_: int = 10, n: int = 1) -> vd.Row:
    return vd.Row(f"category:{n}", "category", id_)


def row(slot_key: str, channel_id: int | None, **fields) -> vd.Row:
    return vd.Row(slot_key, slot_key.split(":")[0].replace("slot", "swiss_slot"), channel_id, **fields)


def kinds(ops) -> list[str]:
    return [type(op).__name__ for op in ops]


class DiffTests(TestCase):
    def test_creates_what_is_missing_in_the_bots_own_category(self) -> None:
        result = vd.diff(plan(hub(), team(1), team(2)), [], seen())

        self.assertEqual(kinds(result.ops), ["CreateCategory", "CreateChannel", "CreateChannel", "CreateChannel"])
        self.assertEqual(result.ops[0], vd.CreateCategory("category:1", "Cup", None))
        self.assertEqual([op.slot_key for op in result.ops[1:]], ["hub", "team:1", "team:2"])
        self.assertEqual({op.category_ref for op in result.ops[1:]}, {"category:1"})
        self.assertTrue(all(op.overwrites is None for op in result.ops[1:]))

    def test_keeps_what_already_matches(self) -> None:
        rows = [own_category(), row("hub", 11), row("team:1", 12)]
        world = seen(category(10, "Cup"), voice(11, "Общий · Cup", 10, 0), voice(12, "Team 1", 10, 1))

        self.assertEqual(vd.diff(plan(hub(), team(1)), rows, world).ops, [])

    def test_renames_only_on_a_name_change(self) -> None:
        rows = [own_category(), row("hub", 11), row("team:1", 12)]
        world = seen(category(10, "Cup"), voice(11, "Общий · Cup", 10, 0), voice(12, "Old name", 10, 1))

        result = vd.diff(plan(hub(), team(1, name="New name")), rows, world)

        self.assertEqual(result.ops, [vd.EditChannel("team:1", name="New name")])

    def test_the_tournament_name_renames_the_bots_category(self) -> None:
        rows = [own_category(), row("hub", 11)]
        world = seen(category(10, "Old Cup"), voice(11, "Общий · Cup", 10))

        self.assertEqual(vd.diff(plan(hub()), rows, world).ops, [vd.EditCategory("category:1", name="Cup")])

    def test_a_public_channel_becoming_private_gets_the_overwrites_in_one_edit(self) -> None:
        rows = [own_category(), row("hub", 11), row("team:1", 12)]
        world = seen(category(10, "Cup"), voice(11, "Общий · Cup", 10, 0), voice(12, "Team 1", 10, 1), roles=(77,))

        result = vd.diff(plan(hub(), team(1, "42", "43"), private=True, staff_role_ids=["77"]), rows, world)

        (edit,) = result.ops  # the hub stays public; nothing else changes
        self.assertEqual(edit.slot_key, "team:1")
        self.assertEqual(
            set(edit.overwrites),
            {("role", EVERYONE), ("role", 77), ("member", 42), ("member", 43), ("member", BOT)},
        )
        everyone_allow, everyone_deny = edit.overwrites[("role", EVERYONE)]
        self.assertEqual((everyone_allow, everyone_deny & vd._VIEW_CONNECT), (0, vd._VIEW_CONNECT))
        self.assertTrue(edit.overwrites[("member", 42)][0] & vd._GUEST == vd._GUEST)

    def test_a_private_channel_that_already_matches_is_left_alone(self) -> None:
        wanted = vd.private_overwrites({}, everyone_id=EVERYONE, staff_role_ids=[], member_ids=[42], bot_id=BOT)
        rows = [own_category(), row("hub", 11), row("team:1", 12)]
        world = seen(
            category(10, "Cup"),
            voice(11, "Общий · Cup", 10, 0),
            voice(12, "Team 1", 10, 1, synced=False, overwrites=wanted),
        )

        self.assertEqual(vd.diff(plan(hub(), team(1, "42"), private=True), rows, world).ops, [])

    def test_a_private_channel_becoming_public_follows_its_category_again(self) -> None:
        wanted = vd.private_overwrites({}, everyone_id=EVERYONE, staff_role_ids=[], member_ids=[42], bot_id=BOT)
        rows = [own_category(), row("hub", 11), row("team:1", 12)]
        world = seen(
            category(10, "Cup"),
            voice(11, "Общий · Cup", 10, 0),
            voice(12, "Team 1", 10, 1, synced=False, overwrites=wanted),
        )

        result = vd.diff(plan(hub(), team(1, "42")), rows, world)

        self.assertEqual(result.ops, [vd.EditChannel("team:1", sync=True)])

    def test_the_category_overwrites_are_the_base_of_a_private_channel(self) -> None:
        organizer = vd.SeenChannel(20, "Events", is_category=True, overwrites={("role", 55): (vd._GUEST, 0)})

        result = vd.diff(plan(team(1, "42"), private=True, category_id="20"), [], seen(organizer, roles=(55,)))

        (create,) = result.ops
        self.assertEqual(create.overwrites[("role", 55)], (vd._GUEST, 0))

    def test_unknown_roles_and_members_outside_the_guild_are_dropped_and_reported(self) -> None:
        result = vd.diff(
            plan(team(1, "42", "43"), private=True, staff_role_ids=["77"]),
            [],
            seen(members=frozenset({42, BOT})),
        )

        (_, create) = result.ops
        self.assertEqual(set(create.overwrites), {("role", EVERYONE), ("member", 42), ("member", BOT)})
        self.assertEqual(
            {(i.code, i.detail) for i in result.issues},
            {("role_not_found", "77"), ("member_overwrite_failed", "team:1:43")},
        )

    def test_switching_to_the_organizers_category_moves_the_channels_instead_of_recreating_them(self) -> None:
        rows = [own_category(), row("hub", 11), row("team:1", 12)]
        world = seen(
            category(10, "Cup"), voice(11, "Общий · Cup", 10, 0), voice(12, "Team 1", 10, 1), category(20, "Events")
        )

        result = vd.diff(plan(hub(), team(1), category_id="20"), rows, world)

        self.assertEqual(
            result.ops,
            [
                vd.EditChannel("hub", category_ref="category:1", sync=True),
                vd.EditChannel("team:1", category_ref="category:1", sync=True),
                vd.MarkDeleting("category:1"),  # the bot's old category, once empty
            ],
        )
        self.assertEqual(result.categories, {"category:1": 20})

    def test_a_missing_organizer_category_falls_back_to_the_bots_own_and_says_so(self) -> None:
        result = vd.diff(plan(hub(), category_id="404"), [], seen())

        self.assertEqual(result.ops[0], vd.CreateCategory("category:1", "Cup", None))
        self.assertEqual(result.issues, [vd.Issue("category_not_found", "404")])

    def test_overflow_counts_foreign_channels_and_continues_in_a_second_category(self) -> None:
        foreign = [voice(1000 + i, f"x{i}", 20) for i in range(48)]  # 48 of 50 seats are taken by others
        world = seen(category(20, "Events", position=3), *foreign)

        result = vd.diff(plan(hub(), team(1), team(2), team(3), category_id="20"), [], world)

        creates = {op.slot_key: op.category_ref for op in result.ops if isinstance(op, vd.CreateChannel)}
        self.assertEqual(
            creates,
            {"hub": "category:1", "team:1": "category:1", "team:2": "category:2", "team:3": "category:2"},
        )
        self.assertIn(vd.CreateCategory("category:2", "Events · 2", "category:1"), result.ops)
        self.assertIn(vd.Issue("category_overflow", "2 categories"), result.issues)

    def test_the_bots_own_channels_do_not_count_against_their_own_category(self) -> None:
        rows = [own_category(), *[row(f"team:{i}", 100 + i) for i in range(1, 51)]]
        world = seen(category(10, "Cup"), *[voice(100 + i, f"Team {i}", 10, i) for i in range(1, 51)])

        result = vd.diff(plan(*[team(i) for i in range(1, 51)]), rows, world)

        self.assertEqual(result.ops, [])  # 50 in one category: no overflow, no churn

    def test_a_channel_dropped_from_the_plan_is_marked_deleting_not_deleted(self) -> None:
        rows = [own_category(), row("hub", 11), row("team:1", 12), row("team:2", 13)]
        world = seen(
            category(10, "Cup"), voice(11, "Общий · Cup", 10, 0), voice(12, "Team 1", 10, 1), voice(13, "Team 2", 10, 2)
        )

        result = vd.diff(plan(hub(), team(1)), rows, world)

        self.assertEqual(result.ops, [vd.MarkDeleting("team:2")])

    def test_a_returning_channel_is_revived(self) -> None:
        rows = [own_category(), row("hub", 11), row("team:1", 12, status="deleting")]
        world = seen(category(10, "Cup"), voice(11, "Общий · Cup", 10, 0), voice(12, "Team 1", 10, 1))

        self.assertEqual(vd.diff(plan(hub(), team(1)), rows, world).ops, [vd.Revive("team:1")])

    def test_a_channel_deleted_by_hand_is_created_again(self) -> None:
        rows = [own_category(), row("hub", 11), row("team:1", None, status="pending"), row("team:2", 99)]
        world = seen(category(10, "Cup"), voice(11, "Общий · Cup", 10, 0))  # 99 is gone from Discord too

        result = vd.diff(plan(hub(), team(1), team(2)), rows, world)

        self.assertEqual(
            [(type(op).__name__, op.slot_key) for op in result.ops],
            [("CreateChannel", "team:1"), ("CreateChannel", "team:2")],
        )

    def test_a_dropped_row_without_a_channel_is_forgotten(self) -> None:
        rows = [own_category(), row("team:1", None, status="pending"), row("team:2", 99, status="deleting")]

        result = vd.diff(plan(), rows, seen(category(10, "Cup")))

        self.assertEqual(
            {(type(op).__name__, op.slot_key) for op in result.ops},
            {("Forget", "team:1"), ("Forget", "team:2"), ("MarkDeleting", "category:1")},
        )

    def test_an_empty_plan_marks_everything_the_bot_made_for_deletion(self) -> None:
        rows = [own_category(), row("hub", 11)]
        world = seen(category(10, "Cup"), voice(11, "Общий · Cup", 10))

        result = vd.diff(plan(), rows, world)

        self.assertEqual(
            [(type(op).__name__, op.slot_key) for op in result.ops],
            [("MarkDeleting", "hub"), ("MarkDeleting", "category:1")],
        )

    def test_the_organizers_category_is_never_deleted(self) -> None:
        rows = [vd.Row("category:1", "category", 20, owned=False), row("hub", 11)]
        world = seen(category(20, "Events"), voice(11, "Общий · Cup", 20))

        result = vd.diff(plan(), rows, world)

        self.assertEqual([op.slot_key for op in result.ops], ["hub"])

    def test_new_channels_in_the_middle_of_the_plan_reorder_the_category(self) -> None:
        rows = [own_category(), row("hub", 11), row("team:2", 13)]
        world = seen(category(10, "Cup"), voice(11, "Общий · Cup", 10, 0), voice(13, "Team 2", 10, 1))

        result = vd.diff(plan(hub(), team(1), team(2)), rows, world)

        self.assertEqual(result.ops[-1], vd.Reorder("category:1", ("hub", "team:1", "team:2")))

    def test_channels_added_at_the_end_need_no_reorder(self) -> None:
        rows = [own_category(), row("hub", 11)]
        world = seen(category(10, "Cup"), voice(11, "Общий · Cup", 10, 0))

        result = vd.diff(plan(hub(), team(1), team(2)), rows, world)

        self.assertFalse(any(isinstance(op, vd.Reorder) for op in result.ops))


class PermissionIssueTests(TestCase):
    def test_names_each_missing_permission_once_across_guild_and_category(self) -> None:
        guild = discord.Permissions(view_channel=True, connect=True, manage_channels=True)
        category = discord.Permissions(view_channel=True, manage_channels=True)  # no Connect here

        codes = [i.code for i in vd.permission_issues(guild, category)]

        self.assertEqual(
            codes,
            ["missing_permission:manage_roles", "missing_permission:move_members", "missing_permission:connect"],
        )
        self.assertEqual(vd.permission_issues(discord.Permissions(administrator=True), None), [])


class RoundMoveTests(TestCase):
    CHANNELS = {"hub": 1, "team:1": 2, "team:2": 3, "slot:7:0": 4}
    ORDER = {"hub": 0, "team:1": 1, "team:2": 2, "slot:7:0": 3}

    def moves(self, old: dict, new: dict, sitting: dict) -> list[tuple[str, int]]:
        return vd.select_round_moves(old, new, sitting, self.CHANNELS, self.ORDER)

    def test_only_changed_routes_of_members_sitting_in_the_tournaments_channels_move(self) -> None:
        old = {"a": "team:1", "b": "team:1", "c": "team:2", "d": "team:2"}
        new = {"a": "slot:7:0", "b": "team:1", "c": "slot:7:0", "d": "slot:7:0"}
        sitting = {"a": 2, "b": 2, "c": 3}  # d sits in no channel of the tournament

        self.assertEqual(self.moves(old, new, sitting), [("a", 4), ("c", 4)])

    def test_a_member_already_in_the_new_channel_stays(self) -> None:
        self.assertEqual(self.moves({"a": "team:1"}, {"a": "slot:7:0"}, {"a": 4}), [])

    def test_a_new_participant_in_a_channel_is_moved_and_a_dropped_one_is_not(self) -> None:
        moves = self.moves({"gone": "team:1"}, {"new": "team:1"}, {"new": 1, "gone": 2})

        self.assertEqual(moves, [("new", 2)])

    def test_moves_follow_the_plan_order_of_the_target_channel(self) -> None:
        old = {"a": "hub", "b": "hub", "c": "hub"}
        new = {"a": "slot:7:0", "b": "team:1", "c": "team:2"}

        moves = self.moves(old, new, {"a": 1, "b": 1, "c": 1})

        self.assertEqual(moves, [("b", 2), ("c", 3), ("a", 4)])

    def test_a_route_to_a_channel_that_does_not_exist_moves_nobody(self) -> None:
        self.assertEqual(self.moves({}, {"a": "team:9"}, {"a": 1}), [])


class DeletionTests(TestCase):
    NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def test_an_empty_voice_channel_goes_at_once(self) -> None:
        self.assertTrue(vd.deletion_due("team", self.NOW, self.NOW, 0))

    def test_an_occupied_one_waits_ten_minutes_from_the_drop(self) -> None:
        asked = self.NOW - timedelta(minutes=9, seconds=59)

        self.assertFalse(vd.deletion_due("team", asked, self.NOW, 3))
        self.assertTrue(vd.deletion_due("team", asked - timedelta(seconds=1), self.NOW, 3))

    def test_a_category_goes_only_when_it_holds_nothing(self) -> None:
        long_ago = self.NOW - timedelta(hours=3)

        self.assertFalse(vd.deletion_due("category", long_ago, self.NOW, 1))
        self.assertTrue(vd.deletion_due("category", long_ago, self.NOW, 0))
