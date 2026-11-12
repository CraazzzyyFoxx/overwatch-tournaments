import { useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore } from "lucide-react";

import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { Tournament } from "@/types/tournament.types";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";

/**
 * The hub header's one status action (DESIGN.md §14 "Header actions").
 *
 * The status is derived from the tournament's nodes (the header badge shows it), so the only thing an admin sets is
 * `archived`: Archive on a `completed` tournament, Unarchive on an archived one. In any other status there is nothing
 * to offer, because the server refuses (`tournament_not_completed`). Needs `tournament.update`, so without it nothing
 * renders. Both go through the `ConfirmDialog`.
 */
export function TournamentStatusControl({
  tournament,
  canUpdate
}: Readonly<{
  tournament: Tournament;
  /** `tournament.update`, the grant the archive RPC checks. */
  canUpdate: boolean;
}>) {
  const t = useTranslations("adminTournament.hubActions");
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  const archived = tournament.status === "archived";

  // Failures surface through the global MutationCache toast.
  const mutation = useMutation({
    mutationFn: () => adminService.setArchived(tournament.id, !archived),
    onSuccess: () => {
      setConfirming(false);
      invalidateTournamentWorkspace(queryClient, tournament.id);
      notify.success(archived ? t("unarchived") : t("archived"));
    }
  });

  if (!canUpdate || (tournament.status !== "completed" && !archived)) return null;

  const label = archived ? t("unarchive") : t("archive");
  const Icon = archived ? ArchiveRestore : Archive;

  return (
    <>
      <Button variant="outline" size="sm" disabled={mutation.isPending} onClick={() => setConfirming(true)}>
        {mutation.isPending ? <Spinner /> : <Icon aria-hidden />}
        {label}
      </Button>

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        intent={{
          title: archived ? t("unarchiveTitle") : t("archiveTitle"),
          description: archived ? t("unarchiveDescription") : t("archiveDescription"),
          confirmLabel: label,
          tone: "neutral"
        }}
        pending={mutation.isPending}
        onConfirm={() => mutation.mutate()}
      />
    </>
  );
}
