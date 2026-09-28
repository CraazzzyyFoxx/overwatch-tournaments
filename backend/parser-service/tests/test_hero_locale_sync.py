from __future__ import annotations

import importlib
import inspect
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, mock

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["DEBUG"] = "true"

models = importlib.import_module("src.models")
schemas = importlib.import_module("src.schemas")
_hero_service_module = importlib.import_module("src.services.hero.service")
_hero_aliases = importlib.import_module("src.domain.hero_aliases")
_overfast_client_module = importlib.import_module("src.clients.overfast")
HeroService = _hero_service_module.HeroService
merge_aliases = _hero_aliases.merge_aliases

# Two heroes, three of the thirteen locales carrying a distinct name; every
# other locale falls back to the canonical spelling, exactly like OverFast does
# for names Blizzard does not localise (e.g. "Genji" in de-de).
LOCALIZED_NAMES: dict[str, dict[str, str]] = {
    "ana": {"en-us": "Ana", "ru-ru": "Ана", "ja-jp": "アナ", "ko-kr": "아나"},
    "genji": {"en-us": "Genji", "ru-ru": "Гэндзи", "ja-jp": "ゲンジ"},
}
ROLES = {"ana": "support", "genji": "damage"}


class _FakeOverfastCatalogClient:
    """Test double for ``OverFastCatalogClient`` — records every requested
    locale instead of making an HTTP call, per the constructor-injected
    collaborator pattern every other domain in this refactor uses."""

    def __init__(self, locales: list[str]) -> None:
        self._locales = locales

    async def fetch_heroes(self, locale: str) -> list:
        self._locales.append(locale)
        return [
            schemas.OverfastHero(
                key=key,
                name=names.get(locale, names["en-us"]),
                portrait=f"https://cdn/{key}.png",
                role=ROLES[key],
            )
            for key, names in LOCALIZED_NAMES.items()
        ]


