"use client";

import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useUnsavedGuard } from "@/components/kit/useUnsavedGuard";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { portsFromRead } from "@/lib/flow/flowCanvas";
import {
  draftFromRead,
  keyedValidation,
  refreshDraft,
  toChanges,
  isDirty,
  type FlowDraft
} from "@/lib/flow/flowDraft";
import { notify } from "@/lib/notify";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import flowService from "@/services/flow.service";
import type { FlowChanges } from "@/types/flow.types";

/** How long the draft must rest before the dry run asks the server about it. */
export const VALIDATE_DEBOUNCE_MS = 400;

const noop = () => undefined;

/** The Flow tab's state: the admin read, the local draft, the debounced dry run, and Save. */
export function useFlowEditor(tournamentId: number) {
  const queryClient = useQueryClient();
  const flowKey = adminQueryKeys.tournamentFlow(tournamentId);
  const readQuery = useQuery({ queryKey: flowKey, queryFn: () => flowService.getAdmin(tournamentId) });
  const read = readQuery.data;

  const [draft, setDraft] = useState<FlowDraft | null>(null);
  const [prevRead, setPrevRead] = useState(read);
  if (read && read !== prevRead) {
    setPrevRead(read);
    setDraft(refreshDraft(draft, read));
  }

  const changes = useMemo(() => (draft ? toChanges(draft) : null), [draft]);
  const dirty = draft ? isDirty(draft) : false;

  const [debounced, setDebounced] = useState(changes);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(changes), VALIDATE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [changes]);

  const dryRun = useQuery({
    queryKey: [...flowKey, "validate", debounced],
    queryFn: () => flowService.validate(tournamentId, debounced as FlowChanges),
    enabled: dirty && debounced !== null,
    placeholderData: keepPreviousData
  });

  const keyed = useMemo(() => {
    if (!draft || !read) return null;
    return dirty && dryRun.data
      ? keyedValidation(draft, dryRun.data.issues, dryRun.data.ports, dryRun.data.ref_ids, dryRun.data.new_edge_ids)
      : keyedValidation(draft, dirty ? [] : read.issues, portsFromRead(read));
  }, [draft, read, dirty, dryRun.data]);

  const save = useMutation({
    mutationFn: () => flowService.applyChanges(tournamentId, changes as FlowChanges),
    onSuccess: (saved) => {
      setDraft(draftFromRead(saved));
      void queryClient.invalidateQueries({ queryKey: flowKey });
      void invalidateTournamentWorkspace(queryClient, tournamentId);
    },
    onError: (error) => notify.apiError(error)
  });

  useUnsavedGuard({ dirty, guardNavigation: false, onNavigationBlocked: noop });

  return {
    read,
    isLoading: readQuery.isLoading,
    isError: readQuery.isError,
    refetch: readQuery.refetch,
    draft,
    dirty,
    changes,
    keyed,
    apply: (op: (d: FlowDraft) => FlowDraft) => setDraft((d) => (d ? op(d) : d)),
    save: () => save.mutate(),
    saving: save.isPending,
    discard: () => read && setDraft(draftFromRead(read))
  };
}
