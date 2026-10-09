"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { resolveHost } from "@/lib/site/host";
import { useWorkspaceStore } from "@/stores/workspace.store";

export default function WorkspaceBootstrap() {
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces);
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const statsScope = useWorkspaceStore((s) => s.statsScope);
  const queryClient = useQueryClient();
  const router = useRouter();
  const previous = useRef({ currentWorkspaceId, statsScope });

  useEffect(() => {
    void fetchWorkspaces();
  }, [fetchWorkspaces]);

  useEffect(() => {
    const before = previous.current;
    previous.current = { currentWorkspaceId, statsScope };
    if (resolveHost(window.location.hostname).mode === "tenant") return;
    const changed = before.statsScope !== statsScope ||
      (statsScope === "workspace" && before.currentWorkspaceId !== currentWorkspaceId);
    if (!changed) return;

    const url = new URL(window.location.href);
    const fixedEntity = useWorkspaceStore.getState().entityWorkspaceId != null ||
      url.pathname.startsWith("/workspace/");
    queryClient.setQueriesData<InfiniteData<unknown>>({
      predicate: (query) => {
        const data = query.state.data as InfiniteData<unknown> | undefined;
        return Array.isArray(data?.pages) && Array.isArray(data?.pageParams) &&
          (!fixedEntity || query.getObserversCount() === 0);
      }
    }, (data) => data && data.pages.length > 1
      ? { ...data, pages: data.pages.slice(0, 1), pageParams: data.pageParams.slice(0, 1) }
      : data);
    void queryClient.invalidateQueries();
    if (!fixedEntity && url.searchParams.has("page")) {
      url.searchParams.delete("page");
      router.replace(`${url.pathname}${url.search}${url.hash}`, { scroll: false });
    }
    router.refresh();
  }, [currentWorkspaceId, statsScope, queryClient, router]);

  return null;
}
