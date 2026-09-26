"use client";

import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { Workspace } from "@/types/workspace.types";
import {
  useScopedSettingsForm,
  type ScopedSettingsForm
} from "@/components/admin/settings/useScopedSettingsForm";
import {
  formFromWorkspace,
  sectionPayload,
  type WorkspaceSettingsFormState
} from "./fields";
import type { WorkspaceRecordSectionKey } from "./sections";
import { adminQueryKeys } from "@/lib/admin/query-keys";

/**
 * Everything a settings section needs to render and save its own fields:
 * the shared scoped-form contract plus the workspace read this hook owns.
 */
export interface WorkspaceSettingsForm
  extends ScopedSettingsForm<WorkspaceSettingsFormState, Partial<WorkspaceSettingsFormState>> {
  workspace: Workspace | undefined;
  isLoading: boolean;
  isError: boolean;
  /** Re-read `admin-workspaces`, `admin-workspace` and the picker store. */
  invalidate: () => void;
}

/**
 * Form state of one workspace settings section, and the scoped diff it saves.
 *
 * Every section shares this hook, so "what changed" is computed once from
 * `FIELD_DEFS` and each page only decides which controls to render.
 */
export function useWorkspaceSettingsForm(
  workspaceId: number | null,
  section: WorkspaceRecordSectionKey
): WorkspaceSettingsForm {
  const queryClient = useQueryClient();
  const fetchWorkspaces = useWorkspaceStore((state) => state.fetchWorkspaces);

  // The `["admin-workspace", id]` key is a cross-module contract, not a local
  // convention: `components/admin/breadcrumb-registry.ts` reads this exact
  // cache entry to name the workspace crumb.
  const query = useQuery({
    queryKey: adminQueryKeys.workspace(workspaceId ?? 0),
    queryFn: () => workspaceService.getById(workspaceId as number),
    enabled: workspaceId !== null && Number.isFinite(workspaceId)
  });
  const workspace = query.data;

  const baseline = useMemo(
    () => (workspace ? formFromWorkspace(workspace) : null),
    [workspace]
  );

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: adminQueryKeys.workspaces() });
    if (workspaceId !== null) {
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.workspace(workspaceId) });
    }
    void fetchWorkspaces();
  }, [queryClient, workspaceId, fetchWorkspaces]);

  const settings = useScopedSettingsForm({
    baseline,
    toPayload: (form, base) => sectionPayload(section, form, base),
    submit: (payload) => workspaceService.update(workspaceId as number, payload),
    onSaved: invalidate
  });

  return {
    ...settings,
    workspace,
    isLoading: query.isLoading,
    isError: query.isError,
    invalidate
  };
}
