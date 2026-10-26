"""``RoleAdminService.list`` must self-heal a workspace's system-role catalog
(real-DB integration; mirrors the DB-skip pattern in
``test_token_workspace_membership.py``).

System roles (owner/admin/host/member/player) are created lazily by
add_member/grant/registration -- never on workspace creation alone. A
workspace that has not exercised one of those paths since a new system role
landed in the catalog would otherwise show a stale role list: the admin
"Roles" page and the members page's role picker would be missing an entry
(e.g. "Host") even though the catalog now defines it.
"""

import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


from shared import models
from shared.rbac import WORKSPACE_SYSTEM_ROLE_NAMES  # noqa: E402
from src import schemas  # noqa: E402
from src.services.rbac import RoleAdminService  # noqa: E402


def test_listing_workspace_roles_creates_missing_system_roles(db_session) -> None:
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        workspace = models.Workspace(slug=f"role-list-test-{suffix}", name=f"Role List Test {suffix}")
        db_session.add(workspace)
        await db_session.commit()

        superuser = SimpleNamespace(is_superuser=True)
        params = schemas.RoleListParams(page=1, per_page=-1, workspace_id=workspace.id)
        result = await RoleAdminService().list(db_session, superuser, params)
        # Release the read transaction before asyncio.run closes its owning loop.
        await db_session.close()
        return result

    result = asyncio.run(_run())

    names = {role.name for role in result["results"]}
    assert set(WORKSPACE_SYSTEM_ROLE_NAMES) <= names
    assert "host" in names
