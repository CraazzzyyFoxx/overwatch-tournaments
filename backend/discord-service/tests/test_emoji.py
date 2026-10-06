"""How shortcodes become what a reader sees, uploaded or not."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from src.interactions.emoji import EmojiRegistry


class _Uploaded(SimpleNamespace):
    def __str__(self) -> str:
        return f"<:owt_{self.name}:{self.id}>"


class RenderTests(TestCase):
    def setUp(self) -> None:
        self.registry = EmojiRegistry()
        self.registry._uploaded = {"tank": _Uploaded(name="tank", id=7)}

    def test_an_uploaded_emoji_wins_over_its_fallback(self) -> None:
        self.assertEqual(self.registry.render(":owt_tank: Танк"), "<:owt_tank:7> Танк")

    def test_a_missing_emoji_falls_back_to_unicode(self) -> None:
        self.assertEqual(self.registry.render(":owt_support: Саппорт"), "💉 Саппорт")

    def test_a_badge_with_nothing_to_show_takes_its_space_along(self) -> None:
        self.assertEqual(self.registry.render("Танк — :owt_div_gold_3: Gold 3"), "Танк — Gold 3")
