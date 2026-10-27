"use client";

import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, MoreHorizontal, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { HandleLabel } from "@/components/HandleLabel";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { SettingGroup } from "@/components/kit/SettingRow";
import { SocialIcon } from "@/components/social/SocialIcon";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { revalidateUser } from "@/app/actions/users";
import { SITE_NAME } from "@/config/site";
import { usePermissions } from "@/hooks/usePermissions";
import { getSocialProviderConfig, hasTaggedHandle, socialAccountLabel } from "@/lib/social/providers";
import { userQueryKeys } from "@/lib/users/query-keys";
import { cn } from "@/lib/utils";
import meService from "@/services/me.service";
import type { SocialProvider, User } from "@/types/user.types";

import { OAUTH_ADDABLE, groupLinkedAccounts } from "./linked-accounts";

/** One block of the group body; the body's `divide-y` draws the hairlines between blocks. */
const BLOCK = "py-3 first:pt-0 last:pb-0";

/** The OAuth link flow; it returns to this dialog's profile tab. Linking an existing account verifies it. */
function linkHref(provider: string) {
  const next =
    typeof window !== "undefined" ? `${window.location.pathname}?settings=profile` : "/?settings=profile";
  return `/auth/${provider}/login?action=link&next=${encodeURIComponent(next)}`;
}

function ProviderTile({ provider }: Readonly<{ provider: string }>) {
  return (
    <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-[color:var(--aqt-overlay-border)] bg-[color:var(--aqt-overlay-2)]">
      <SocialIcon provider={provider} size={16} decorative />
    </span>
  );
}

