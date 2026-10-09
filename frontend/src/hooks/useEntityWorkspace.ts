"use client";

import { useLayoutEffect } from "react";
import { useWorkspaceStore } from "@/stores/workspace.store";

/** An opened object's owner is runtime context, not a saved viewing filter. */
export function useEntityWorkspace(workspaceId: number | null | undefined): void {
  useLayoutEffect(() => {
    if (workspaceId == null) return;
    useWorkspaceStore.getState().setEntityWorkspace(workspaceId);
    return () => {
      const state = useWorkspaceStore.getState();
      if (state.entityWorkspaceId === workspaceId) state.setEntityWorkspace(null);
    };
  }, [workspaceId]);
}
