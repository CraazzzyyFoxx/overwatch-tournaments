"""``assert_tournament_viewable`` — a scrim container reads wider than it lists.

The break this fixes: a scrim room is shared by link, and the opponent following
it was a plain workspace member — neither a workspace admin nor preview-
allowlisted — so every read of the room 404'd. The allowlist could not solve it,
because the row that would have added them is written by the CLAIM, and the claim
button lives on a page that could not load. The share link was dead for everyone
but admins.

Narrowness is the whole risk here, so it is what most of these tests pin: a
hidden PREVIEW tournament is an unpublished real one, and admitting every
workspace member to it is exactly what preview mode exists to prevent.

Run against a real (SQLite) database rather than a faked session: the widening is
conditional on ``is_scrim_container``, which is a query, and a fake would only
prove that this module can call a stub.
"""

from __future__ import annotations

import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))


from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament.preview_access import TournamentPreviewAccess  # noqa: E402
from shared.models.tournament.scrim import ScrimRoom  # noqa: E402
from shared.models.tournament.tournament import Tournament  # noqa: E402
from shared.services.tournament.visibility import (  # noqa: E402
    assert_tournament_viewable,
    visible_tournament_ids_subquery,
)
from shared.testing import install_postgres_type_shims  # noqa: E402

install_postgres_type_shims()


# Select-in relationships query these tables even when their collections are empty.
TABLE_NAMES = (
    "tournament.tournament",
    "tournament.tournament_phase_schedule",
    "tournament.tournament_preview_access",
    "tournament.scrim_room",
    "workspace",
    "workspace_division_grid_default",
)
WORKSPACE_ID = 1
OTHER_WORKSPACE_ID = 2
CONTAINER_ID = 10
PREVIEW_ID = 11
PUBLIC_ID = 12

MEMBER = 100
OUTSIDER = 200
ALLOWLISTED = 300