export function LinkedAccountsGroup() {
  const t = useTranslations("accountSettings");
  const { canUseCapability } = usePermissions();
  const canSocial = canUseCapability("account.social");
  const queryClient = useQueryClient();

  const socialQuery = useQuery({
    queryKey: userQueryKeys.mySocial(),
    queryFn: () => meService.getSocialAccounts(),
    enabled: canSocial,
    // A failed load is shown in the group itself, with a retry.
    meta: { suppressErrorToast: true }
  });

  // Persist the fresh user into the query cache AND bust the Next Data Cache so
  // the public users/[slug] header / list / search reflect the change at once.
  const writeSocial = (user: User) => {
    void revalidateUser(user.id);
    queryClient.setQueryData(userQueryKeys.mySocial(), user);
  };

  // Failures surface via the global MutationCache.onError toast (see providers.tsx).
  const setPrimary = useMutation({
    mutationFn: (id: number) => meService.setSocialPrimary(id),
    onSuccess: writeSocial
  });
  const setVisibility = useMutation({
    mutationFn: ({ id, visible }: { id: number; visible: boolean }) => meService.setSocialVisibility(id, visible),
    onSuccess: writeSocial
  });

  // One confirmation for the whole group. The target outlives `open` so the
  // title keeps its provider while the dialog animates out.
  const [unlinkTarget, setUnlinkTarget] = useState<SocialProvider | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  // Self-service OAuth unlink. Returns no body (204), so refetch the list rather
  // than writing it back; errors (e.g. "set a password first") surface via the
  // global mutation toast.
  const unlink = useMutation({
    mutationFn: (provider: string) => meService.unlinkOAuth(provider),
    onSuccess: () => {
      void revalidateUser();
      void queryClient.invalidateQueries({ queryKey: userQueryKeys.mySocial() });
    },
    onSettled: () => setConfirmOpen(false)
  });

  const data = socialQuery.data;
  const { connected, connectable } = groupLinkedAccounts(data?.social_accounts ?? [], OAUTH_ADDABLE);

  let body: ReactNode;
  if (!canSocial) {
    body = <p className="text-caption text-[color:var(--aqt-fg-dim)]">{t("linked.disabled")}</p>;
  } else if (data) {
    body = (
      <>
        {connected.map(({ provider, accounts }) => {
          const config = getSocialProviderConfig(provider);
          const addable = OAUTH_ADDABLE.includes(provider);
          const several = accounts.length > 1;
          return (
            <div key={provider} className={BLOCK}>
              <div className="flex items-center gap-3">
                <ProviderTile provider={provider} />
                <p className="min-w-0 flex-1 truncate text-sm font-medium text-[color:var(--aqt-fg)]">{config.label}</p>
                {addable ? (
                  <Button variant="ghost" size="sm" asChild>
                    <a href={linkHref(provider)} aria-label={t("linked.addAria", { provider: config.label })}>
                      <Plus aria-hidden />
                      {t("linked.add")}
                    </a>
                  </Button>
                ) : null}
              </div>
              <ul aria-label={config.label} className="mt-2 space-y-2 pl-11">
                {accounts.map((account) => {
                  const name = socialAccountLabel(account);
                  const visible = account.visible_global !== false;
                  const unverified = Boolean(config.canBeVerified) && !account.is_verified;
                  const offerPrimary = several && !account.is_primary;
                  // Exceptions only: verified, visible and the sole account is the norm.
                  const meta = [
                    several && account.is_primary && t("linked.primary"),
                    !visible && t("linked.hidden"),
                    unverified && t("linked.unverified")
                  ].filter(Boolean);
                  // Only the identity dims when hidden: fading the whole row
                  // makes its live controls look disabled.
                  const identityClass = cn(
                    "min-w-0 truncate text-sm text-[color:var(--aqt-fg)]",
                    !visible && "opacity-60"
                  );
                  return (
                    <li key={account.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <div className="flex min-w-0 flex-1 basis-40 items-center gap-2">
                        {hasTaggedHandle(provider) ? (
                          <HandleLabel handle={account.username} title={account.username} className={identityClass} />
                        ) : (
                          <span title={name} className={identityClass}>
                            {name}
                          </span>
                        )}
                        {meta.length > 0 ? (
                          <span className="shrink-0 text-caption text-[color:var(--aqt-fg-dim)]">
                            {meta.join(" · ")}
                          </span>
                        ) : null}
                      </div>
                      <div className="ml-auto flex shrink-0 items-center gap-1">
                        {unverified && addable ? (
                          <Button variant="outline" size="sm" asChild>
                            <a href={linkHref(provider)} aria-label={t("linked.verifyAria", { name })}>
                              {t("linked.verify")}
                            </a>
                          </Button>
                        ) : null}
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              disabled={setVisibility.isPending}
                              onClick={() => setVisibility.mutate({ id: account.id, visible: !visible })}
                              aria-label={visible ? t("linked.hideAria", { name }) : t("linked.showAria", { name })}
                            >
                              {visible ? <Eye aria-hidden /> : <EyeOff aria-hidden />}
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>{visible ? t("linked.hide") : t("linked.show")}</TooltipContent>
                        </Tooltip>
                        {offerPrimary || account.is_verified ? (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="icon-sm" aria-label={t("linked.actionsAria", { name })}>
                                <MoreHorizontal aria-hidden />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              {offerPrimary ? (
                                <DropdownMenuItem
                                  className="flex-col items-start gap-0.5"
                                  disabled={!account.is_verified || setPrimary.isPending}
                                  onSelect={() => setPrimary.mutate(account.id)}
                                >
                                  {t("linked.makePrimary")}
                                  {account.is_verified ? null : (
                                    <span className="text-caption text-muted-foreground">
                                      {t("linked.primaryNeedsVerified")}
                                    </span>
                                  )}
                                </DropdownMenuItem>
                              ) : null}
                              {account.is_verified ? (
                                <DropdownMenuItem
                                  variant="destructive"
                                  onSelect={() => {
                                    setUnlinkTarget(provider);
                                    setConfirmOpen(true);
                                  }}
                                >
                                  {t("linked.disconnect")}
                                </DropdownMenuItem>
                              ) : null}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        ) : (
                          // Holds the menu's column so every row's eye lines up.
                          <span aria-hidden className="size-7 shrink-0" />
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
        {connectable.length > 0 ? (
          <div className={cn(BLOCK, "space-y-3")}>
            {connected.length > 0 ? <p className={eyebrowClass("faint")}>{t("linked.connectableTitle")}</p> : null}
            <ul className="space-y-3">
              {connectable.map((provider) => {
                const label = getSocialProviderConfig(provider).label;
                // A provider whose link makes a game rank public says so in `linked.<provider>Notice`.
                const noticeKey = `linked.${provider}Notice` as "linked.riotNotice";
                const notice = t.has(noticeKey) ? t(noticeKey, { siteName: SITE_NAME }) : null;
                return (
                  <li key={provider} className="flex items-center gap-3">
                    <ProviderTile provider={provider} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-[color:var(--aqt-fg)]">{label}</p>
                      {notice ? (
                        <p className="text-caption text-pretty text-[color:var(--aqt-fg-dim)]">{notice}</p>
                      ) : null}
                    </div>
                    <Button variant="outline" size="sm" asChild>
                      <a href={linkHref(provider)} aria-label={t("linked.linkAria", { provider: label })}>
                        {t("linked.connect")}
                      </a>
                    </Button>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </>
    );
  } else if (socialQuery.isError) {
    // A failed load must not read as "no linked accounts". Unframed: the group is the card.
    body = (
      <PageStateCard
        state="error"
        onAction={() => void socialQuery.refetch()}
        className="border-0 bg-transparent px-0 py-6"
      />
    );
  } else {
    body = ["a", "b"].map((key) => (
      <div key={key} className={cn(BLOCK, "space-y-2")} aria-hidden>
        <div className="flex items-center gap-3">
          <Skeleton className="size-8 rounded-md" />
          <Skeleton className="h-4 w-24" />
        </div>
        <Skeleton className="ml-11 h-4 w-40" />
      </div>
    ));
  }

  return (
    <TooltipProvider>
      <SettingGroup
        id="account-linked"
        level={4}
        title={t("linked.title")}
        description={canSocial ? t("linked.desc") : undefined}
      >
        {body}
      </SettingGroup>
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={(open) => {
          if (!unlink.isPending) setConfirmOpen(open);
        }}
        intent={{
          title: t("linked.disconnectTitle", {
            provider: unlinkTarget ? getSocialProviderConfig(unlinkTarget).label : ""
          }),
          description: t("linked.disconnectBody"),
          confirmLabel: t("linked.disconnect"),
          tone: "warning"
        }}
        pending={unlink.isPending}
        onConfirm={() => {
          if (unlinkTarget) unlink.mutate(unlinkTarget);
        }}
      />
    </TooltipProvider>
  );
}
