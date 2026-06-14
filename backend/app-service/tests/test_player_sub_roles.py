from shared.domain.player_sub_roles import (
    legacy_flags_to_sub_role,
    normalize_sub_role,
    sub_role_to_legacy_flags,
)


def test_legacy_flags_to_sub_role_maps_current_damage_and_support_specializations() -> None:
    assert legacy_flags_to_sub_role("Damage", primary=True, secondary=False) == "hitscan"
    assert legacy_flags_to_sub_role("Damage", primary=False, secondary=True) == "projectile"
    assert legacy_flags_to_sub_role("Support", primary=True, secondary=False) == "main_heal"
    assert legacy_flags_to_sub_role("Support", primary=False, secondary=True) == "light_heal"


def test_legacy_flags_to_sub_role_returns_none_for_ambiguous_or_base_roles() -> None:
    assert legacy_flags_to_sub_role("Tank", primary=True, secondary=False) is None
    assert legacy_flags_to_sub_role("Damage", primary=True, secondary=True) is None
    assert legacy_flags_to_sub_role("Support", primary=False, secondary=False) is None


def test_sub_role_to_legacy_flags_only_maps_known_legacy_specializations() -> None:
    assert sub_role_to_legacy_flags("Damage", "hitscan") == (True, False)
    assert sub_role_to_legacy_flags("Damage", "projectile") == (False, True)
    assert sub_role_to_legacy_flags("Support", "main_heal") == (True, False)
    assert sub_role_to_legacy_flags("Support", "light_heal") == (False, True)
    assert sub_role_to_legacy_flags("Support", "flex_support") == (False, False)


def test_normalize_sub_role_keeps_dynamic_values_but_clears_empty_strings() -> None:
    assert normalize_sub_role("  Flex Support  ") == "flex_support"
    assert normalize_sub_role("anchor-tank") == "anchor-tank"
    assert normalize_sub_role("   ") is None
    assert normalize_sub_role(None) is None
