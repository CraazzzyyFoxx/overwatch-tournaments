"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Eye, EyeOff, Plus, Star, Unlink } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import { SocialIcon } from "@/components/social/SocialIcon";
import { getSocialProviderConfig, sortSocialAccounts } from "@/lib/social/providers";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { usePermissions } from "@/hooks/usePermissions";
import meService from "@/services/me.service";
import { revalidateUser } from "@/app/actions/users";
import { MAX_AVATAR_BYTES } from "@/lib/uploads";
import type { User } from "@/types/user.types";

import { SettingsGroup } from "./SettingsGroup";

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
      <SettingsGroup title={t("avatar.title")}>
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
            labels={{
              change: t("avatar.change"),
              upload: t("avatar.upload"),
              edit: t("avatar.edit"),
              drop: t("avatar.drop"),
              remove: t("avatar.remove"),
              unsupportedType: t("avatar.unsupported"),
              tooLarge: t("avatar.tooLarge", { mb: Math.round(MAX_AVATAR_BYTES / (1024 * 1024)) }),
            }}
          />
          <p className="text-caption text-pretty text-[color:var(--aqt-fg-dim)]">
            {canAvatar ? t("avatar.hint") : t("avatar.disabled")}
          </p>
        </div>
      </SettingsGroup>

      <SettingsGroup title={t("linked.title")}>
        {!canSocial ? (
          <p className="text-caption text-[color:var(--aqt-fg-dim)]">{t("linked.disabled")}</p>
        ) : (
          <>
            {socialQuery.isLoading ? (
              <div className="space-y-1.5" aria-hidden>
                <Skeleton className="h-11 rounded-lg" />
                <Skeleton className="h-11 rounded-lg" />
              </div>
            ) : accounts.length === 0 ? (
              <p className="text-caption text-[color:var(--aqt-fg-dim)]">{t("linked.empty")}</p>
            ) : (
              <ul className="space-y-1.5">
                {accounts.map((account) => {
                  const visible = account.visible_global !== false;
                  return (
                    <li
                      key={account.id}
                      className="flex items-center gap-2 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-3 py-2"
                    >
                      {/* Hidden is shown as a word, and only the identity dims:
                          fading the whole row used to make its live controls
                          look disabled. */}
                      <span className={cn("flex min-w-0 flex-1 items-center gap-2", !visible && "opacity-60")}>
                        <SocialIcon provider={account.provider} size={15} />
                        <span className="truncate text-sm text-[color:var(--aqt-fg)]" title={account.username}>
                          {account.username}
                        </span>
                      </span>
                      {!visible ? (
                        <span className="shrink-0 text-caption text-[color:var(--aqt-fg-dim)]">
                          {t("linked.hidden")}
                        </span>
                      ) : null}
                      {account.is_verified && (
                        <Check
                          className="h-3.5 w-3.5 shrink-0 text-[color:var(--aqt-emerald)]"
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
                        aria-label={
                          visible
                            ? t("linked.hideAria", { name: account.username })
                            : t("linked.showAria", { name: account.username })
                        }
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
                    </li>
                  );
                })}
              </ul>
            )}
            <div className="flex flex-wrap gap-2">
              {OAUTH_ADDABLE.map((provider) => {
                const label = getSocialProviderConfig(provider).label;
                return (
                  <a
                    key={provider}
                    href={linkHref(provider)}
                    aria-label={t("linked.linkAria", { provider: label })}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-2.5 text-xs text-[color:var(--aqt-fg)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <Plus className="h-3 w-3" aria-hidden />
                    <SocialIcon provider={provider} size={13} />
                    {label}
                  </a>
                );
              })}
            </div>
            <p className="text-caption text-pretty text-[color:var(--aqt-fg-dim)]">{t("linked.footnote")}</p>
          </>
        )}
      </SettingsGroup>
    </div>
  );
}
