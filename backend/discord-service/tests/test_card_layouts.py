"""Every bot-owned surface, pinned by its *shape* alone.

The wording of a card is free to change -- it is translated, reworded and
re-ordered constantly, and a test that pins a sentence only ever fails for the
wrong reason. What must not change by accident is the layout Discord is handed:
which components nest in which, the accent colour that says how it went, and on
every button the style, the ``custom_id`` a click is routed by, its emoji, and
whether it is disabled or a link. A ``custom_id`` quietly renamed or a style
flipped from danger to primary is invisible in review and obvious here.

So each surface is rendered through the real code, reduced to that skeleton
(:func:`_shape` drops every label, every sentence, every URL target) and
compared with a golden file in ``tests/layouts/``. Regenerate them after a
deliberate change::

    UPDATE_LAYOUTS=1 uv run python -m pytest tests/test_card_layouts.py
"""

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest import TestCase

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord  # noqa: E402

from shared.schemas.events import DiscordCard  # noqa: E402
from src.interactions.actions import ACTIONS  # noqa: E402
from src.interactions.cards import card_view, seat_modal, settle  # noqa: E402
from src.interactions.dispatcher import ActionDispatcher, Outcome  # noqa: E402

LAYOUTS = Path(__file__).parent / "layouts"
SITE = "https://owt.example"
LOCALE = "ru"


def _shape(node: Mapping[str, Any]) -> dict[str, Any]:
    """One component reduced to what Discord's renderer actually branches on.

    Deliberately *not* here: labels, text, placeholders, URLs and emoji ids --
    copy, links and the dev/prod emoji ids are all free to move. A link button
    keeps only the fact that it is one.
    """
    out: dict[str, Any] = {"type": node.get("type")}
    if "accent_color" in node:
        out["accent_color"] = node["accent_color"]
    if node.get("type") == 2:  # button
        out["style"] = node.get("style")
        out["custom_id"] = node.get("custom_id")
        out["emoji"] = (node.get("emoji") or {}).get("name")
        out["disabled"] = bool(node.get("disabled"))
        out["link"] = "url" in node
    elif node.get("custom_id"):  # a form field: radio group, checkbox, ...
        out["custom_id"] = node["custom_id"]
    if "required" in node:
        out["required"] = node["required"]
    if node.get("options"):
        # The values the bot mints and refuses submits by; their labels are copy.
        out["options"] = [option.get("value") for option in node["options"]]
    if isinstance(node.get("component"), Mapping):  # a modal label wraps one field
        out["component"] = _shape(node["component"])
    if node.get("components"):
        out["components"] = [_shape(child) for child in node["components"]]
    return out


def _view_shape(view: discord.ui.LayoutView) -> list[dict[str, Any]]:
    return [_shape(component) for component in view.to_components()]


def _modal_shape(modal: discord.ui.Modal) -> dict[str, Any]:
    data = modal.to_dict()
    return {"custom_id": data.get("custom_id"), "components": [_shape(c) for c in data.get("components") or ()]}


def _dispatcher() -> ActionDispatcher:
    return ActionDispatcher(site_url=SITE, broker=lambda: None)


