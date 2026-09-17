"use client";

import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { EmptyNote } from "@/components/admin/kit/EmptyNote";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { notify } from "@/lib/notify";
import { parseQuotaAboveInherited } from "@/lib/quota";
import workspaceService from "@/services/workspace.service";
import type { QuotaDimension, QuotaScope, QuotaScopeUsage } from "@/types/auth.types";
import { EMPTY_QUOTA_LIMITS, hasQuotaOverride, type QuotaLimitsDraft } from "./dimensions";
import { QuotaLimitFields } from "./QuotaLimitFields";
import { QuotaUsagePanel } from "./QuotaUsagePanel";

/** In table order: the tenant pool first, then the two per-principal buckets. */
const SCOPES: readonly QuotaScope[] = ["workspace", "key", "session"];

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
  effective
}: Readonly<{ workspaceId: number; scope: QuotaScope; effective: QuotaScopeUsage | null }>) {
  const t = useTranslations("quota");
  const fieldPrefix = useId();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<QuotaLimitsDraft>(EMPTY_QUOTA_LIMITS);
  const [errors, setErrors] = useState<Partial<Record<QuotaDimension, string>>>({});

  const save = useMutation({
    mutationFn: (limits: QuotaLimitsDraft) => workspaceService.setQuota(workspaceId, scope, limits),
    onSuccess: async () => {
      notify.success(t("saved"));
      await queryClient.invalidateQueries({ queryKey: workspaceQuotaKey(workspaceId) });
    },
    onError: (error) => {
      const rejection = parseQuotaAboveInherited(error);
      if (!rejection) {
        notify.apiError(error, { title: t("errors.saveFailed") });
        return;
      }
      // The refusal names one dimension of one scope. Marking that input is the
      // only rendering an admin can act on: "lower this number, or ask a
      // superuser to raise the plan".
      const dimension = t(`dimensions.${rejection.dimension}.label`);
      setErrors({
        [rejection.dimension]:
          rejection.limit === null
            ? t("errors.aboveInheritedUnlimited", { dimension })
            : t("errors.aboveInherited", {
                dimension,
                limit: rejection.limit,
                requested: rejection.requested ?? draft[rejection.dimension] ?? 0
              })
      });
    }
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t(`scopes.${scope}.label`)}</CardTitle>
        <CardDescription>{t(`scopes.${scope}.hint`)}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <QuotaLimitFields
          idPrefix={fieldPrefix}
          values={draft}
          effective={effective}
          errors={errors}
          disabled={save.isPending}
          onChange={(dimension, value) => {
            setDraft((current) => ({ ...current, [dimension]: value }));
            setErrors((current) =>
              current[dimension] ? { ...current, [dimension]: undefined } : current
            );
          }}
        />
        <div className="flex justify-end">
          <Button
            type="button"
            size="sm"
            disabled={save.isPending}
            onClick={() => {
              setErrors({});
              save.mutate(draft);
            }}
          >
            {save.isPending ? (
              <>
                <LoaderCircle aria-hidden className="size-4 animate-spin" />
                {t("saving")}
              </>
            ) : hasQuotaOverride(draft) ? (
              t("save")
            ) : (
              t("clearOverride")
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
  const usageQuery = useQuery({
    queryKey: workspaceQuotaKey(workspaceId),
    queryFn: () => workspaceService.getQuotaUsage(workspaceId),
    staleTime: 0
  });

  const workspaceScope =
    usageQuery.data?.scopes.find((scope) => scope.scope === "workspace") ?? null;

  return (
    <div className="space-y-6">
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

      <div>
        <h3 className="text-sm font-medium">{t("overrideHeading")}</h3>
        <p className="mt-0.5 max-w-prose text-xs text-muted-foreground">{t("overrideHint")}</p>
      </div>

      {SCOPES.map((scope) => (
        <WorkspaceQuotaScopeCard
          key={scope}
          workspaceId={workspaceId}
          scope={scope}
          effective={scope === "workspace" ? workspaceScope : null}
        />
      ))}
    </div>
  );
}