class _AsyncSessionShim:
    def __init__(self, session: Session) -> None:
        self.sync_session = session

    async def execute(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.sync_session.execute(statement, *args, **kwargs)

    async def scalar(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.sync_session.scalar(statement, *args, **kwargs)

    def __getattr__(self, name):  # noqa: ANN001, ANN204
        return getattr(self.sync_session, name)


def _user(auth_id: int, *, workspaces: list[int] | None = None, ws_admin: list[int] | None = None) -> AuthUser:
    """An ``AuthUser`` carrying only its RBAC cache, the way a rehydrated gateway
    identity does. Same construction as ``test_tournament_visibility.py``."""
    user = AuthUser()
    user.id = auth_id
    user.is_superuser = False
    user.is_active = True
    ws_admin = ws_admin or []
    member_of = workspaces if workspaces is not None else [WORKSPACE_ID]
    user.set_rbac_cache(
        role_names=[],
        permissions=[],
        workspaces=[{"workspace_id": ws} for ws in member_of],
        workspace_rbac={ws: {"roles": [], "permissions": [{"resource": "*", "action": "*"}]} for ws in ws_admin},
    )
    return user


class ScrimContainerVisibilityTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        metadata = Tournament.__table__.metadata
        tables = [metadata.tables[name] for name in TABLE_NAMES]
        self.engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in tables if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            for table in tables:
                table.create(conn)
        self.session = Session(self.engine)
        self.shim = _AsyncSessionShim(self.session)
        self.addCleanup(self._close)

        self.session.execute(sa.insert(Workspace.__table__).values(id=WORKSPACE_ID, slug="ws", name="WS"))
        for tournament_id, name, hidden in (
            (CONTAINER_ID, "Scrims", True),
            (PREVIEW_ID, "Season 9", True),
            (PUBLIC_ID, "Season 8", False),
        ):
            self.session.execute(
                sa.insert(Tournament.__table__).values(
                    id=tournament_id,
                    workspace_id=WORKSPACE_ID,
                    name=name,
                    slug=f"tournament-{tournament_id}",
                    is_hidden=hidden,
                    is_league=False,
                    start_date=datetime(2026, 8, 12, tzinfo=UTC),
                    end_date=datetime(2026, 8, 12, tzinfo=UTC),
                )
            )
        # What makes CONTAINER_ID a container: it holds a room.
        self.session.execute(
            sa.insert(ScrimRoom.__table__).values(
                id=1,
                token="tok",
                label="A vs B",
                workspace_id=WORKSPACE_ID,
                tournament_id=CONTAINER_ID,
                stage_id=1,
                encounter_id=1,
                created_by_auth_user_id=MEMBER,
            )
        )
        self.session.execute(
            sa.insert(TournamentPreviewAccess.__table__).values(
                id=1, tournament_id=PREVIEW_ID, auth_user_id=ALLOWLISTED
            )
        )
        self.session.commit()

    def _close(self) -> None:
        self.session.close()
        self.engine.dispose()

    async def assert_denied(self, user, tournament_id: int) -> None:  # noqa: ANN001
        with self.assertRaises(HTTPException) as ctx:
            await assert_tournament_viewable(self.shim, user, tournament_id)
        self.assertEqual(404, ctx.exception.status_code)

    # ── the fix ──────────────────────────────────────────────────────────────

    async def test_a_workspace_member_may_read_the_scrim_container(self) -> None:
        """The opponent following a share link. Neither admin nor allowlisted."""
        tournament = await assert_tournament_viewable(self.shim, _user(MEMBER), CONTAINER_ID)
        self.assertEqual(CONTAINER_ID, tournament.id)

    async def test_a_member_needs_no_allowlist_row(self) -> None:
        rows = self.session.scalars(
            sa.select(TournamentPreviewAccess.auth_user_id).where(TournamentPreviewAccess.tournament_id == CONTAINER_ID)
        ).all()
        self.assertEqual([], list(rows), "the container grants nothing; membership is the rule")

    # ── narrowness: everything the widening must NOT admit ───────────────────

    async def test_a_hidden_preview_tournament_still_refuses_a_plain_member(self) -> None:
        """The regression this widening could cause: preview mode exists to keep
        an unpublished tournament from the workspace at large."""
        await self.assert_denied(_user(MEMBER), PREVIEW_ID)

    async def test_a_hidden_preview_tournament_still_admits_its_allowlist(self) -> None:
        tournament = await assert_tournament_viewable(self.shim, _user(ALLOWLISTED), PREVIEW_ID)
        self.assertEqual(PREVIEW_ID, tournament.id)

    async def test_a_hidden_preview_tournament_still_admits_a_workspace_admin(self) -> None:
        tournament = await assert_tournament_viewable(self.shim, _user(MEMBER, ws_admin=[WORKSPACE_ID]), PREVIEW_ID)
        self.assertEqual(PREVIEW_ID, tournament.id)

    async def test_a_member_of_another_workspace_is_refused_the_container(self) -> None:
        await self.assert_denied(_user(OUTSIDER, workspaces=[OTHER_WORKSPACE_ID]), CONTAINER_ID)

    async def test_an_anonymous_viewer_is_refused_the_container(self) -> None:
        await self.assert_denied(None, CONTAINER_ID)

    async def test_a_missing_tournament_is_still_404(self) -> None:
        await self.assert_denied(_user(MEMBER), 9999)

    # ── listing is unchanged: reading got wider, listing did not ─────────────

    async def test_the_container_stays_out_of_a_plain_viewers_listings(self) -> None:
        """The widening is on the direct-read gate only. A member can open a room
        by link but must never find the container in a list — that exclusion is
        what keeps scrims out of the public surface."""
        for viewer in (None, _user(MEMBER)):
            visible = set(self.session.scalars(visible_tournament_ids_subquery(viewer)).all())
            self.assertIn(PUBLIC_ID, visible)
            self.assertNotIn(CONTAINER_ID, visible)
            self.assertNotIn(PREVIEW_ID, visible)

    async def test_a_workspace_admin_still_sees_hidden_rows_in_listings(self) -> None:
        """Pre-existing and deliberate: hidden tournaments are listed to the
        admins of their workspace, which is the only way an admin learns the
        container exists at all. Pinned so the widening above is not mistaken for
        having changed it."""
        visible = set(
            self.session.scalars(visible_tournament_ids_subquery(_user(MEMBER, ws_admin=[WORKSPACE_ID]))).all()
        )
        self.assertEqual({PUBLIC_ID, PREVIEW_ID, CONTAINER_ID}, visible)
