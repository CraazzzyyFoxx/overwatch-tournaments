from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, mock

import httpx

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["DEBUG"] = "true"

models = importlib.import_module("src.models")
schemas = importlib.import_module("src.schemas")
_images_module = importlib.import_module("src.services.catalog_images")
_map_service_module = importlib.import_module("src.services.map.service")
_overfast_module = importlib.import_module("src.clients.overfast")
CatalogImageMirror = _images_module.CatalogImageMirror

BUCKET = "https://s3.test/bucket"


class _FakeS3:
    def __init__(self, *, upload_ok: bool = True) -> None:
        self.uploads: dict[str, tuple[bytes, str, bool]] = {}
        self._upload_ok = upload_ok

    def get_public_url(self, key: str) -> str:
        return f"{BUCKET}/{key}"

    async def put_object(self, key: str, data: bytes, content_type: str, *, public: bool = False) -> bool:
        self.uploads[key] = (data, content_type, public)
        return self._upload_ok


class _FakeOverfast:
    def __init__(self, maps: list | None = None) -> None:
        self.fetched: list[str] = []
        self._maps = maps or []

    async def fetch_image(self, url: str) -> tuple[bytes, str]:
        self.fetched.append(url)
        return b"img:" + url.encode(), "image/jpeg"

    async def fetch_maps(self, gamemode_slug: str) -> list:
        return self._maps


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add_all(self, objects: list[object]) -> None:
        self.added.extend(objects)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


class CatalogImageMirrorTests(IsolatedAsyncioTestCase):
    async def test_external_images_are_copied_to_the_bucket_and_mirrored_ones_are_left_alone(self) -> None:
        s3, overfast = _FakeS3(), _FakeOverfast()
        mirror = CatalogImageMirror(s3=s3, overfast=overfast)  # type: ignore[arg-type]

        urls = await mirror.resolve_many(
            "maps",
            {
                "ilios": (f"{BUCKET}/assets/overwatch/maps/ilios-custom.png", "https://overfast/static/maps/ilios.jpg"),
                "neon-junction": (
                    "https://overfast/static/maps/neon-junction.jpg",
                    "https://overfast/static/maps/neon-junction.JPG",
                ),
            },
        )

        self.assertEqual(f"{BUCKET}/assets/overwatch/maps/ilios-custom.png", urls["ilios"])
        self.assertEqual(f"{BUCKET}/assets/overwatch/maps/neon-junction.jpg", urls["neon-junction"])
        self.assertEqual(["https://overfast/static/maps/neon-junction.JPG"], overfast.fetched)
        self.assertEqual(
            {
                "assets/overwatch/maps/neon-junction.jpg": (
                    b"img:https://overfast/static/maps/neon-junction.JPG",
                    "image/jpeg",
                    True,
                )
            },
            s3.uploads,
        )

    async def test_a_failed_upload_fails_the_sync_instead_of_storing_a_dead_url(self) -> None:
        mirror = CatalogImageMirror(s3=_FakeS3(upload_ok=False), overfast=_FakeOverfast())  # type: ignore[arg-type]

        with self.assertRaises(RuntimeError):
            await mirror.resolve_many("heroes", {"ana": (None, "https://cdn/ana.png")})

    async def test_fetch_image_refuses_a_non_image_response(self) -> None:
        client = _overfast_module.OverFastCatalogClient(base_url="https://overfast.test")
        client._http.get = mock.AsyncMock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=b"<html>",
                request=httpx.Request("GET", "https://overfast.test/static/maps/x.jpg"),
            )
        )

        with self.assertRaises(ValueError):
            await client.fetch_image("https://overfast.test/static/maps/x.jpg")


class MapSyncImageTests(IsolatedAsyncioTestCase):
    async def test_sync_moves_maps_onto_the_bucket_and_never_back_to_overfast(self) -> None:
        # The regression: every map sync used to overwrite `image_path` with the
        # OverFast screenshot URL, which the site cannot load.
        control = models.Gamemode(id=1, slug="control", name="Control")
        mirrored = models.Map(id=1, gamemode_id=1, name="Ilios", image_path=f"{BUCKET}/assets/overwatch/maps/ilios.jpg")
        stale = models.Map(
            id=2, gamemode_id=1, name="Lijiang Tower", image_path="https://overfast/static/maps/lijiang.jpg"
        )
        overfast = _FakeOverfast(
            maps=[
                schemas.OverfastMap(
                    name=name,
                    screenshot=f"https://overfast/static/maps/{slug}.jpg",
                    gamemodes=["control"],
                    location="",
                    country_code=None,
                )
                for name, slug in (("Ilios", "ilios"), ("Lijiang Tower", "lijiang-tower"), ("Samoa", "samoa"))
            ]
        )
        service = _map_service_module.MapService(
            overfast=overfast,  # type: ignore[arg-type]
            images=CatalogImageMirror(s3=_FakeS3(), overfast=overfast),  # type: ignore[arg-type]
        )
        session = _FakeSession()

        with (
            mock.patch.object(
                _map_service_module.gamemode_service, "get_all", mock.AsyncMock(return_value=([control], 1))
            ),
            mock.patch.object(
                service, "get_by_names", mock.AsyncMock(return_value={"Ilios": mirrored, "Lijiang Tower": stale})
            ),
        ):
            await service.initial_create(session)  # type: ignore[arg-type]

        self.assertEqual(f"{BUCKET}/assets/overwatch/maps/ilios.jpg", mirrored.image_path)
        self.assertEqual(f"{BUCKET}/assets/overwatch/maps/lijiang-tower.jpg", stale.image_path)
        (samoa,) = session.added
        self.assertEqual(f"{BUCKET}/assets/overwatch/maps/samoa.jpg", samoa.image_path)
        self.assertNotIn(
            "https://overfast/static/maps/ilios.jpg", overfast.fetched, "a mirrored map is not re-downloaded"
        )
