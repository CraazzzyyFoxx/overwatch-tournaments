import { describe, expect, it } from "vitest";

import { shouldRefreshWorkspaceScope } from "./WorkspaceBootstrap.helpers";

describe("shouldRefreshWorkspaceScope", () => {
  const initialCorrection = {
    isTenantHost: false,
    workspaceChanged: false,
    needsInitialCorrection: true
  };

  it.each([
    "/tournaments/72",
    "/tournaments/72/",
    "/tournaments/72/bracket",
    "/tournaments/72/teams",
    "/tournaments/72/participants",
    "/tournaments/72/matches",
    "/tournaments/72/heroes",
    "/tournaments/72/standings",
    "/tournaments/72/draft",
    "/draft/78",
    "/draft/78/"
  ])("skips the first-load correction on workspace-independent public path %s", (pathname) => {
    expect(shouldRefreshWorkspaceScope({ ...initialCorrection, pathname })).toBe(false);
  });

  it.each([
    "/tournaments",
    "/tournaments/",
    "/tournaments/analytics",
    "/tournaments/0",
    "/tournaments/072",
    "/tournaments/72abc",
    "/tournaments/9007199254740992",
    "/draft",
    "/draft/",
    "/draft/0",
    "/draft/078",
    "/draft/78/extra",
    "/draft/78abc",
    "/draft/9007199254740992",
    "/admin/tournaments/72",
    "/players"
  ])("keeps the first-load correction on non-detail path %s", (pathname) => {
    expect(shouldRefreshWorkspaceScope({ ...initialCorrection, pathname })).toBe(true);
  });

  it("still refreshes a public tournament detail after a real workspace change", () => {
    expect(
      shouldRefreshWorkspaceScope({
        isTenantHost: false,
        pathname: "/tournaments/72/teams",
        workspaceChanged: true,
        needsInitialCorrection: false
      })
    ).toBe(true);
  });

  it("never refreshes the workspace scope on a tenant host", () => {
    expect(
      shouldRefreshWorkspaceScope({
        isTenantHost: true,
        pathname: "/players",
        workspaceChanged: true,
        needsInitialCorrection: true
      })
    ).toBe(false);
  });
});
