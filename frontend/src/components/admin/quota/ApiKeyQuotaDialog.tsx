"use client";

import { useId, type FormEvent } from "react";
import { useTranslations } from "next-intl";

import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { EmptyNote } from "@/components/admin/kit/EmptyNote";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiKeyQuota, useSetApiKeyQuota } from "@/hooks/use-account-api-keys";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import type { AccountApiKey } from "@/types/auth.types";
import { hasQuotaOverride } from "./dimensions";
import { QuotaLimitFields } from "./QuotaLimitFields";
import { QuotaUsagePanel } from "./QuotaUsagePanel";
import { useQuotaDraft } from "./useQuotaDraft";

export interface ApiKeyQuotaDialogProps {
  /** The key under edit; `null` closes the dialog. */
  apiKey: AccountApiKey | null;
  workspaceId: number | null;
  onClose: () => void;
}

/**
 * One key's budgets, and the override written on the key itself.
 *
 * The fields are seeded from the STORED override, never from the effective
 * ceiling: most of an effective number is inherited, so pre-filling with it
 * would turn a glance into a permanent override — and starting blank was worse,
 * because an all-null payload deletes the row, so opening the dialog and
 * pressing the button silently reset limits the dialog never showed.
 */
export function ApiKeyQuotaDialog({
  apiKey,
  workspaceId,
  onClose
}: Readonly<ApiKeyQuotaDialogProps>) {
  const t = useTranslations("quota");
  const fieldPrefix = useId();
  const { isSuperuser } = usePermissions();

  const usageQuery = useApiKeyQuota(apiKey?.id ?? null);
  const setQuota = useSetApiKeyQuota(workspaceId);
  const policy = usageQuery.data?.policy?.find((row) => row.scope === "key") ?? null;
  const form = useQuotaDraft(policy);

  // "Stop overriding" only when there is a row to stop: a key that already
  // inherits must not be offered the removal of an override it never had.
  const removing = form.overridden && !hasQuotaOverride(form.draft);
  const blocked = form.raised.length > 0 && !isSuperuser;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!apiKey) return;
    if (blocked) {
      document.getElementById(`${fieldPrefix}-${form.raised[0]}`)?.focus();
      return;
    }

    setQuota.mutate(
      { id: apiKey.id, limits: form.draft },
      {
        onSuccess: () => {
          notify.success(t("saved"));
          onClose();
        },
        onError: (error) => {
          if (!form.reject(error)) notify.apiError(error, { title: t("errors.saveFailed") });
        }
      }
    );
  };

  return (
    <EntityFormDialog
      open={apiKey !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("apiKey.dialogTitle", { name: apiKey?.name ?? "" })}
      description={t("apiKey.dialogDescription")}
      submitLabel={removing ? t("clearOverride") : t("save")}
      submittingLabel={t("saving")}
      isSubmitting={setQuota.isPending}
      isDirty={form.dirty}
      fieldErrors={form.errors as Record<string, string>}
      contentClassName="!max-w-2xl"
      onSubmit={handleSubmit}
    >
      <div className="space-y-4">
        <section>
          <h3 className="text-sm font-medium">{t("usageHeading")}</h3>
          {usageQuery.isPending ? (
            <div className="mt-2 space-y-2">
              <Skeleton className="h-28 w-full rounded-xl" />
              <Skeleton className="h-28 w-full rounded-xl" />
            </div>
          ) : usageQuery.data ? (
            <div className="mt-2">
              <QuotaUsagePanel usage={usageQuery.data} />
            </div>
          ) : (
            <EmptyNote size="sm">{t("loadFailed")}</EmptyNote>
          )}
        </section>

        <section className="border-t border-border/60 pt-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium">{t("overrideHeading")}</h3>
            <Badge tone={form.overridden ? "info" : "neutral"} className="font-normal">
              {t(form.overridden ? "state.overridden" : "state.inherited")}
            </Badge>
            {isSuperuser ? (
              <Badge tone="warning" className="font-normal">
                {t("authority.badge")}
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 max-w-prose text-xs text-muted-foreground">{t("overrideHint")}</p>
          <p className="mt-0.5 max-w-prose text-xs text-muted-foreground">
            {isSuperuser ? t("authority.keySuperuser") : t("authority.keyAdmin")}
          </p>
          <div className="mt-3">
            <QuotaLimitFields
              idPrefix={fieldPrefix}
              values={form.draft}
              inherited={policy?.inherited}
              raised={form.raised}
              canRaise={isSuperuser}
              errors={form.errors}
              disabled={setQuota.isPending}
              onChange={form.set}
            />
          </div>
        </section>
      </div>
    </EntityFormDialog>
  );
}
