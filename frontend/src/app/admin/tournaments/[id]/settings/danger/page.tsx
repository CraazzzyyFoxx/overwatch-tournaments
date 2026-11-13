"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Card, CardContent } from "@craazzzyyfoxx/admin-kit/ui/card";
import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { Tournament } from "@/types/tournament.types";
import { SettingsSectionPage } from "../SettingsSection";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

export default function DangerSettingsPage() {
  return (
    <SettingsSectionPage section="danger">
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
  const t = useTranslations("adminTournament.danger");
  const router = useRouter();
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const deleteMutation = useMutation({
    mutationFn: () => adminService.deleteTournament(tournamentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.list() });
      notify.success(t("deleted"));
      router.push("/admin/tournaments");
    },
    onError: (error) => notify.apiError(error, { title: t("deleteError") })
  });

  return (
    <>
      <Card>
        <CardContent className="flex flex-col gap-4 py-5 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">
            {t("warning")}
          </p>
          <Button
            type="button"
            variant="destructive"
            className="shrink-0 sm:w-auto"
            disabled={deleteMutation.isPending}
            onClick={() => setConfirmOpen(true)}
          >
            <Trash2 aria-hidden className="mr-2 size-4" />
            {t("delete")}
          </Button>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        pending={deleteMutation.isPending}
        intent={{
          title: t("delete"),
          description: t("confirmDescription", { name: tournament.name }),
          confirmLabel: t("delete"),
          tone: "danger",
          cascade: [
            t("stages"),
            t("teamsPlayers"),
            t("encountersMatches"),
            t("standingsRows")
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
