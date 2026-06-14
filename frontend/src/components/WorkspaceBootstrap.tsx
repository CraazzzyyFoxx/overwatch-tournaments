"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useWorkspaceStore } from "@/stores/workspace.store";

export default function WorkspaceBootstrap() {
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces);
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const queryClient = useQueryClient();
  const router = useRouter();
  const prevWorkspaceId = useRef(currentWorkspaceId);

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  useEffect(() => {
    if (
      prevWorkspaceId.current !== null &&
      currentWorkspaceId !== null &&
      prevWorkspaceId.current !== currentWorkspaceId
    ) {
      // Invalidate client-side React Query cache
      queryClient.invalidateQueries();
      // Re-render server components with new workspace cookie
      router.refresh();
    }
    prevWorkspaceId.current = currentWorkspaceId;
  }, [currentWorkspaceId, queryClient, router]);

  return null;
}
