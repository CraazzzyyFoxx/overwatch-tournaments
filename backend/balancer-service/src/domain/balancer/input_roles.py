from __future__ import annotations

from collections.abc import Mapping

from shared.core.enums import HeroClass


def normalize_standard_role_code(raw_role: str | None) -> str | None:
    """Any accepted spelling of a game role -> its canonical slot code.

    Just ``HeroClass.parse`` narrowed to the three game roles: ``flex`` is a
    SLOT, not a role, so no game role may resolve to it -- a flex slot is worth
    the best role the player actually plays, synthesized in
    ``player_loader.parse_player_node``. ``None`` for anything else, which the
    caller reads as "not a role this roster fields" and skips.
    """
    parsed = HeroClass.parse(raw_role)
    return None if parsed is None or parsed is HeroClass.flex else parsed.slot_code


def resolve_input_role_name(raw_role: str | None, role_mask: Mapping[str, int]) -> str | None:
    """Map an input JSON role name onto the algorithm's role key.

    Prefers the mask's own spelling, so a legacy config saved with
    ``{"Tank": 1, "Damage": 2, "Support": 2}`` keeps resolving to its own keys.
    Falls back to the canonical code when the mask has no slot for the role at
    all: a role the roster does not field is still part of what the player can
    do, and the caller needs it both to synthesize a flex rating and to report
    the full ``all_ratings`` snapshot.
    """
    if raw_role is None:
        return None

    normalized_value = raw_role.strip()
    if not normalized_value:
        return None

    if normalized_value in role_mask:
        return normalized_value

    lowered_value = normalized_value.lower()
    for role_name in role_mask:
        if role_name.lower() == lowered_value:
            return role_name

    normalized_code = normalize_standard_role_code(normalized_value)
    if normalized_code is None:
        return None

    for role_name in role_mask:
        if normalize_standard_role_code(role_name) == normalized_code:
            return role_name

    return normalized_code
