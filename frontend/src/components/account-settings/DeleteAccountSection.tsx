"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
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
        <Button variant="destructive" size="sm" onClick={() => setConfirmOpen(true)}>
          <Trash2 aria-hidden />
          {t("delete")}
        </Button>
        {/* The dialog stays open while the request is in flight so the pending
            state stays visible; onError closes it and the global toast carries
            the reason. */}
        <ConfirmDialog
          open={confirmOpen}
          onOpenChange={setConfirmOpen}
          intent={{
            title: t("confirmTitle"),
            description: t("confirmBody"),
            confirmLabel: t("confirmDelete"),
            tone: "danger"
          }}
          pending={deleteAccount.isPending}
          onConfirm={() => deleteAccount.mutate()}
        />
      </div>
    </SettingsGroup>
  );
}
