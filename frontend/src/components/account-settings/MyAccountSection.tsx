"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Eye, EyeOff, Loader2, Plus, Star, Unlink } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import { SocialIcon } from "@/components/social/SocialIcon";
import { getSocialProviderConfig, sortSocialAccounts } from "@/lib/social-providers";
import { notify } from "@/lib/notify";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { usePermissions } from "@/hooks/usePermissions";
import meService from "@/services/me.service";
import { revalidateUser } from "@/app/actions/users";
import { MAX_AVATAR_BYTES } from "@/lib/avatar";
import type { User } from "@/types/user.types";

// Providers a user can OAuth-link (and thereby verify).
const OAUTH_ADDABLE = ["battlenet", "discord", "twitch"] as const;

export default function MyAccountSection() {
  const t = useTranslations("accountSettings");
  const user = useAuthProfileStore((s) => s.user);
  const fetchMe = useAuthProfileStore((s) => s.fetchMe);
  const { canUseCapability } = usePermissions();
  const canAvatar = canUseCapability("account.avatar");
  const canSocial = canUseCapability("account.social");
  const queryClient = useQueryClient();

  const socialQuery = useQuery({
    queryKey: ["me", "social"],
    queryFn: () => meService.getSocialAccounts(),
    enabled: canSocial,
  });
  const accounts = sortSocialAccounts(socialQuery.data?.social_accounts ?? []);

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

  const linkHref = (provider: string) => {
    const next =
      typeof window !== "undefined" ? `${window.location.pathname}?settings=profile` : "/?settings=profile";
    return `/auth/${provider}/login?action=link&next=${encodeURIComponent(next)}`;
  };

  return (
    <div className="space-y-8">
      {/* ── Avatar ─────────────────────────────────────── */}
      <section className="space-y-3">
        <h4 className="text-sm font-medium text-slate-300">{t("avatar.title")}</h4>
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
          {canAvatar ? (
            <p className="text-xs text-slate-500">{t("avatar.hint")}</p>
          ) : (
            <p className="text-xs text-slate-500">{t("avatar.disabled")}</p>
          )}
        </div>
      </section>

      {/* ── Linked accounts ────────────────────────────── */}
      <section className="space-y-3">
        <h4 className="text-sm font-medium text-slate-300">{t("linked.title")}</h4>
        {!canSocial ? (
          <p className="text-xs text-slate-500">{t("linked.disabled")}</p>
        ) : (
          <>
            <div className="space-y-1.5">
              {socialQuery.isLoading && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
              {!socialQuery.isLoading && accounts.length === 0 && (
                <p className="text-sm text-slate-500">{t("linked.empty")}</p>
              )}
              {accounts.map((account) => {
                const visible = account.visible_global !== false;
                return (
                  <div
                    key={account.id}
                    className={`flex items-center gap-2 rounded-lg border border-white/5 bg-white/3 px-3 py-2 ${visible ? "" : "opacity-50"}`}
                  >
                    <SocialIcon provider={account.provider} size={15} />
                    <span className="flex-1 truncate text-sm text-white">{account.username}</span>
                    {account.is_verified && <Check className="h-3.5 w-3.5 text-emerald-400" aria-label={t("linked.verifiedAria")} />}
                    {account.is_primary ? (
                      <Star className="h-4 w-4 shrink-0 fill-amber-400 text-amber-400" aria-label={t("linked.primaryAria")} />
                    ) : (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7"
                        title={account.is_verified ? t("linked.makePrimary") : t("linked.primaryNeedsVerified")}
                        disabled={!account.is_verified || setPrimary.isPending}
                        onClick={() => setPrimary.mutate(account.id)}
                      >
                        <Star className="h-3.5 w-3.5" />
                      </Button>
                    )}
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7 text-slate-400 hover:text-white"
                      title={visible ? t("linked.hide") : t("linked.show")}
                      disabled={setVisibility.isPending}
                      onClick={() => setVisibility.mutate({ id: account.id, visible: !visible })}
                      aria-label={visible ? t("linked.hideAria", { name: account.username }) : t("linked.showAria", { name: account.username })}
                    >
                      {visible ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
                    </Button>
                    {account.is_verified && (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7 text-slate-400 hover:text-red-400"
                        title={t("linked.disconnect")}
                        disabled={unlinkAccount.isPending}
                        onClick={() => {
                          const label = getSocialProviderConfig(account.provider).label;
                          if (window.confirm(t("linked.disconnectConfirm", { provider: label }))) {
                            unlinkAccount.mutate(account.provider);
                          }
                        }}
                        aria-label={t("linked.disconnectAria", { name: account.username })}
                      >
                        <Unlink className="h-3.5 w-3.5" />
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
                  className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-white transition-colors hover:bg-white/10"
                >
                  <Plus className="h-3 w-3" />
                  <SocialIcon provider={provider} size={13} />
                  {getSocialProviderConfig(provider).label}
                </a>
              ))}
            </div>
            <p className="text-[11px] text-slate-500">{t("linked.footnote")}</p>
          </>
        )}
      </section>
    </div>
  );
}
