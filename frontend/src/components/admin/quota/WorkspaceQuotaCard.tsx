"use client";

import { useId } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { LinkTabs, type LinkTabItem } from "@/components/kit/LinkTabs";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import workspaceService from "@/services/workspace.service";
import type { QuotaScope, QuotaScopePolicy } from "@/types/auth.types";
import { Spinner } from "@/components/ui/spinner";
import { hasQuotaOverride } from "./dimensions";
import { QuotaLimitFields } from "./QuotaLimitFields";
import { QuotaUsagePanel } from "./QuotaUsagePanel";
import { useQuotaDraft } from "./useQuotaDraft";

/** In table order: the tenant pool first, then the two per-principal buckets. */
const SCOPES: readonly QuotaScope[] = ["workspace", "key", "session"];

/** `?tab=` like every other admin tab row, so one scope's form is linkable. */
const SCOPE_PARAM = "tab";

function workspaceQuotaKey(workspaceId: number) {
  return ["workspace", workspaceId, "quota", "usage"] as const;
}

/**
 * One scope's override row.
 *
 * Each scope is its own row in `quota.workspace_limit` and its own write, so it
 * saves on its own: sequencing three writes behind one button would leave a
 * rejected second scope with the first already stored, and no way to say which.
 */
function WorkspaceQuotaScopeCard({
  workspaceId,
  scope,
  policy,
  canRaise
}: Readonly<{
  workspaceId: number;
  scope: QuotaScope;
  policy: QuotaScopePolicy | null;
  canRaise: boolean;
}>) {
  const t = useTranslations("quota");
  const fieldPrefix = useId();
  const queryClient = useQueryClient();
  const form = useQuotaDraft(policy);

  const save = useMutation({
    mutationFn: () => workspaceService.setQuota(workspaceId, scope, form.draft),
    onSuccess: async () => {
      notify.success(t("saved"));
      await queryClient.invalidateQueries({ queryKey: workspaceQuotaKey(workspaceId) });
    },
    onError: (error) => {
      if (!form.reject(error)) notify.apiError(error, { title: t("errors.saveFailed") });
    }
  });

  // An all-null payload deletes the row, so the button says so — but only when
  // there is a row to delete. A scope that already inherits must not offer to
  // "stop overriding" something it never overrode.
  const removing = form.overridden && !hasQuotaOverride(form.draft);
  const blocked = form.raised.length > 0 && !canRaise;

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="space-y-1.5">
          <CardTitle className="text-base">{t(`scopes.${scope}.label`)}</CardTitle>
          <CardDescription>{t(`scopes.${scope}.hint`)}</CardDescription>
        </div>
        {/* `info`, not `accent`: the light-theme primary is a near-black, which
            makes an "overridden" chip look like the neutral "inherited" one at a
            glance — the state has to be readable without reading. */}
        <Badge tone={form.overridden ? "info" : "neutral"} className="shrink-0 font-normal">
          {t(form.overridden ? "state.overridden" : "state.inherited")}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <QuotaLimitFields
          idPrefix={fieldPrefix}
          values={form.draft}
          inherited={policy?.inherited}
          raised={form.raised}
          canRaise={canRaise}
          errors={form.errors}
          disabled={save.isPending}
          onChange={form.set}
        />
        <div className="flex flex-wrap items-center justify-end gap-2">
          {/* Rendered even when clean: a button that vanishes under the caret
              after its own click drops keyboard focus to the document body. */}
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={!form.dirty || save.isPending}
            onClick={form.reset}
          >
            {t("reset")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant={removing ? "destructive" : "default"}
            // Only the no-op is disabled. A refused raise keeps the button live
            // and sends focus to the number that has to move, which is the one
            // thing the operator can act on.
            disabled={!form.dirty || save.isPending}
            onClick={() => {
              if (blocked) {
                document.getElementById(`${fieldPrefix}-${form.raised[0]}`)?.focus();
                return;
              }
              save.mutate();
            }}
          >
            {save.isPending ? (
              <>
                <Spinner />
                {t("saving")}
              </>
            ) : removing ? (
              t("clearOverride")
            ) : (
              t("save")
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * The workspace's quota policy: what the tenant pool may spend, and the ceiling
 * one key or one interactive session may take out of it.
 */
export function WorkspaceQuotaCard({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const t = useTranslations("quota");
  const { isSuperuser } = usePermissions();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const usageQuery = useQuery({
    queryKey: workspaceQuotaKey(workspaceId),
    queryFn: () => workspaceService.getQuotaUsage(workspaceId),
    staleTime: 0
  });

  // Routed like every other admin tab row, so one scope's form is linkable and
  // survives a reload. An unknown `?tab=` falls back to the tenant pool rather
  // than rendering nothing.
  const requested = searchParams?.get(SCOPE_PARAM) ?? "";
  const active = SCOPES.find((scope) => scope === requested) ?? SCOPES[0];
  const policyOf = (scope: QuotaScope) =>
    usageQuery.data?.policy?.find((row) => row.scope === scope) ?? null;

  const tabs: LinkTabItem[] = SCOPES.map((scope) => ({
    key: scope,
    label: t(`scopes.${scope}.tab`),
    href: `${pathname}?${SCOPE_PARAM}=${scope}`,
    // Which scopes carry a row is the one thing tabbing away hides, so it rides
    // on the tab itself instead of only inside the panel it belongs to.
    dot: hasQuotaOverride(policyOf(scope)?.override ?? {})
      ? { tone: "info" as const, label: t("state.overridden") }
      : undefined
  }));

  return (
    <div className="space-y-8">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("usageHeading")}</CardTitle>
          <CardDescription>{t("workspace.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {usageQuery.isPending ? (
            <Skeleton className="h-40 w-full rounded-xl" />
          ) : usageQuery.data ? (
            <QuotaUsagePanel usage={usageQuery.data} />
          ) : (
            <EmptyNote size="sm">{t("loadFailed")}</EmptyNote>
          )}
        </CardContent>
      </Card>

      {/* The heading sits closer to the tab row it owns than the gap that
          separates it from the usage card above — the grouping is the spacing,
          not a rule. */}
      <section className="space-y-3">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium">{t("overrideHeading")}</h3>
            {isSuperuser ? (
              <Badge tone="warning" className="font-normal">
                {t("authority.badge")}
              </Badge>
            ) : null}
          </div>
          <p className="max-w-prose text-xs text-muted-foreground">{t("overrideHint")}</p>
          <p className="max-w-prose text-xs text-muted-foreground">
            {isSuperuser ? t("authority.superuser") : t("authority.admin")}
          </p>
        </div>

        {usageQuery.isPending ? (
          <Skeleton className="h-72 w-full rounded-xl" />
        ) : usageQuery.data ? (
          <>
            <LinkTabs items={tabs} activeKey={active} ariaLabel={t("overrideHeading")} />
            {/* Every scope stays mounted and the inactive ones are hidden: a
                half-typed override on another tab is unsaved work, and
                unmounting it would drop it without a word. */}
            {SCOPES.map((scope) => (
              <div key={scope} hidden={scope !== active}>
                <WorkspaceQuotaScopeCard
                  workspaceId={workspaceId}
                  scope={scope}
                  policy={policyOf(scope)}
                  canRaise={isSuperuser}
                />
              </div>
            ))}
          </>
        ) : (
          <EmptyNote size="sm">{t("loadFailed")}</EmptyNote>
        )}
      </section>
    </div>
  );
}
