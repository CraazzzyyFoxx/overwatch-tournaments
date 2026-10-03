type WorkspaceScopeRefreshInput = {
  isTenantHost: boolean;
  /** The route on screen now — what `router.refresh()` would re-render. */
  pathname: string;
  /** The route the SSR being corrected was rendered for. */
  initialPathname: string;
  workspaceChanged: boolean;
  needsInitialCorrection: boolean;
};

// `/tournaments/<ref>` and `/draft/<ref>`, where `<ref>` is whatever the page
// resolves by (slug, legacy numeric id or retired slug). `analytics` is the one
// static route beside `[slug]`, and it is workspace-scoped.
const PUBLIC_TOURNAMENT_DETAIL_PATH = /^\/tournaments\/(?!analytics(?:\/|$))[^/]+(?:\/|$)/;
const PUBLIC_STANDALONE_DRAFT_PATH = /^\/draft\/[^/]+\/?$/;
// The `/users` index renders a single client component: its server tree fetches
// nothing and reads no workspace cookie, so the correction would only pay for a
// full RSC refetch of identical HTML. The client queries there already re-key on
// `currentWorkspaceId`, so they rescope on their own. `/users/<slug>` is *not*
// exempt — that page renders server-side through the workspace-scoped api-fetch.
const PUBLIC_USERS_INDEX_PATH = /^\/users\/?$/;

// Whether this route's server render ignores the selected workspace.
function rendersWithoutWorkspace(pathname: string): boolean {
  return (
    PUBLIC_TOURNAMENT_DETAIL_PATH.test(pathname) ||
    PUBLIC_STANDALONE_DRAFT_PATH.test(pathname) ||
    PUBLIC_USERS_INDEX_PATH.test(pathname)
  );
}

export function shouldRefreshWorkspaceScope({
  isTenantHost,
  pathname,
  initialPathname,
  workspaceChanged,
  needsInitialCorrection
}: WorkspaceScopeRefreshInput): boolean {
  if (isTenantHost) return false;
  // A tournament page switches the active workspace to its owner on open
  // (`useSyncActiveWorkspace`); re-rendering a route that renders by ref would
  // be a full SSR per visitor for identical output. The client cache is still
  // invalidated by the caller.
  if (workspaceChanged && !rendersWithoutWorkspace(pathname)) return true;
  return needsInitialCorrection && !rendersWithoutWorkspace(initialPathname);
}
