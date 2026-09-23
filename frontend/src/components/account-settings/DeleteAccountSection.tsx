"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Loader2, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { logout } from "@/lib/auth/logout";
import meService from "@/services/me.service";
import { useAuthProfileStore } from "@/stores/auth-profile.store";

import { SettingsGroup } from "./SettingsGroup";

export default function DeleteAccountSection() {
  const t = useTranslations("accountSettings.danger");
  const isSuperuser = useAuthProfileStore((s) => s.user?.isSuperuser ?? false);
  const clearAuth = useAuthProfileStore((s) => s.clear);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Historical data (tournaments, matches, statistics, registrations) is
  // untouched — identity-svc only removes the account itself and unclaims the
  // player (see auth_flows.delete_me). The session is dead the moment this
  // returns, so go straight through the logout POST to drop the cookies rather
  // than leaving a stale profile in memory. Refusals surface via the global toast.
  const deleteAccount = useMutation({
    mutationFn: () => meService.deleteAccount(),
    onSuccess: () => {
      clearAuth();
      void logout();
    },
    onError: () => setConfirmOpen(false),
  });

  // The backend refuses to delete a superuser; offering the button would only
  // lead to that refusal.
  if (isSuperuser) return null;

  return (
    <SettingsGroup title={t("title")} tone="danger">
      <div className="space-y-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4">
        <p className="text-caption text-[color:var(--aqt-fg-muted)]">{t("deleteDesc")}</p>
        <p className="text-caption text-[color:var(--aqt-fg-dim)]">{t("deleteKeeps")}</p>
        <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
          <AlertDialogTrigger asChild>
            <Button variant="destructive" size="sm">
              <Trash2 aria-hidden />
              {t("delete")}
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t("confirmTitle")}</AlertDialogTitle>
              <AlertDialogDescription>{t("confirmBody")}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={deleteAccount.isPending}>{t("confirmCancel")}</AlertDialogCancel>
              <AlertDialogAction
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                disabled={deleteAccount.isPending}
                onClick={(event) => {
                  // Hold the dialog open while the request is in flight so the
                  // pending state stays visible; onError closes it and the
                  // global toast carries the reason.
                  event.preventDefault();
                  deleteAccount.mutate();
                }}
              >
                {deleteAccount.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />}
                {t("confirmDelete")}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </SettingsGroup>
  );
}
