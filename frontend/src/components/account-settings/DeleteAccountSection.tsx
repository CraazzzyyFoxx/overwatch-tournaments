"use client";

import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/error";
import { logout } from "@/lib/auth/logout";
import { notify } from "@/lib/notify";
import meService from "@/services/me.service";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import { useAuthProfileStore } from "@/stores/auth-profile.store";

type Refusal = "wrongPassword" | "reauth";

export default function DeleteAccountSection() {
  const t = useTranslations("accountSettings.danger");
  const passwordId = useId();
  const isSuperuser = useAuthProfileStore((s) => s.user?.isSuperuser ?? false);
  const hasPassword = useAuthProfileStore((s) => s.user?.hasPassword ?? false);
  const clearAuth = useAuthProfileStore((s) => s.clear);
  const closeSettings = useAccountSettingsModalStore((s) => s.close);
  const openAuthModal = useAuthModalStore((s) => s.open);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [refusal, setRefusal] = useState<Refusal | null>(null);

  const setDialogOpen = (open: boolean) => {
    setConfirmOpen(open);
    if (!open) {
      setPassword("");
      setRefusal(null);
    }
  };

  // Historical data (tournaments, matches, statistics, registrations) is
  // untouched — identity-svc only removes the account itself and unclaims the
  // player (see auth_flows.delete_me). The session is dead the moment this
  // returns, so go straight through the logout POST to drop the cookies rather
  // than leaving a stale profile in memory. A wrong password and a too-old
  // sign-in are answered inside the dialog; any other refusal closes it and
  // goes to the toast.
  const deleteAccount = useMutation({
    meta: { suppressErrorToast: true },
    mutationFn: () => meService.deleteAccount(hasPassword ? password : undefined),
    onSuccess: () => {
      clearAuth();
      void logout();
    },
    onError: (error) => {
      if (hasPassword && error instanceof ApiError && error.status === 401) {
        setRefusal("wrongPassword");
        return;
      }
      // A passwordless account whose sign-in is older than 10 minutes.
      if (
        error instanceof ApiError &&
        error.status === 403 &&
        error.details.some((d) => d.msg === "reauth_required")
      ) {
        setRefusal("reauth");
        return;
      }
      setDialogOpen(false);
      notify.apiError(error);
    }
  });

  // A fresh sign-in through the usual login dialog, landing back on this tab.
  const signInAgain = () => {
    setDialogOpen(false);
    closeSettings();
    openAuthModal(`${window.location.pathname}?settings=security`);
  };

  // The backend refuses to delete a superuser; offering the button would only
  // lead to that refusal.
  if (isSuperuser) return null;

  return (
    <>
      <SettingGroup id="security-delete" level={4} title={t("title")}>
        <SettingRow
          label={t("delete")}
          hint={
            <>
              {t("deleteDesc")} {t("deleteKeeps")}
            </>
          }
        >
          <Button variant="destructive" size="sm" onClick={() => setConfirmOpen(true)}>
            <Trash2 aria-hidden />
            {t("delete")}
          </Button>
        </SettingRow>
      </SettingGroup>
      {/* The dialog stays open while the request is in flight so the pending
          state stays visible. */}
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setDialogOpen}
        intent={{
          title: t("confirmTitle"),
          description: (
            <div className="space-y-3">
              <p>{t("confirmBody")}</p>
              {hasPassword ? (
                <div className="space-y-1.5">
                  <Label htmlFor={passwordId}>{t("currentPassword")}</Label>
                  <Input
                    id={passwordId}
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    aria-invalid={refusal === "wrongPassword" || undefined}
                    onChange={(event) => {
                      setPassword(event.target.value);
                      setRefusal(null);
                    }}
                  />
                </div>
              ) : null}
              {refusal === "wrongPassword" ? (
                <p role="alert" className="text-danger">
                  {t("wrongPassword")}
                </p>
              ) : null}
              {refusal === "reauth" ? (
                <div role="alert" className="space-y-2">
                  <p>{t("reauthRequired")}</p>
                  <Button type="button" variant="outline" size="sm" onClick={signInAgain}>
                    {t("signInAgain")}
                  </Button>
                </div>
              ) : null}
            </div>
          ),
          confirmLabel: t("confirmDelete"),
          tone: "danger"
        }}
        pending={deleteAccount.isPending}
        confirmDisabled={hasPassword ? !password : refusal === "reauth"}
        onConfirm={() => deleteAccount.mutate()}
      />
    </>
  );
}
