"""Public discipline metadata (P7 §1): descriptors, scoped ontology, vocabularies, hidden-workspace authorization.

Real PostgreSQL inside a rolled-back transaction; the handlers run through the RPC harness with the installed modules.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import sys
import uuid
from contextlib import asynccontextmanager
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.disciplines import DISCIPLINES, DisciplineSpec
from shared.repository import CatalogRoleRepository
from shared.services.ontology import project_disciplines
from shared.testing import create_test_async_engine, ensure_test_postgres
from src import openapi_docs, openapi_schemas
from src.rpc import disciplines as disciplines_rpc
from src.services import discipline as discipline_service
from tests.conftest import RpcHarness, _CaptureBroker

LIST = "rpc.app.disciplines.list"
METADATA = "rpc.app.disciplines.metadata"
ORIGIN = "https://s3.test/aqt"


def _viewer(user_id: int, *workspace_ids: int, superuser: bool = False) -> dict:
    return {
        "user_id": user_id,
        "is_active": True,
        "is_superuser": superuser,
        "workspaces": [{"workspace_id": ws, "rbac_roles": [], "rbac_permissions": []} for ws in workspace_ids],
    }


def test_both_subjects_are_registered_documented_and_typed() -> None:
    broker = _CaptureBroker()
    disciplines_rpc.register(broker, logging.getLogger("discipline-metadata-tests"))
    assert set(broker.handlers) == {LIST, METADATA}
    for subject in (LIST, METADATA):
        assert openapi_docs.DOCS[subject]["summary"]
        assert openapi_schemas.OPERATIONS[subject].response is not None


def test_the_scope_query_param_is_documented_as_an_id_or_the_literal_all() -> None:
    for subject in (LIST, METADATA):
        (param,) = openapi_schemas.OPERATIONS[subject].query_params
        assert (param.name, param.type, param.array, param.required) == ("workspace_id", "string", False, False)
        assert "all" in param.description and "integer" in param.description
        assert param is not openapi_schemas._WS  # the plain integer param would reject the literal


def test_a_descriptor_carries_the_module_marks_and_falls_back_to_the_name() -> None:
    bare = discipline_service._descriptor(DisciplineSpec("x", "Xgame"), enabled=True)
    assert (bare.short_name, bare.icon) == ("Xgame", None)
    spec = DisciplineSpec("x", "Xgame", short_name="XG", icon="assets/x/icon.svg")
    with patch.object(discipline_service.config.settings, "s3_public_url", ORIGIN):
        marked = discipline_service._descriptor(spec, enabled=False)
    assert (marked.short_name, marked.icon) == ("XG", f"{ORIGIN}/assets/x/icon.svg")
    with patch.object(discipline_service.config.settings, "s3_public_url", None):
        assert discipline_service._descriptor(spec, enabled=False).icon is None  # the monogram, not a 500


def test_every_installed_game_declares_its_own_short_name() -> None:
    names = [spec.short_name for spec in DISCIPLINES.values()]
    assert all(names)
    assert len(set(names)) == len(names)


class DisciplineMetadataTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg async cannot run on the Proactor loop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        await project_disciplines(self.session)  # the declared rows, whatever the shared database last saw
        self.tag = uuid.uuid4().hex[:10]
        self.roles = CatalogRoleRepository()

        @asynccontextmanager
        async def _factory():  # the handler's own session is this rolled-back one
            yield self.session

        self._original = disciplines_rpc._SF
        disciplines_rpc._SF = _factory
        patcher = patch.object(discipline_service.config.settings, "s3_public_url", ORIGIN)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.rpc = RpcHarness().register(disciplines_rpc)

    async def asyncTearDown(self) -> None:
        disciplines_rpc._SF = self._original
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    async def workspace(self, suffix: str, *, hidden: bool = False, enabled=("overwatch",)) -> models.Workspace:
        workspace = models.Workspace(
            slug=f"{self.tag}-{suffix}",
            name=f"{self.tag}-{suffix}",
            disciplines_enabled=list(enabled),
            verification_status="verified",
            is_hidden=hidden,
        )
        self.session.add(workspace)
        await self.session.flush()
        return workspace

    async def child(self, workspace_id: int, parent: str, code: str, **fields) -> models.CatalogRole:
        parent_row = await self.roles.resolve(
            self.session, discipline="overwatch", workspace_id=None, dimension=None, code=parent
        )
        row = models.CatalogRole(
            dimension_id=parent_row.dimension_id,
            workspace_id=workspace_id,
            parent_role_id=parent_row.id,
            code=code,
            name=code.title(),
            **fields,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, workspace_id=None, identity=None) -> dict:
        data: dict = {}
        if workspace_id is not None:
            data["query"] = {"workspace_id": [str(workspace_id)]}
        if identity is not None:
            data["identity"] = identity
        return await self.rpc.call(LIST, data)

    async def metadata(self, discipline: str, workspace_id=None, identity=None) -> dict:
        data: dict = {"discipline": discipline}
        if workspace_id is not None:
            data["query"] = {"workspace_id": [str(workspace_id)]}
        if identity is not None:
            data["identity"] = identity
        return await self.rpc.call(METADATA, data)

    # --- descriptors ----------------------------------------------------------------------------------------------

    async def test_the_global_list_is_the_installed_disciplines_in_declaration_order_all_enabled(self) -> None:
        reply = await self.list("all")
        self.assertTrue(reply["ok"], reply)
        listed = reply["data"]
        self.assertEqual(list(DISCIPLINES), [row["code"] for row in listed])
        self.assertTrue(all(row["enabled"] for row in listed))
        by_code = {row["code"]: row for row in listed}
        # Deadlock and VALORANT have no open slot and no Full flex player (DisciplineSpec.flex).
        self.assertEqual(
            {"overwatch": True, "lol": True, "deadlock": False, "valorant": False},
            {row["code"]: row["flex"] for row in listed},
        )
        overwatch, lol = by_code["overwatch"], by_code["lol"]
        self.assertEqual({"character": "Hero", "map": "Map", "mode": "Mode"}, overwatch["kinds"])
        self.assertEqual({"character": "Champion", "map": "Map"}, lol["kinds"])  # LoL declares no mode kind
        self.assertEqual(list(DISCIPLINES["lol"].character_classes), lol["character_classes"])
        self.assertEqual(
            (DISCIPLINES["overwatch"].identity_provider, DISCIPLINES["lol"].identity_provider),
            (overwatch["identity_provider"], lol["identity_provider"]),
        )
        self.assertNotEqual(overwatch["identity_provider"], lol["identity_provider"])
        self.assertEqual(
            {
                "catalog_sync": True,
                "native_rank_collection": True,
                "native_ladder": True,
                "match_fetch": False,
                "log_upload": True,
                "achievement_conditions": True,
                "analytics": True,
            },
            overwatch["capabilities"],
        )
        self.assertEqual(
            {
                "catalog_sync": True,
                "native_rank_collection": True,
                "native_ladder": True,
                "match_fetch": False,
                "log_upload": False,
                "achievement_conditions": False,
                "analytics": False,
            },
            lol["capabilities"],
        )
        self.assertEqual(
            {
                "overwatch": ("OW", f"{ORIGIN}/assets/overwatch/icon.svg"),
                "lol": ("LoL", f"{ORIGIN}/assets/lol/icon.svg"),
                "deadlock": ("Deadlock", f"{ORIGIN}/assets/deadlock/icon.png"),
                "valorant": ("VAL", f"{ORIGIN}/assets/valorant/icon.svg"),
            },
            {row["code"]: (row["short_name"], row["icon"]) for row in listed},
        )

    async def test_an_omitted_scope_is_the_global_view(self) -> None:
        self.assertEqual(await self.list("all"), await self.list())

    async def test_enabled_follows_the_requested_workspace(self) -> None:
        workspace = await self.workspace("ow-only")
        reply = await self.list(workspace.id)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(
            {"overwatch": True, "lol": False, "deadlock": False, "valorant": False},
            {row["code"]: row["enabled"] for row in reply["data"]},
        )
        both = await self.workspace("both", enabled=tuple(DISCIPLINES))
        self.assertTrue(all(row["enabled"] for row in (await self.list(both.id))["data"]))

    async def test_a_community_lists_its_own_games_first_in_its_own_order(self) -> None:
        # Spec §2: the community's order is "the first enabled game" and every tie-break; the rest follow installed.
        installed = list(DISCIPLINES)
        reversed_order = await self.workspace("reversed", enabled=tuple(reversed(installed)))
        reply = await self.list(reversed_order.id)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(installed[::-1], [row["code"] for row in reply["data"]])
        last_only = await self.workspace("last-only", enabled=(installed[-1],))
        listed = (await self.list(last_only.id))["data"]
        self.assertEqual([installed[-1], *installed[:-1]], [row["code"] for row in listed])
        self.assertEqual([True] + [False] * (len(installed) - 1), [row["enabled"] for row in listed])
        self.assertEqual(installed, [row["code"] for row in (await self.list("all"))["data"]])

    async def test_a_non_integer_scope_is_422_and_any_unknown_integer_is_the_404(self) -> None:
        for call in (self.list, lambda scope: self.metadata("overwatch", scope)):
            for scope in ("abc", "-3", "1.5", "ALL", " 7"):
                reply = await call(scope)
                self.assertFalse(reply["ok"], scope)
                self.assertEqual("unprocessable", reply["error"]["code"])
                self.assertEqual("invalid_workspace_id", reply["error"]["details"]["fields"][0]["code"])
            # Digit-only values are integers: unknown (including beyond BigInteger) is the 404, never a 422.
            for scope in (
                "2000000000",
                "1000000000",
                "0",
                "00",
                "0000",
                str(2**63 - 1),
                str(2**63),
                "9" * 40,
                "1" + "0" * 5000,
            ):
                reply = await call(scope)
                self.assertEqual("not_found", reply["error"]["code"], scope[:12])
                self.assertEqual("Workspace not found", reply["error"]["message"])
            for scope in ("٣", "1" + "٠" * 20):  # non-ASCII digits are not integers
                reply = await call(scope)
                self.assertEqual("invalid_workspace_id", reply["error"]["details"]["fields"][0]["code"])

    async def test_any_bigint_id_and_its_leading_zero_forms_reach_the_real_visibility_check(self) -> None:
        for index, ws_id in enumerate((999_999_999, 1_000_000_000, 5_000_000_000 + uuid.uuid4().int % 10**6)):
            hidden = models.Workspace(
                id=ws_id,
                slug=f"{self.tag}-big{index}",
                name=f"{self.tag}-big{index}",
                disciplines_enabled=["overwatch"],
                verification_status="verified",
                is_hidden=True,
            )
            self.session.add(hidden)
            await self.session.flush()
            for form in (str(ws_id), f"000{ws_id}"):
                member = await self.metadata("overwatch", form, _viewer(9, ws_id))
                self.assertTrue(member["ok"], (form, member))
                self.assertEqual(ws_id, member["data"]["workspace_id"])
                for identity in (None, _viewer(9, ws_id + 1)):  # a hidden workspace is the same 404 for outsiders
                    for reply in (await self.metadata("overwatch", form, identity), await self.list(form, identity)):
                        self.assertEqual("not_found", reply["error"]["code"], form)
                self.assertTrue((await self.list(form, _viewer(1, superuser=True)))["ok"])

    # --- hidden workspaces ----------------------------------------------------------------------------------------

    async def test_a_hidden_workspace_is_not_found_for_everyone_but_a_member_or_a_superuser(self) -> None:
        hidden = await self.workspace("hidden", hidden=True)
        other = await self.workspace("other")
        await self.child(hidden.id, "damage", f"{self.tag}-secret")
        outsiders = (None, _viewer(9), _viewer(9, other.id))
        for identity in outsiders:
            for reply in (await self.list(hidden.id, identity), await self.metadata("overwatch", hidden.id, identity)):
                self.assertFalse(reply["ok"])
                self.assertEqual("not_found", reply["error"]["code"])
                self.assertEqual("Workspace not found", reply["error"]["message"])
                self.assertNotIn("secret", str(reply))
        for identity in (_viewer(9, hidden.id), _viewer(1, superuser=True)):
            reply = await self.metadata("overwatch", hidden.id, identity)
            self.assertTrue(reply["ok"], reply)
            self.assertIn(f"{self.tag}-secret", {role["code"] for role in reply["data"]["roles"]})
            self.assertTrue((await self.list(hidden.id, identity))["ok"])

    async def test_an_unverified_workspace_stays_publicly_readable(self) -> None:
        unverified = models.Workspace(
            slug=f"{self.tag}-unv", name=f"{self.tag}-unv", disciplines_enabled=["overwatch"], is_hidden=False
        )
        self.session.add(unverified)
        await self.session.flush()
        self.assertTrue((await self.metadata("overwatch", unverified.id))["ok"])

    # --- metadata -------------------------------------------------------------------------------------------------

    async def test_overwatch_describes_its_one_rated_dimension_roles_vocabulary_and_ladder_without_frontend_tables(
        self,
    ) -> None:
        reply = await self.metadata("overwatch", "all")
        self.assertTrue(reply["ok"], reply)
        meta = reply["data"]
        self.assertIsNone(meta["workspace_id"])
        self.assertEqual("overwatch", meta["discipline"]["code"])
        self.assertTrue(meta["discipline"]["enabled"])
        rated = [d for d in meta["dimensions"] if d["active"] and d["rated"]]
        self.assertEqual(["player_role"], [d["code"] for d in rated])
        self.assertEqual("single", rated[0]["selection_mode"])
        module_roles = [r for r in meta["roles"] if r["dimension"] == "player_role"]
        self.assertEqual(["tank", "damage", "support"], [r["code"] for r in module_roles])
        self.assertTrue(all(r["workspace_id"] is None and r["parent_id"] is None for r in module_roles))
        self.assertEqual(
            {
                "tank": {"icon": "/disciplines/overwatch/roles/tank.svg", "color": "#5da8ef"},
                "damage": {"icon": "/disciplines/overwatch/roles/damage.svg", "color": "#ef6298"},
                "support": {"icon": "/disciplines/overwatch/roles/support.svg", "color": "#3fca85"},
            },
            {r["code"]: r["attrs"] for r in module_roles},
        )
        declared = DISCIPLINES["overwatch"].stat_defs
        self.assertEqual(
            [s.code for s in declared], [s["code"] for s in meta["stat_defs"] if s["active"]][: len(declared)]
        )
        by_code = {s["code"]: s for s in meta["stat_defs"]}
        for spec in declared:
            row = by_code[spec.code]
            self.assertEqual(
                (spec.name, spec.value_format, spec.aggregation, spec.group),
                (row["name"], row["value_format"], row["aggregation"], row["group"]),
            )
        self.assertEqual(sorted(s["code"] for s in meta["event_types"]), [s["code"] for s in meta["event_types"]])
        self.assertEqual(["role_queue_5v5"], [p["preset_code"] for p in meta["team_format_presets"]])
        self.assertEqual({"preset"}, {p["source"] for p in meta["team_format_presets"]})
        ladder = DISCIPLINES["overwatch"].native_ladder
        self.assertEqual([t.number for t in ladder], [t["number"] for t in meta["native_ladder"]])
        self.assertEqual([t.slug for t in ladder], [t["slug"] for t in meta["native_ladder"]])

    async def test_lol_describes_its_rated_position_dimension_and_its_ladder(self) -> None:
        meta = (await self.metadata("lol", "all"))["data"]
        rated = [d for d in meta["dimensions"] if d["active"] and d["rated"]]
        self.assertEqual(["position"], [d["code"] for d in rated])
        self.assertEqual(
            ["top", "jungle", "mid", "bot", "support"],
            [r["code"] for r in meta["roles"] if r["dimension"] == "position"],
        )
        self.assertEqual([t.slug for t in DISCIPLINES["lol"].native_ladder], [t["slug"] for t in meta["native_ladder"]])
        declared = DISCIPLINES["lol"].stat_defs
        self.assertEqual(["kills", "dragons"], [s.code for s in declared])
        self.assertEqual([s.code for s in declared], [s["code"] for s in meta["stat_defs"] if s["active"]])
        by_code = {s["code"]: s for s in meta["stat_defs"]}
        for spec in declared:
            row = by_code[spec.code]
            self.assertEqual(
                (spec.name, spec.value_format, spec.aggregation),
                (row["name"], row["value_format"], row["aggregation"]),
            )
        self.assertEqual({"positions_5v5", "open_5v5"}, {p["preset_code"] for p in meta["team_format_presets"]})
        capabilities = meta["discipline"]["capabilities"]
        self.assertEqual((True, False), (capabilities["native_ladder"], capabilities["analytics"]))

    async def test_an_uninstalled_or_malformed_code_is_404_discipline_not_installed_never_overwatch(self) -> None:
        for code in ("chess", "OVERWATCH", "../etc", "overwatch ", "ow", "%00"):
            reply = await self.metadata(code, "all")
            self.assertFalse(reply["ok"], code)
            self.assertEqual("not_found", reply["error"]["code"])
            self.assertEqual("discipline_not_installed", reply["error"]["details"]["fields"][0]["code"])
        self.assertEqual("not_found", (await self.rpc.call(METADATA, {}))["error"]["code"])

    async def test_a_disabled_discipline_is_still_readable_for_history(self) -> None:
        workspace = await self.workspace("ow-only")
        reply = await self.metadata("lol", workspace.id)
        self.assertTrue(reply["ok"], reply)
        self.assertFalse(reply["data"]["discipline"]["enabled"])
        self.assertEqual(workspace.id, reply["data"]["workspace_id"])
        self.assertTrue((await self.metadata("overwatch", workspace.id))["data"]["discipline"]["enabled"])

    async def test_same_named_children_in_two_workspaces_never_leak_and_module_ids_do_not_move(self) -> None:
        mine, theirs = await self.workspace("mine"), await self.workspace("theirs")
        a = await self.child(mine.id, "damage", "main", attrs={"color": "#111111"})
        b = await self.child(theirs.id, "damage", "main", attrs={"icon": None, "color": "#222222"})
        global_ids = {
            r["code"]: r["id"]
            for r in (await self.metadata("overwatch", "all"))["data"]["roles"]
            if r["workspace_id"] is None
        }
        for workspace, own, foreign, expected in (
            (mine, a, b, {"color": "#111111"}),
            (theirs, b, a, {"icon": None, "color": "#222222"}),
        ):
            meta = (await self.metadata("overwatch", workspace.id))["data"]
            self.assertEqual(workspace.id, meta["workspace_id"])
            children = [r for r in meta["roles"] if r["workspace_id"] is not None]
            self.assertEqual([own.id], [r["id"] for r in children])
            self.assertNotIn(foreign.id, {r["id"] for r in meta["roles"]})
            self.assertEqual(expected, children[0]["attrs"])  # explicit null stays present
            self.assertEqual(workspace.id, children[0]["workspace_id"])
            self.assertEqual(global_ids["damage"], children[0]["parent_id"])
            self.assertEqual(global_ids, {r["code"]: r["id"] for r in meta["roles"] if r["workspace_id"] is None})
        glob = (await self.metadata("overwatch", "all"))["data"]
        self.assertFalse([r for r in glob["roles"] if r["workspace_id"] is not None])  # no children in the global view

    async def test_retired_rows_stay_in_the_dictionary_but_selection_flags_say_so(self) -> None:
        workspace = await self.workspace("history")
        retired = await self.child(workspace.id, "support", "old", active=False, selectable=False)
        dimension = models.RoleDimension(
            discipline="overwatch",
            code=f"z{self.tag}",
            name="Legacy",
            selection_mode="single",
            rated=False,
            active=False,
            sort_order=500,
        )
        self.session.add(dimension)
        await self.session.flush()
        self.session.add(models.CatalogRole(dimension_id=dimension.id, code="ancient", name="Ancient", active=False))
        await self.session.flush()
        meta = (await self.metadata("overwatch", workspace.id))["data"]
        old = next(r for r in meta["roles"] if r["id"] == retired.id)
        self.assertEqual((False, False), (old["active"], old["selectable"]))
        self.assertEqual(f"z{self.tag}", meta["dimensions"][-1]["code"])  # (sort_order, code): the retired one is last
        self.assertFalse(meta["dimensions"][-1]["active"])
        self.assertIn(("ancient", f"z{self.tag}"), {(r["code"], r["dimension"]) for r in meta["roles"]})
        self.assertEqual(1, len([d for d in meta["dimensions"] if d["active"] and d["rated"]]))
        orders = [(d["sort_order"], d["code"]) for d in meta["dimensions"]]
        self.assertEqual(sorted(orders), orders)

    async def test_a_stored_object_key_icon_is_served_as_its_public_url_and_null_when_no_origin_is_configured(
        self,
    ) -> None:
        workspace = await self.workspace("icons")
        row = await self.child(workspace.id, "tank", "anchor", attrs={"icon": "assets/overwatch/roles/anchor.svg"})
        meta = (await self.metadata("overwatch", workspace.id))["data"]
        icon = next(r for r in meta["roles"] if r["id"] == row.id)["attrs"]["icon"]
        self.assertEqual(f"{ORIGIN}/assets/overwatch/roles/anchor.svg", icon)
        with patch.object(discipline_service.config.settings, "s3_public_url", None):
            meta = (await self.metadata("overwatch", workspace.id))["data"]
        self.assertTrue(meta["roles"])  # not a 500
        self.assertEqual({"icon": None}, next(r for r in meta["roles"] if r["id"] == row.id)["attrs"])

    async def test_a_read_never_executes_a_module_hook(self) -> None:
        calls: list[str] = []

        def spy(name: str):
            def hook(*_args, **_kwargs):
                calls.append(name)
                raise AssertionError(f"{name} must not run on a metadata read")

            return hook

        installed = DISCIPLINES["overwatch"]
        probed = dataclasses.replace(
            installed,
            catalog_sync=spy("catalog_sync"),
            achievement_conditions=spy("achievement_conditions"),
            achievement_catalog=spy("achievement_catalog"),
            achievement_eligible_keys=spy("achievement_eligible_keys"),
            analytics=spy("analytics"),
            native_ranks=spy("native_ranks"),
            configure_runtime=spy("configure_runtime"),
            register_jobs=spy("register_jobs"),
            start_jobs=spy("start_jobs"),
            collection_handlers={"rank.collect": spy("rank.collect")},
            match_fetchers={"probe": spy("match_fetch")},
            ingestors={"upload": spy("upload")},
        )
        with patch.dict(discipline_service.DISCIPLINES, {"overwatch": probed}):
            listed = await self.list("all")
            meta = await self.metadata("overwatch", "all")
        self.assertTrue(listed["ok"] and meta["ok"], (listed, meta))
        self.assertEqual([], calls)
        self.assertTrue(all(meta["data"]["discipline"]["capabilities"].values()))

    async def test_a_module_that_declares_no_hook_reports_each_capability_absent(self) -> None:
        bare = dataclasses.replace(
            DISCIPLINES["overwatch"],
            catalog_sync=None,
            achievement_conditions=None,
            analytics=None,
            native_ladder=(),
            collection_handlers={"impact.recompute_baselines": lambda *_: None},
            ingestors={"discord": lambda *_: None},  # another source is not a file upload
        )
        with patch.dict(discipline_service.DISCIPLINES, {"overwatch": bare}):
            capabilities = (await self.metadata("overwatch", "all"))["data"]["discipline"]["capabilities"]
        self.assertEqual(
            {
                "catalog_sync": False,
                "native_rank_collection": False,  # another collection handler is not rank collection
                "native_ladder": False,
                "match_fetch": False,
                "log_upload": False,
                "achievement_conditions": False,
                "analytics": False,
            },
            capabilities,
        )
