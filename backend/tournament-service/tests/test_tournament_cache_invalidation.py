"""The local half of an invalidation: resources -> dropped cashews keys.

WHICH keys a resource maps to is asserted in ``test_cache_resources.py``; this
file covers the loop that applies them — scope filtering, deduplication across
overlapping resources, and the routability contract cashews imposes at runtime.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from cashews import cache

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

cache_invalidation = importlib.import_module("src.services.tournament.cache_invalidation")
form_service_module = importlib.import_module("src.services.registration.form_service")

from shared.domain.forms import FormField, default_schema  # noqa: E402
from shared.services.realtime import Resource, Scope  # noqa: E402

# Mirrors the prefixes registered by ``src.core.caching.configure_cache()`` in
# production. cashews routes ``delete_match`` to the backend whose registered
# prefix the key starts with, so a pattern that starts with neither is
# unroutable and raises ``NotConfiguredError`` at runtime.
_CONFIGURED_PREFIXES = ("fastapi:", "backend:")

_ALL_TOURNAMENT_RESOURCES = frozenset(resource for resource in Resource if str(resource).startswith("tournament."))


class InvalidateTournamentResourcesTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Reproduce production routing: only prefixed backends, no default.
        for prefix in _CONFIGURED_PREFIXES:
            cache.setup("mem://", prefix=prefix)

    async def _dropped(self, scope: Scope, resources: frozenset[Resource]) -> list[str]:
        with patch.object(cache, "delete_match", AsyncMock()) as delete_match:
            await cache_invalidation.invalidate_tournament_resources(scope, resources)
        return [call.args[0] for call in delete_match.await_args_list]

    async def test_encounters_drops_encounter_and_standings_keys(self) -> None:
        # Standings embed matches_history, built from completed encounters, so a
        # score report moves them even though no standings row was written.
        patterns = await self._dropped(Scope.tournament(42), frozenset({Resource.TOURNAMENT_ENCOUNTERS}))

        self.assertTrue(any("encounters" in pattern for pattern in patterns))
        self.assertTrue(any("standings" in pattern for pattern in patterns))
        self.assertFalse(any("tournaments/42" in pattern for pattern in patterns))
        self.assertFalse(any("teams" in pattern for pattern in patterns))

    async def test_registrations_leaves_teams_standings_and_encounters_cached(self) -> None:
        # The tournament read embeds live participants_count/registrations_count
        # and the public list is cached as `registration_list:{id}:`. Nothing
        # else moves on a registration write.
        patterns = await self._dropped(Scope.tournament(42), frozenset({Resource.TOURNAMENT_REGISTRATIONS}))

        self.assertTrue(any("tournaments/42" in pattern for pattern in patterns))
        self.assertTrue(any("registration_list:42:" in pattern for pattern in patterns))
        self.assertFalse(any("teams" in pattern for pattern in patterns))
        self.assertFalse(any("standings" in pattern for pattern in patterns))
        self.assertFalse(any("encounters" in pattern for pattern in patterns))

    async def test_overlapping_resources_drop_each_pattern_once(self) -> None:
        # `structure` subsumes `detail`, and a Redis SCAN per pattern is the whole
        # cost of an invalidation — a union of resources must not pay it twice.
        patterns = await self._dropped(
            Scope.tournament(42),
            frozenset({Resource.TOURNAMENT_STRUCTURE, Resource.TOURNAMENT_DETAIL}),
        )

        self.assertEqual(len(patterns), len(set(patterns)))

    async def test_non_tournament_scope_drops_nothing(self) -> None:
        # The shared invalidator hands this process every scope it emits, and a
        # workspace id is not a tournament id — matching on it would purge an
        # unrelated tournament's reads.
        patterns = await self._dropped(Scope.workspace(42), frozenset({Resource.WORKSPACE_LOGS}))

        self.assertEqual(patterns, [])

    async def test_every_resource_is_routable_at_runtime(self) -> None:
        # Not a pattern-shape assertion (that is test_cache_resources.py) but the
        # end-to-end one: cashews itself must accept every pattern the whole
        # tournament vocabulary produces, in a single union.
        await cache_invalidation.invalidate_tournament_resources(Scope.tournament(42), _ALL_TOURNAMENT_RESOURCES)


class _FakeSession:
    """Only what ``save_schema`` touches: the version-number read, flush, commit."""

    async def execute(self, _statement: Any) -> Any:
        return SimpleNamespace(scalar_one_or_none=lambda: 1)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


class SchemaSaveInvalidationTests(IsolatedAsyncioTestCase):
    """The join the tests above stop short of: what a schema save actually emits,
    put through the real invalidator against a real cache entry."""

    async def asyncSetUp(self) -> None:
        for prefix in _CONFIGURED_PREFIXES:
            cache.setup("mem://", prefix=prefix)

    async def test_a_schema_save_purges_the_public_registration_list(self) -> None:
        # Redacting a field to `organizers` must take effect for the rows whose
        # `form_version_id` is NULL — they are rendered against the CURRENT
        # schema, so the cached anonymous list is stale the moment it is saved.
        key = "fastapi:registration_list:42:"
        await cache.set(key, ["stale payload"])
        redacted = default_schema()
        redacted.sections[2].fields.append(FormField(key="vk", kind="url", label="VK", visibility="organizers"))
        form = SimpleNamespace(
            id=1,
            tournament_id=42,
            current_version=SimpleNamespace(schema_json=default_schema().model_dump(mode="json")),
            current_version_id=None,
        )
        emitted: list[tuple[Scope, frozenset[Resource]]] = []

        async def _emit(_session: Any, *, scope: Scope, invalidates: Any, **_kwargs: Any) -> None:
            emitted.append((scope, frozenset(invalidates)))

        with (
            patch.object(form_service_module, "emit", _emit),
            patch.object(form_service_module.form_service, "get_form", AsyncMock(return_value=form)),
        ):
            await form_service_module.form_service.save_schema(_FakeSession(), form, redacted, actor_user_id=None)

        self.assertEqual(len(emitted), 1)
        scope, resources = emitted[0]
        await cache_invalidation.invalidate_tournament_resources(scope, resources)

        self.assertIsNone(await cache.get(key))
