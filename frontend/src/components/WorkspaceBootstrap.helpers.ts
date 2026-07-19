type WorkspaceScopeRefreshInput = {
  isTenantHost: boolean;
  pathname: string;
  workspaceChanged: boolean;
  needsInitialCorrection: boolean;
};

const PUBLIC_TOURNAMENT_DETAIL_PATH = /^\/tournaments\/([1-9]\d*)(?:\/|$)/;
const PUBLIC_STANDALONE_DRAFT_PATH = /^\/draft\/([1-9]\d*)\/?$/;

function isWorkspaceIndependentPublicPath(pathname: string): boolean {
  const match =
    PUBLIC_TOURNAMENT_DETAIL_PATH.exec(pathname) ?? PUBLIC_STANDALONE_DRAFT_PATH.exec(pathname);
  if (!match) return false;

  return Number.isSafeInteger(Number(match[1]));
}

export function shouldRefreshWorkspaceScope({
  isTenantHost,
  pathname,
  workspaceChanged,
  needsInitialCorrection
}: WorkspaceScopeRefreshInput): boolean {
  if (isTenantHost) return false;
  if (workspaceChanged) return true;

  // These pages load public data by tournament id, independently of the selected workspace.
  return needsInitialCorrection && !isWorkspaceIndependentPublicPath(pathname);
}
