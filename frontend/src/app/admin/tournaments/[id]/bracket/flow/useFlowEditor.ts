"use client";

import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { useFlowErrorMessage } from "@/hooks/useFlowErrorNotifier";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { getApiErrorMessage } from "@/lib/api/error";
import { arrangeIfOverlapping } from "@/lib/flow/autoLayout";
import { portsFromRead } from "@/lib/flow/flowCanvas";
import {
  draftFromRead,
  keyedValidation,
  refreshDraft,
  sameChanges,
  toChanges,
  isDirty,
  type FlowDraft
} from "@/lib/flow/flowDraft";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import flowService from "@/services/flow.service";
import type { FlowChanges, FlowRead } from "@/types/flow.types";

/** How long the draft must rest before the dry run asks the server about it. */
export const VALIDATE_DEBOUNCE_MS = 400;

/** Whether the admin changed `draft` since it opened: the opening arrangement alone is no edit, though Save sends it along. */
const editedSince = (draft: FlowDraft | null, opened: FlowDraft | null): draft is FlowDraft =>
  draft !== null && isDirty(draft) && !(opened !== null && sameChanges(draft, opened));

/** The Flow tab's state: the admin read, the local draft, the debounced dry run, and Save. */
export function useFlowEditor(tournamentId: number) {
  const t = useTranslations("adminTournament.flow");
  const queryClient = useQueryClient();
  const flowErrorMessage = useFlowErrorMessage();
  const flowKey = adminQueryKeys.tournamentFlow(tournamentId);
  const readQuery = useQuery({ queryKey: flowKey, queryFn: () => flowService.getAdmin(tournamentId) });
  const read = readQuery.data;

  const [draft, setDraft] = useState<FlowDraft | null>(null);
  const [opened, setOpened] = useState<FlowDraft | null>(null);
  // Undefined at first, so a read already cached on mount opens the draft too.
  const [prevRead, setPrevRead] = useState<FlowRead | undefined>(undefined);
  if (read && read !== prevRead) {
    setPrevRead(read);
    // Overlapping cards (migrated tournaments) open already arranged.
    const fresh = arrangeIfOverlapping(draftFromRead(read));
    const kept = editedSince(draft, opened) ? refreshDraft(draft, read) : null;
    setDraft(kept && isDirty(kept) ? kept : fresh);
    setOpened(fresh);
  }

  const changes = useMemo(() => (draft ? toChanges(draft) : null), [draft]);
  const dirty = editedSince(draft, opened);

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
      const next = draftFromRead(saved);
      setDraft(next);
      setOpened(next);
      void queryClient.invalidateQueries({ queryKey: flowKey });
      void invalidateTournamentWorkspace(queryClient, tournamentId);
    }
  });
  const error = save.error ? (flowErrorMessage(save.error) ?? getApiErrorMessage(save.error, t("saveFailed"))) : null;

  return {
    read,
    isLoading: readQuery.isLoading,
    isError: readQuery.isError,
    refetch: readQuery.refetch,
    draft,
    /** The draft as it opened, the arrangement of overlapping cards included. */
    opened,
    dirty,
    changes,
    keyed,
    apply: (op: (d: FlowDraft) => FlowDraft) => {
      if (save.isError) save.reset();
      setDraft((d) => (d ? op(d) : d));
    },
    save: () => save.mutate(),
    saving: save.isPending,
    /** Why the last Save failed, for the save bar; cleared by the next edit. */
    error,
    discard: () => {
      save.reset();
      setDraft(opened);
    }
  };
}
