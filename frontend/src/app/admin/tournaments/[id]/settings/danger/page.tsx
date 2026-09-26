"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { Tournament } from "@/types/tournament.types";
import { SettingsSectionPage } from "../SettingsSection";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

export default function DangerSettingsPage() {
  return (
    <SettingsSectionPage
      section="danger"
      description="Removing this tournament and everything recorded against it."
    >
      {({ tournament, tournamentId }) => (
        <DeleteTournament tournament={tournament} tournamentId={tournamentId} />
      )}
    </SettingsSectionPage>
  );
}

function DeleteTournament({
  tournament,
  tournamentId
}: Readonly<{ tournament: Tournament; tournamentId: number }>) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const deleteMutation = useMutation({
    mutationFn: () => adminService.deleteTournament(tournamentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.list() });
      notify.success("Tournament deleted successfully");
      router.push("/admin/tournaments");
    },
    onError: (error) => notify.apiError(error, { title: "Could not delete the tournament" })
  });

  return (
    <>
      <Card className="border-destructive/30 bg-destructive/5">
        <CardContent className="flex flex-col gap-4 py-5 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-destructive/80">
            Deleting a tournament permanently removes its logs, rosters and standings. There is no
            undo, and nothing else on this page is irreversible.
          </p>
          <Button
            type="button"
            variant="destructive"
            className="shrink-0 sm:w-auto"
            disabled={deleteMutation.isPending}
            onClick={() => setConfirmOpen(true)}
          >
            <Trash2 aria-hidden className="mr-2 size-4" />
            Delete tournament
          </Button>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        pending={deleteMutation.isPending}
        intent={{
          title: "Delete tournament",
          description: `“${tournament.name}” and every piece of workspace data linked to it will be removed. This cannot be undone.`,
          confirmLabel: "Delete tournament",
          tone: "danger",
          cascade: [
            "Tournament stages",
            "Teams and players",
            "Encounters and matches",
            "Standings rows"
          ],
          // Typing the name is what separates this from every other confirm in
          // the admin: it is the one action no invalidation can walk back.
          requireTyped: tournament.name
        }}
        onConfirm={() => deleteMutation.mutate()}
      />
    </>
  );
}
