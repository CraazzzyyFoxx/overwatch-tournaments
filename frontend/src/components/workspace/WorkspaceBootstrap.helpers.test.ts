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
    "/tournaments/turnir-thao-4-fleks-turnir",
    "/tournaments/anak-cup/bracket",
    "/tournaments/analytics-cup",
    "/draft/78",
    "/draft/78/",
    "/draft/anak-cup",
    "/users",
    "/users/"
  ])("skips the first-load correction on workspace-independent public path %s", (pathname) => {
    expect(
      shouldRefreshWorkspaceScope({ ...initialCorrection, pathname, initialPathname: pathname })
    ).toBe(false);
  });

  it.each([
    "/tournaments",
    "/tournaments/",
    "/tournaments/analytics",
    "/tournaments/analytics/",
    "/draft",
    "/draft/",
    "/draft/78/extra",
    "/admin/tournaments/72",
    "/players",
    "/users/andremorua"
  ])("keeps the first-load correction on non-detail path %s", (pathname) => {
    expect(
      shouldRefreshWorkspaceScope({ ...initialCorrection, pathname, initialPathname: pathname })
    ).toBe(true);
  });

  const workspaceChange = {
    isTenantHost: false,
    initialPathname: "/players",
    workspaceChanged: true,
    needsInitialCorrection: false
  };

  it.each(["/tournaments/72/teams", "/tournaments/anak-cup", "/draft/78"])(
    "does not re-render ref-addressed path %s when the workspace follows the tournament",
    (pathname) => {
      expect(shouldRefreshWorkspaceScope({ ...workspaceChange, pathname })).toBe(false);
    }
  );

  it("re-renders a workspace-scoped page after a workspace change", () => {
    expect(
      shouldRefreshWorkspaceScope({ ...workspaceChange, pathname: "/tournaments/analytics" })
    ).toBe(true);
  });

  it("judges the correction by the SSR's route, not the one navigated to since", () => {
    expect(
      shouldRefreshWorkspaceScope({
        ...initialCorrection,
        pathname: "/players",
        initialPathname: "/tournaments/72"
      })
    ).toBe(false);
  });

  it("never refreshes the workspace scope on a tenant host", () => {
    expect(
      shouldRefreshWorkspaceScope({
        isTenantHost: true,
        pathname: "/players",
        initialPathname: "/players",
        workspaceChanged: true,
        needsInitialCorrection: true
      })
    ).toBe(false);
  });
});
