"""Parity gate: the Resource enum IS the manifest.

The manifest (``shared/realtime/resources.json``) is the vocabulary four tables
mirror — this enum, the gateway's URL patterns, the frontend's query keys, and
each service's cashews globs. Each has a test like this one. Together they are
the only mechanical guarantee that a publisher cannot name a resource some
consumer has never heard of; the previous rail had no such gate, and its three
``reason``-to-keys tables drifted apart until a draft pick evicted an entire
tournament's cache while a balancer export evicted nothing.
"""

from __future__ import annotations

import json

from shared.services.realtime import MANIFEST_PATH, Resource, load_manifest, route_refresh_resources
from shared.services.realtime.scope import ScopeKind


def test_enum_mirrors_manifest() -> None:
    declared = set(load_manifest()["resources"])
    enumerated = {str(resource) for resource in Resource}

    assert enumerated == declared, (
        f"missing from the enum: {sorted(declared - enumerated)}; "
        f"absent from the manifest: {sorted(enumerated - declared)}"
    )


def test_every_resource_declares_a_known_scope() -> None:
    kinds = {ScopeKind.TOURNAMENT, ScopeKind.WORKSPACE, ScopeKind.USER}
    for name, spec in load_manifest()["resources"].items():
        assert ScopeKind(spec["scope"]) in kinds, name


def test_resource_name_matches_its_scope() -> None:
    # `tournament.teams` under a workspace scope would be published to a topic
    # whose audience is a different set of people; the prefix is what makes the
    # mismatch visible at a glance, and `emit` enforces it at runtime.
    for name, spec in load_manifest()["resources"].items():
        assert name.startswith(f"{spec['scope']}."), name


def test_route_refresh_is_read_from_the_manifest() -> None:
    declared = {name for name, spec in load_manifest()["resources"].items() if spec.get("route_refresh")}

    assert {str(r) for r in route_refresh_resources()} == declared


def test_manifest_is_valid_json_at_the_declared_version() -> None:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    # A version bump means the event payload shape changed: the gateway's
    # eventResources(), the frontend's onEvent and every consumer table have to
    # be revisited together, so it must not pass silently.
    assert raw["version"] == 1
