"use client";

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { shouldRefreshWorkspaceScope } from "./WorkspaceBootstrap.helpers";
import { resolveHost } from "@/lib/host";
import {
  LEGACY_WORKSPACE_COOKIE,
  useWorkspaceStore,
  WORKSPACE_COOKIE
} from "@/stores/workspace.store";

export default function WorkspaceBootstrap() {
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces);
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const queryClient = useQueryClient();
  const router = useRouter();
  // The correction applies to the initial SSR, not to later client navigations.
  const initialPathname = useRef(usePathname());
  const prevWorkspaceId = useRef(currentWorkspaceId);
  // Whether the server render that produced the current HTML carried a workspace
  // cookie. When it didn't (fresh session — the cookie is absent), server
  // components rendered unscoped (cross-workspace) data, so once we resolve the
  // active workspace on the client we must refresh them exactly once.
  const ssrHadWorkspaceCookie = useRef(
    typeof document !== "undefined" &&
      (document.cookie.includes(`${WORKSPACE_COOKIE}=`) ||
        document.cookie.includes(`${LEGACY_WORKSPACE_COOKIE}=`))
  );
  const correctedInitialSsr = useRef(false);

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  useEffect(() => {
    // On a tenant (white-label) host the SSR is already scoped by the
    // `x-owt-workspace-id` header (host beats cookie), the workspace is fixed,
    // and no workspace cookie is written — so the cookie-absence "correction"
    // below would fire a needless router.refresh()+invalidateQueries() on every
    // load. Skip it entirely there.
    const isTenantHost = resolveHost(window.location.hostname).mode === "tenant";

    const workspaceChanged =
      prevWorkspaceId.current !== null &&
      currentWorkspaceId !== null &&
      prevWorkspaceId.current !== currentWorkspaceId;

    // First-load correction: the initial SSR had no workspace cookie, so its
    // server components rendered unscoped. Now that a workspace is resolved (and
    // fetchWorkspaces has set the cookie), re-render them once so they scope.
    const needsInitialCorrection =
      !ssrHadWorkspaceCookie.current && !correctedInitialSsr.current && currentWorkspaceId !== null;

    const shouldRefresh = shouldRefreshWorkspaceScope({
      isTenantHost,
      pathname: initialPathname.current,
      workspaceChanged,
      needsInitialCorrection
    });

    if (shouldRefresh) {
      correctedInitialSsr.current = true;
      // Invalidate client-side React Query cache
      queryClient.invalidateQueries();
      // Re-render server components with the resolved workspace cookie
      router.refresh();
    }
    prevWorkspaceId.current = currentWorkspaceId;
  }, [currentWorkspaceId, queryClient, router]);

  return null;
}
