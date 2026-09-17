"use client";

import { useId, useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";

import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { EmptyNote } from "@/components/admin/kit/EmptyNote";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiKeyQuota, useSetApiKeyQuota } from "@/hooks/use-account-api-keys";
import { notify } from "@/lib/notify";
import { parseQuotaAboveInherited } from "@/lib/quota";
import type { AccountApiKey, QuotaDimension } from "@/types/auth.types";
import { EMPTY_QUOTA_LIMITS, hasQuotaOverride, type QuotaLimitsDraft } from "./dimensions";
import { QuotaLimitFields } from "./QuotaLimitFields";
import { QuotaUsagePanel } from "./QuotaUsagePanel";

export interface ApiKeyQuotaDialogProps {
  /** The key under edit; `null` closes the dialog. */
  apiKey: AccountApiKey | null;
  workspaceId: number | null;
  onClose: () => void;
}

/**
 * One key's budgets, and the override written on the key itself.
 *
 * Mounted keyed by the key's id, so a fresh instance (and an empty draft) is
 * what every open starts from: the read contract reports *effective* ceilings,
 * not the stored override row, and pre-filling with an inherited value would
 * turn a glance into a permanent override on the next save.
 */
export function ApiKeyQuotaDialog({
  apiKey,
  workspaceId,
  onClose
}: Readonly<ApiKeyQuotaDialogProps>) {
  const t = useTranslations("quota");
  const fieldPrefix = useId();
  const [draft, setDraft] = useState<QuotaLimitsDraft>(EMPTY_QUOTA_LIMITS);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<QuotaDimension, string>>>({});

  const usageQuery = useApiKeyQuota(apiKey?.id ?? null);
  const setQuota = useSetApiKeyQuota(workspaceId);

  const keyScope = usageQuery.data?.scopes.find((scope) => scope.scope === "key") ?? null;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!apiKey) return;
    setFieldErrors({});

    setQuota.mutate(
      { id: apiKey.id, limits: draft },
      {
        onSuccess: () => {
          notify.success(t("saved"));
          onClose();
        },
        onError: (error) => {
          const rejection = parseQuotaAboveInherited(error);
          if (!rejection) {
            notify.apiError(error, { title: t("errors.saveFailed") });
            return;
          }
          // The rejection names one dimension, so it belongs on that input —
          // a toast would leave the admin guessing which of five numbers the
          // server refused, and why.
          const dimension = t(`dimensions.${rejection.dimension}.label`);
          setFieldErrors({
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
      submitLabel={hasQuotaOverride(draft) ? t("save") : t("clearOverride")}
      submittingLabel={t("saving")}
      isSubmitting={setQuota.isPending}
      isDirty={hasQuotaOverride(draft)}
      fieldErrors={fieldErrors as Record<string, string>}
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
          <h3 className="text-sm font-medium">{t("overrideHeading")}</h3>
          <p className="mt-0.5 max-w-prose text-xs text-muted-foreground">
            {t("overrideHint")}
          </p>
          <div className="mt-3">
            <QuotaLimitFields
              idPrefix={fieldPrefix}
              values={draft}
              effective={keyScope}
              errors={fieldErrors}
              disabled={setQuota.isPending}
              onChange={(dimension, value) =>
                setDraft((current) => ({ ...current, [dimension]: value }))
              }
            />
          </div>
        </section>
      </div>
    </EntityFormDialog>
  );
}
