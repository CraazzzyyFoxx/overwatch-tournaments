"use client";

import { useEntityWorkspace } from "@/hooks/useEntityWorkspace";

export function EntityWorkspace({ workspaceId }: Readonly<{ workspaceId: number | null | undefined }>) {
  useEntityWorkspace(workspaceId);
  return null;
}
