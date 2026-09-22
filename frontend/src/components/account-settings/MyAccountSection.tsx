"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Check, Eye, EyeOff, Loader2, Plus, Star, Trash2, Unlink } from "lucide-react";
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
import { Switch } from "@/components/ui/switch";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import { SocialIcon } from "@/components/social/SocialIcon";
import { getSocialProviderConfig, sortSocialAccounts } from "@/lib/social/providers";
import { logout } from "@/lib/auth/logout";
import { notify } from "@/lib/notify";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { usePermissions } from "@/hooks/usePermissions";
import meService from "@/services/me.service";
import { revalidateUser } from "@/app/actions/users";
import { MAX_AVATAR_BYTES } from "@/lib/uploads";
import type { User } from "@/types/user.types";

// Providers a user can OAuth-link (and thereby verify).
const OAUTH_ADDABLE = ["battlenet", "discord", "twitch"] as const;

export default function MyAccountSection() {
  const t = useTranslations("accountSettings");
  const user = useAuthProfileStore((s) => s.user);
  const fetchMe = useAuthProfileStore((s) => s.fetchMe);
  const clearAuth = useAuthProfileStore((s) => s.clear);
  const { canUseCapability } = usePermissions();
  const canAvatar = canUseCapability("account.avatar");
  const canSocial = canUseCapability("account.social");
  const queryClient = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const socialQuery = useQuery({
    queryKey: ["me", "social"],
    queryFn: () => meService.getSocialAccounts(),
    enabled: canSocial,
  });
  const accounts = sortSocialAccounts(socialQuery.data?.social_accounts ?? []);
  // Only an explicit `false` is a veto: responses cached before the flag
  // existed omit it entirely, and the backend default is "allowed" — the same
  // rule the per-account row applies to `visible_global`.
  const streamVisible = socialQuery.data?.stream_visible !== false;

  // Persist the fresh user into the query cache AND bust the Next Data Cache so
  // the public users/[slug] header / list / search reflect the change at once.
  const writeSocial = (user: User) => {
    void revalidateUser(user.id);
    queryClient.setQueryData(["me", "social"], user);
  };

  // Failures surface via the global MutationCache.onError toast (see providers.tsx),
  // so these only need to refresh the profile on success.
  const avatarUpload = useMutation({
    mutationFn: (file: File) => meService.setAvatar(file),
    onSuccess: () => {
      void revalidateUser();
      fetchMe({ force: true });
    },
  });
  const avatarDelete = useMutation({
    mutationFn: () => meService.deleteAvatar(),
    onSuccess: () => {
      void revalidateUser();
      fetchMe({ force: true });
    },
  });
  const setPrimary = useMutation({
    mutationFn: (id: number) => meService.setSocialPrimary(id),
    onSuccess: writeSocial,
  });
  const setVisibility = useMutation({
    mutationFn: ({ id, visible }: { id: number; visible: boolean }) =>
      meService.setSocialVisibility(id, visible),
    onSuccess: writeSocial,
  });
  // Same write-back path as the per-account toggle: the endpoint answers with
  // the refreshed user, so the switch state comes straight from the server.
  const setStreamVisibility = useMutation({
    mutationFn: (visible: boolean) => meService.setStreamVisibility(visible),
    onSuccess: writeSocial,
  });
  // Self-service OAuth unlink. Returns no body (204), so refetch the list rather
  // than writing it back; errors (e.g. "set a password first") surface via the
  // global mutation toast.
  const unlinkAccount = useMutation({
    mutationFn: (provider: string) => meService.unlinkOAuth(provider),
    onSuccess: () => {
      void revalidateUser();
      void queryClient.invalidateQueries({ queryKey: ["me", "social"] });
    },
  });
  // Self-service account deletion. Historical data (tournaments, matches,
  // statistics, registrations) is untouched — identity-svc only removes the
  // account itself and unclaims the player (see auth_flows.delete_me). The
  // session is dead the moment this returns, so go straight through the logout
  // POST to drop the cookies rather than leaving a stale profile in memory.
  // Refusals (a superuser account) surface via the global toast.
  const deleteAccount = useMutation({
    mutationFn: () => meService.deleteAccount(),
    onSuccess: () => {
      clearAuth();
      void logout();
    },
    onError: () => setConfirmDelete(false),
  });

  const linkHref = (provider: string) => {
    const next =
      typeof window !== "undefined" ? `${window.location.pathname}?settings=profile` : "/?settings=profile";
    return `/auth/${provider}/login?action=link&next=${encodeURIComponent(next)}`;
  };

  return (
    <div className="space-y-8">
      {/* ── Avatar ─────────────────────────────────────── */}
      <section className="space-y-3">
        <h4 className="text-sm font-medium text-[color:var(--aqt-fg-muted)]">{t("avatar.title")}</h4>
        <div className="flex items-center gap-4">
          <EditableAvatar
            src={user?.avatarUrl}
            name={user?.username}
            size={72}
            editable={canAvatar}
            busy={avatarUpload.isPending || avatarDelete.isPending}
            onSelectFile={(file) => avatarUpload.mutate(file)}
            onDelete={user?.avatarUrl ? () => avatarDelete.mutate() : undefined}
            maxSizeBytes={MAX_AVATAR_BYTES}
            onError={(message) => notify.error(message)}
          />
          <p className="text-xs text-[color:var(--aqt-fg-dim)]">
            {canAvatar ? t("avatar.hint") : t("avatar.disabled")}
          </p>
        </div>
      </section>

      {/* ── Linked accounts ────────────────────────────── */}
      <section className="space-y-3">
        <h4 className="text-sm font-medium text-[color:var(--aqt-fg-muted)]">{t("linked.title")}</h4>
        {!canSocial ? (
          <p className="text-xs text-[color:var(--aqt-fg-dim)]">{t("linked.disabled")}</p>
        ) : (
          <>
            <div className="space-y-1.5">
              {socialQuery.isLoading && (
                <Loader2
                  className="h-4 w-4 animate-spin text-[color:var(--aqt-fg-muted)]"
                  aria-label={t("linked.title")}
                />
              )}
              {!socialQuery.isLoading && accounts.length === 0 && (
                <p className="text-sm text-[color:var(--aqt-fg-dim)]">{t("linked.empty")}</p>
              )}
              {accounts.map((account) => {
                const visible = account.visible_global !== false;
                return (
                  <div
                    key={account.id}
                    className={`flex items-center gap-2 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-3 py-2 ${visible ? "" : "opacity-50"}`}
                  >
                    <SocialIcon provider={account.provider} size={15} />
                    <span className="flex-1 truncate text-sm text-[color:var(--aqt-fg)]">
                      {account.username}
                    </span>
                    {account.is_verified && (
                      <Check
                        className="h-3.5 w-3.5 text-[color:var(--aqt-emerald)]"
                        aria-label={t("linked.verifiedAria")}
                      />
                    )}
                    {account.is_primary ? (
                      <Star
                        className="h-4 w-4 shrink-0 fill-[color:var(--aqt-amber)] text-[color:var(--aqt-amber)]"
                        aria-label={t("linked.primaryAria")}
                      />
                    ) : (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7"
                        disabled={!account.is_verified || setPrimary.isPending}
                        onClick={() => setPrimary.mutate(account.id)}
                        aria-label={
                          account.is_verified
                            ? t("linked.makePrimary")
                            : t("linked.primaryNeedsVerified")
                        }
                      >
                        <Star className="h-3.5 w-3.5" aria-hidden />
                      </Button>
                    )}
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7 text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]"
                      disabled={setVisibility.isPending}
                      onClick={() => setVisibility.mutate({ id: account.id, visible: !visible })}
                      aria-label={visible ? t("linked.hideAria", { name: account.username }) : t("linked.showAria", { name: account.username })}
                    >
                      {visible ? (
                        <Eye className="h-3.5 w-3.5" aria-hidden />
                      ) : (
                        <EyeOff className="h-3.5 w-3.5" aria-hidden />
                      )}
                    </Button>
                    {account.is_verified && (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7 text-[color:var(--aqt-fg-muted)] hover:text-destructive"
                        disabled={unlinkAccount.isPending}
                        onClick={() => {
                          const label = getSocialProviderConfig(account.provider).label;
                          if (window.confirm(t("linked.disconnectConfirm", { provider: label }))) {
                            unlinkAccount.mutate(account.provider);
                          }
                        }}
                        aria-label={t("linked.disconnectAria", { name: account.username })}
                      >
                        <Unlink className="h-3.5 w-3.5" aria-hidden />
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              {OAUTH_ADDABLE.map((provider) => (
                <a
                  key={provider}
                  href={linkHref(provider)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] px-2.5 py-1.5 text-xs text-[color:var(--aqt-fg)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Plus className="h-3 w-3" aria-hidden />
                  <SocialIcon provider={provider} size={13} />
                  {getSocialProviderConfig(provider).label}
                </a>
              ))}
            </div>
            <p className="text-label text-[color:var(--aqt-fg-dim)]">{t("linked.footnote")}</p>
          </>
        )}
      </section>

      {/* ── Stream privacy ─────────────────────────────── */}
      <section className="space-y-3">
        <h4 className="text-sm font-medium text-[color:var(--aqt-fg-muted)]">{t("stream.title")}</h4>
        <div className="flex items-start gap-3 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-3 py-2.5">
          <div className="flex-1 space-y-1">
            <p id="stream-visibility-label" className="text-sm text-[color:var(--aqt-fg)]">
              {t("stream.toggleLabel")}
            </p>
            <p id="stream-visibility-desc" className="text-xs text-[color:var(--aqt-fg-dim)]">
              {t("stream.toggleDesc")}
            </p>
          </div>
          <Switch
            checked={streamVisible}
            // Never let the switch act on a guess: without a loaded response
            // there is no current value to invert, and a wrong payload here
            // silently re-publishes a stream the user meant to hide.
            disabled={!socialQuery.data || setStreamVisibility.isPending}
            onCheckedChange={(next) => setStreamVisibility.mutate(next)}
            aria-labelledby="stream-visibility-label"
            aria-describedby="stream-visibility-desc"
          />
        </div>
        <p className="text-label text-[color:var(--aqt-fg-dim)]">{t("stream.footnote")}</p>
      </section>

      {/* ── Danger zone ────────────────────────────────── */}
      {!user?.isSuperuser && (
        <section className="space-y-3">
          <h4 className="text-sm font-medium text-destructive">{t("danger.title")}</h4>
          <div className="space-y-3 rounded-lg border border-destructive/40 bg-destructive/5 p-3">
            <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("danger.deleteDesc")}</p>
            <p className="text-label text-[color:var(--aqt-fg-dim)]">{t("danger.deleteKeeps")}</p>
            <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" size="sm">
                  <Trash2 className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                  {t("danger.delete")}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>{t("danger.confirmTitle")}</AlertDialogTitle>
                  <AlertDialogDescription>{t("danger.confirmBody")}</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel disabled={deleteAccount.isPending}>
                    {t("danger.confirmCancel")}
                  </AlertDialogCancel>
                  <AlertDialogAction
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                    disabled={deleteAccount.isPending}
                    onClick={(event) => {
                      // Hold the dialog open while the request is in flight so
                      // the pending state stays visible; onError closes it and
                      // the global toast carries the reason.
                      event.preventDefault();
                      deleteAccount.mutate();
                    }}
                  >
                    {deleteAccount.isPending && (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
                    )}
                    {t("danger.confirmDelete")}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </section>
      )}
    </div>
  );
}
