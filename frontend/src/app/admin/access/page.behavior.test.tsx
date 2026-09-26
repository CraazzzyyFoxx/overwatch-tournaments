// @vitest-environment happy-dom
//
// Access › hub landing — the redirect that replaced a fixed `/admin/access/accounts`
// entry. What is pinned here:
//   1. a workspace admin lands on Roles: Accounts/Permissions/OAuth are
//      global-RBAC reads and Sessions is superuser-only, so the old fixed href
//      handed every workspace admin the Unauthorized wall on the one Access
//      entry the sidebar showed them;
//   2. a global panel role still lands on Accounts, the first section it holds;
//   3. an outsider is not forwarded anywhere — the layout's empty state stands.
//
// The real `usePermissions` runs against real profiles: mocking the predicate
// would pin the mock, and the whole defect was the gate disagreeing with the
// destination.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The real store hydrates its workspace from a cookie, which no test sets.
// Only `currentWorkspaceId` matters here, so it is pinned outright.
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector?: (state: { currentWorkspaceId: number | null }) => unknown) => {
    const state = { currentWorkspaceId: 7 };
    return selector ? selector(state) : state;
  }
}));

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: replace })
}));

import { type AppPermission } from "@/hooks/usePermissions";
import { type AuthProfile, useAuthProfileStore } from "@/stores/auth-profile.store";
import AccessAdminIndex from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

const WORKSPACE = 7;

function profile(overrides: Partial<AuthProfile>): AuthProfile {
  return {
    id: 1,
    username: "probe",
    roles: [],
    permissions: [],
    denies: [],
    isSuperuser: false,
    workspaces: [],
    linkedPlayers: [],
    ...overrides
  };
}

async function landing(user: AuthProfile): Promise<string | undefined> {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  useAuthProfileStore.setState({ status: "authenticated", user });

  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(<AccessAdminIndex />);
  });
  await act(async () => {
    root.unmount();
  });
  container.remove();

  return replace.mock.calls[0]?.[0] as string | undefined;
}

beforeEach(() => {
  replace.mockClear();
  document.body.innerHTML = "";
});

describe("Access › hub landing", () => {
  it("sends a workspace admin to Roles, not to global-only Accounts", async () => {
    const target = await landing(
      profile({
        username: "owner",
        workspaces: [
          { workspace_id: WORKSPACE, slug: "ws", roles: ["owner"], permissions: ["admin.*"] }
        ]
      })
    );

    expect(target).toBe("/admin/access/roles");
  });

  it("sends a global panel role to Accounts", async () => {
    const target = await landing(
      profile({
        username: "mod",
        roles: ["moderator"],
        permissions: ["auth_user.read"] as AppPermission[]
      })
    );

    expect(target).toBe("/admin/access/accounts");
  });

  it("forwards a superuser to the first section", async () => {
    const target = await landing(profile({ username: "root", isSuperuser: true }));

    expect(target).toBe("/admin/access/accounts");
  });

  it("ignores read-only memberships beside the one workspace it owns", async () => {
    // The reported shape: `owner` of one workspace, plain `host`/`member` of two
    // others, and a handful of global reads that cover none of the Access
    // sections. `host` looks non-read only because of `custom_game`, which is
    // deliberately not an admin-panel resource.
    const target = await landing(
      profile({
        username: "shadow_pulse_dl",
        roles: ["user"],
        permissions: ["user.read", "tournament.read", "team.read", "match.read"] as AppPermission[],
        workspaces: [
          {
            workspace_id: 6,
            slug: "txao",
            roles: ["host"],
            permissions: ["tournament.read", "custom_game.create", "custom_game.delete"]
          },
          { workspace_id: 8, slug: "moonrise", roles: ["owner"], permissions: ["admin.*"] },
          { workspace_id: 2, slug: "anakq-dvor", roles: ["member"], permissions: ["tournament.read"] }
        ]
      })
    );

    expect(target).toBe("/admin/access/roles");
  });

  it("forwards nobody when no section is open", async () => {
    const target = await landing(profile({ username: "outsider" }));

    expect(target).toBeUndefined();
  });
});