def _mix_state(**overrides: Any) -> dict[str, Any]:
    """The ``self_*`` wire answer: a seated player who may reorder their roles."""
    state: dict[str, Any] = {
        "custom_game_id": 42,
        "name": "Пятничный микс",
        "status": "balanced",
        "lobby_count": 1,
        "seat": {
            "participation": "pool",
            "roles": ["tank", "support"],
            "is_flex": False,
            "ranks": {"tank": 3100, "damage": None, "support": None},
            "divisions": {"tank": {"name": "Gold 3", "slug": "gold-3"}, "damage": None, "support": None},
            "current_lobby": None,
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


def _seat(**overrides: Any) -> dict[str, Any]:
    seat = dict(_mix_state()["seat"])
    seat.update(overrides)
    return seat


def _invite_card() -> DiscordCard:
    """A DM notification card: two action buttons plus a link row."""
    return DiscordCard(
        text="### Team invite",
        answers=[
            {"type": "action", "label": "Accept", "action": "invite.accept", "target": "42", "style": "success"},
            {"type": "action", "label": "Decline", "action": "invite.decline", "target": "42", "style": "danger"},
        ],
        rows=[
            [
                {"type": "link", "label": "View participants", "url": f"{SITE}/tournaments/3/participants"},
                {
                    "type": "action",
                    "label": "Уведомления",
                    "action": "notifications.menu",
                    "target": "all",
                    "emoji": "bell_off",
                },
            ],
        ],
    )


def _surfaces() -> dict[str, Any]:
    """Every surface the bot lays out itself, by golden-file name."""
    dispatcher = _dispatcher()

    def panel(state: Mapping[str, Any]) -> list[dict[str, Any]]:
        return _view_shape(dispatcher.reply(Outcome("ok", state), "mix.roles", LOCALE))

    locked = _mix_state()
    locked["policy"] = {**locked["policy"], "can_edit_roles": False, "edit_blocker": "role_edit_off"}
    two_lobbies = _mix_state(lobby_count=2, seat=_seat(current_lobby=1))
    joinable = _mix_state(seat=None)
    joinable["policy"] = {"can_join": True, "can_leave": False, "can_edit_roles": False, "edit_blocker": None}

    settled = settle(
        card_view(_invite_card()),
        retire=ACTIONS["invite.accept"].settles,
        note="-# Приглашение принято",
    )
    assert settled is not None

    return {
        # The seat panel, every state the policy can put it in.
        "seat_panel_pool": panel(_mix_state()),
        "seat_panel_benched": panel(_mix_state(seat=_seat(participation="benched"))),
        "seat_panel_not_seated": panel(joinable),
        "seat_panel_role_edit_locked": panel(locked),
        "seat_panel_two_lobbies": panel(two_lobbies),
        # The one-sentence replies, one per outcome.
        "reply_ok": _view_shape(dispatcher.reply(Outcome("ok"), "check_in", LOCALE)),
        "reply_not_linked": _view_shape(dispatcher.reply(Outcome("not_linked"), "check_in", LOCALE)),
        "reply_inactive": _view_shape(dispatcher.reply(Outcome("inactive"), "check_in", LOCALE)),
        "reply_unavailable": _view_shape(dispatcher.reply(Outcome("unavailable"), "check_in", LOCALE)),
        "reply_mix_blocker_link": _view_shape(
            dispatcher.reply(Outcome("failed", code="battlenet_not_linked"), "mix.join", LOCALE)
        ),
        "reply_failed": _view_shape(dispatcher.reply(Outcome("failed", code="internal"), "check_in", LOCALE)),
        # The prompt the DM card's own button opens, and the card after a click.
        "notifications_mute_prompt": _view_shape(dispatcher.reply(Outcome("ok"), "notifications.menu", LOCALE)),
        "dm_card_settled": _view_shape(settled),
        # The seat form: its field ids and the values it may answer with.
        "seat_modal": _modal_shape(seat_modal(LOCALE, 42, ["tank", "support"], False)),
        "seat_modal_any_ranked": _modal_shape(seat_modal(LOCALE, 42, None, True)),
    }


class CardLayoutGoldenTests(TestCase):
    """Each surface against its golden skeleton; ``UPDATE_LAYOUTS=1`` rewrites them."""

    def test_every_surface_keeps_its_shape(self) -> None:
        update = os.environ.get("UPDATE_LAYOUTS") == "1"
        if update:
            LAYOUTS.mkdir(exist_ok=True)
        for name, shape in _surfaces().items():
            with self.subTest(name):
                path = LAYOUTS / f"{name}.json"
                if update:
                    path.write_text(json.dumps(shape, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                    continue
                self.assertTrue(path.is_file(), f"missing golden {path.name}; rerun with UPDATE_LAYOUTS=1")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), shape)

    def test_no_golden_is_left_behind_by_a_deleted_surface(self) -> None:
        self.assertEqual(
            sorted(path.stem for path in LAYOUTS.glob("*.json")),
            sorted(_surfaces()),
        )


class ShapeReducerTests(TestCase):
    def test_copy_is_not_part_of_the_pinned_shape(self) -> None:
        """The whole point: rewording a label or moving a link changes nothing here."""
        card = DiscordCard(text="### Before", rows=[[{"type": "link", "label": "Open", "url": f"{SITE}/a"}]])
        reworded = DiscordCard(text="### After", rows=[[{"type": "link", "label": "Go", "url": f"{SITE}/b"}]])

        self.assertEqual(_view_shape(card_view(card)), _view_shape(card_view(reworded)))

    def test_a_renamed_custom_id_or_a_flipped_style_is_caught(self) -> None:
        before = DiscordCard(
            text="x", rows=[[{"type": "action", "label": "Join", "action": "mix.join", "target": "1"}]]
        )
        renamed = DiscordCard(
            text="x", rows=[[{"type": "action", "label": "Join", "action": "mix.leave", "target": "1"}]]
        )
        restyled = DiscordCard(
            text="x",
            rows=[[{"type": "action", "label": "Join", "action": "mix.join", "target": "1", "style": "danger"}]],
        )

        self.assertNotEqual(_view_shape(card_view(before)), _view_shape(card_view(renamed)))
        self.assertNotEqual(_view_shape(card_view(before)), _view_shape(card_view(restyled)))
