"""The Pydantic edge of the draft format: one field type, one projection.

The format is a rule of the draft formation node, not a per-draft choice: ``FlowNode.config["draft_format"]``
stores it and ``rpc.balancer.draft.session_create`` copies it onto the session it creates. Both sides live in
different services, so the normalize-or-reject step and the node -> session projection live here once, beside
``roster_slots.py``, instead of being mirrored per service.

The bound field stores the **normalized** payload, never the raw input:
``round_rules`` and ``avg_tie_seed_reverse`` are meaningless outside ``custom``,
so a snake node can never carry rules that would silently apply if the
format were switched back.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, model_validator

from shared.core.enums import DraftFormat, DraftRoundRule

__all__ = (
    "DraftFormatField",
    "DraftFormatSettings",
    "normalize_draft_format",
    "session_format",
)


class DraftFormatSettings(BaseModel):
    """The draft format of a formation node. ``None`` in its config means these defaults."""

    format: DraftFormat = DraftFormat.SNAKE
    round_rules: list[DraftRoundRule] = []
    avg_tie_seed_reverse: bool = False

    @model_validator(mode="after")
    def _custom_only_fields(self) -> DraftFormatSettings:
        """Drop the per-round knobs unless the format actually reads them."""
        if self.format is not DraftFormat.CUSTOM:
            self.round_rules = []
            self.avg_tie_seed_reverse = False
        return self


def normalize_draft_format(value: Any) -> Any:
    """``None`` passes through (inherit the snake default); anything else is normalized."""
    if value is None:
        return None
    return DraftFormatSettings.model_validate(value).model_dump(mode="json")


DraftFormatField = Annotated[dict[str, Any] | None, BeforeValidator(normalize_draft_format)]


def session_format(raw: dict[str, Any] | None, rounds: int) -> tuple[DraftFormat, dict[str, Any]]:
    """Project a node's stored format onto a new session: ``(format, settings_json keys)``.

    The roster shape may have changed since the format was saved, so the rules are
    padded with ``linear`` or truncated to the session's actual round count.
    Non-custom formats contribute no keys at all.
    """
    settings = DraftFormatSettings.model_validate(raw or {})
    if settings.format is not DraftFormat.CUSTOM:
        return settings.format, {}
    rules = [rule.value for rule in settings.round_rules[:rounds]]
    rules += [DraftRoundRule.LINEAR.value] * (rounds - len(rules))
    return settings.format, {"round_rules": rules, "avg_tie_seed_reverse": settings.avg_tie_seed_reverse}