class _FakeImageMirror:
    """Test double for ``CatalogImageMirror``: records what it was asked to
    resolve and answers with a bucket URL per slug."""

    def __init__(self) -> None:
        self.requests: dict[str, dict[str, tuple[str | None, str]]] = {}

    async def resolve_many(self, kind: str, images: dict[str, tuple[str | None, str]]) -> dict[str, str]:
        self.requests[kind] = images
        return {slug: f"https://bucket/{kind}/{slug}.png" for slug in images}


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add_all(self, objects: list[object]) -> None:
        self.added.extend(objects)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class HeroLocaleSyncTests(IsolatedAsyncioTestCase):
    def test_all_thirteen_blizzard_locales_are_covered(self) -> None:
        self.assertEqual(
            {
                "de-de",
                "en-gb",
                "en-us",
                "es-es",
                "es-mx",
                "fr-fr",
                "it-it",
                "ja-jp",
                "ko-kr",
                "pl-pl",
                "pt-br",
                "ru-ru",
                "zh-tw",
            },
            {_hero_service_module.CANONICAL_LOCALE, *_hero_service_module.ALIAS_LOCALES},
        )
        self.assertNotIn(_hero_service_module.CANONICAL_LOCALE, _hero_service_module.ALIAS_LOCALES)
        self.assertEqual(12, len(_hero_service_module.ALIAS_LOCALES), "no duplicate alias locales")

    def test_the_request_is_keyed_on_locale_not_role(self) -> None:
        # Scoped to the request line, not the whole body: the surrounding comment
        # legitimately explains why the `role` filter went away. The HTTP request
        # itself lives on the shared OverFastCatalogClient (also used by
        # map/gamemode sync), not on HeroService.
        request_line = next(
            line
            for line in inspect.getsource(_overfast_client_module.OverFastCatalogClient.fetch_heroes).splitlines()
            if "self._http.get(" in line
        )
        self.assertIn("locale={locale}", request_line)
        self.assertNotIn("role=", request_line)

    def test_aliases_union_existing_and_exclude_the_canonical_name(self) -> None:
        merged = merge_aliases(existing=["Ана"], localized={"Ana", "アナ", "Ана"}, canonical="Ana")
        self.assertEqual(["Ана", "アナ"], merged)

    def test_a_manual_alias_survives_a_sync(self) -> None:
        merged = merge_aliases(existing=["Анка"], localized={"Ана"}, canonical="Ana")
        self.assertIn("Анка", merged)

    async def test_fetch_heroes_requests_the_locale_endpoint(self) -> None:
        locales: list[str] = []
        service = HeroService(overfast=_FakeOverfastCatalogClient(locales))

        heroes = await service.fetch_heroes("ru-ru")

        self.assertEqual(["ru-ru"], locales)
        self.assertEqual(["Ана", "Гэндзи"], [hero.name for hero in heroes])

    async def test_initial_create_hits_every_locale_exactly_once(self) -> None:
        locales: list[str] = []
        session = _FakeSession()
        service = HeroService(overfast=_FakeOverfastCatalogClient(locales), images=_FakeImageMirror())
        with mock.patch.object(service, "get_by_slugs", mock.AsyncMock(return_value={})):
            await service.initial_create(session)  # type: ignore[arg-type]

        self.assertEqual(13, len(locales), f"one round-trip per Blizzard locale, got {locales}")
        self.assertEqual(
            {_hero_service_module.CANONICAL_LOCALE, *_hero_service_module.ALIAS_LOCALES},
            set(locales),
        )
        self.assertEqual(_hero_service_module.CANONICAL_LOCALE, locales[0])

    async def test_initial_create_creates_new_heroes_with_localized_aliases(self) -> None:
        locales: list[str] = []
        session = _FakeSession()
        service = HeroService(overfast=_FakeOverfastCatalogClient(locales), images=_FakeImageMirror())
        with mock.patch.object(service, "get_by_slugs", mock.AsyncMock(return_value={})):
            await service.initial_create(session)  # type: ignore[arg-type]

        created = {hero.slug: hero for hero in session.added}
        self.assertEqual({"ana", "genji"}, set(created))
        self.assertEqual("Ana", created["ana"].name)
        self.assertEqual("support", created["ana"].type)
        self.assertEqual("https://bucket/heroes/ana.png", created["ana"].image_path)
        self.assertEqual(["Ана", "アナ", "아나"], created["ana"].aliases)
        self.assertNotIn("Ana", created["ana"].aliases, "canonical name never lands in aliases")

    async def test_initial_create_refreshes_aliases_and_image_of_existing_heroes_without_touching_the_rest(
        self,
    ) -> None:
        existing = models.Hero(
            slug="ana",
            name="Ana (stale)",
            image_path="https://cdn/old-ana.png",
            type="support",  # type: ignore[arg-type]
            aliases=["Анка"],
        )
        locales: list[str] = []
        session = _FakeSession()
        images = _FakeImageMirror()
        service = HeroService(overfast=_FakeOverfastCatalogClient(locales), images=images)
        with mock.patch.object(service, "get_by_slugs", mock.AsyncMock(return_value={"ana": existing})):
            await service.initial_create(session)  # type: ignore[arg-type]

        # Pre-existing row is not re-inserted and keeps its own columns.
        self.assertEqual(["genji"], [hero.slug for hero in session.added])
        self.assertEqual("Ana (stale)", existing.name)
        # The mirror sees the row's current image next to OverFast's, and its
        # answer is what the row stores.
        self.assertEqual(("https://cdn/old-ana.png", "https://cdn/ana.png"), images.requests["heroes"]["ana"])
        self.assertEqual("https://bucket/heroes/ana.png", existing.image_path)
        # The hand-added alias survives, the localisations are appended, and the
        # canonical OverFast name is excluded.
        self.assertEqual(["Ana", "Ана", "Анка", "アナ", "아나"], existing.aliases)
        self.assertGreaterEqual(session.commits, 1)
