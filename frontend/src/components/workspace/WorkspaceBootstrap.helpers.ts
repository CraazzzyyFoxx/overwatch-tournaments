type WorkspaceScopeRefreshInput = {
  isTenantHost: boolean;
  pathname: string;
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

export function shouldRefreshWorkspaceScope({
  isTenantHost,
  pathname,
  workspaceChanged,
  needsInitialCorrection
}: WorkspaceScopeRefreshInput): boolean {
  if (isTenantHost) return false;
  if (workspaceChanged) return true;

  // These pages render server-side without the selected workspace: by tournament ref, or not at all.
  return (
    needsInitialCorrection &&
    !PUBLIC_TOURNAMENT_DETAIL_PATH.test(pathname) &&
    !PUBLIC_STANDALONE_DRAFT_PATH.test(pathname) &&
    !PUBLIC_USERS_INDEX_PATH.test(pathname)
  );
}
