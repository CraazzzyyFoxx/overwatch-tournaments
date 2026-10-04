"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { CollectionSettingsPanel, useCollectionSettings } from "@/components/admin/CollectionSettingsPanel";
import { formatInterval } from "@/components/kit/format-time";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import type { RankCollectionConfig } from "@/types/admin.types";

const RANK_COLLECTION_KEY = "parser.rank_collection";

const DEFAULTS: RankCollectionConfig = {
  enabled: false,
  interval_seconds: 900,
  batch_size: 50,
  rate_limit_per_minute: 30,
  scope: "registrations_only",
  extra_accounts_per_registration: 0,
  max_consecutive_failures: 5,
  backoff_base_seconds: 60,
  auto_pace: true,
  jitter_fraction: 0.15,
  max_per_tick: null
};

const read = (stored: Partial<RankCollectionConfig> | undefined) => ({ ...DEFAULTS, ...stored });

/**
 * `parser.rank_collection`, grouped by the question each knob answers: whose
 * ranks, how often, how hard OverFast is hit, and when a tag is given up on.
 * min/max are the backend's own bounds (`RankCollectionConfig` in
 * `shared/schemas/settings.py`): past them it answers 422 with nothing this
 * form can show. The OW rank mapping is its own slot (`rank-mapping.tsx`).
 */
export function RankSettingsPanel() {
  const t = useTranslations("collectors.settings.rank");
  const format = useFormatter();
  const ids = useId();
  const settings = useCollectionSettings<RankCollectionConfig>({
    settingKey: RANK_COLLECTION_KEY,
    read,
    invalidateKeys: [adminQueryKeys.rankStatsAll()]
  });

  return (
    <CollectionSettingsPanel settings={settings}>
      {(form, patch) => (
        <>
          <SettingGroup title={t("collection.title")}>
            <SettingRow
              htmlFor={`${ids}-enabled`}
              label={t("collection.enabled")}
              hint={t("collection.enabledHint")}
            >
              <Switch
                id={`${ids}-enabled`}
                checked={form.enabled}
                onCheckedChange={(enabled) => patch({ enabled })}
              />
            </SettingRow>
            <SettingRow
              htmlFor={`${ids}-scope`}
              label={t("collection.scope")}
              hint={t("collection.scopeHint")}
            >
              <Select
                value={form.scope}
                onValueChange={(scope) => patch({ scope: scope as RankCollectionConfig["scope"] })}
              >
                <SelectTrigger id={`${ids}-scope`} className="h-8 w-fit min-w-[230px] max-w-full text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="registrations_only">
                    {t("collection.scopeRegistrations")}
                  </SelectItem>
                  <SelectItem value="all">{t("collection.scopeAll")}</SelectItem>
                </SelectContent>
              </Select>
            </SettingRow>
            <SettingRow
              htmlFor={`${ids}-extra`}
              label={t("collection.extraAccounts")}
              hint={t("collection.extraAccountsHint")}
            >
              <NumberInput
                id={`${ids}-extra`}
                integer
                min={0}
                max={50}
                value={form.extra_accounts_per_registration}
                disabled={form.scope !== "registrations_only"}
                onValueChange={(next) => patch({ extra_accounts_per_registration: next ?? 0 })}
                className="h-8 w-28"
              />
            </SettingRow>
          </SettingGroup>

          <SettingGroup title={t("pace.title")}>
            <SettingRow
              htmlFor={`${ids}-interval`}
              label={t("pace.interval")}
              hint={t("pace.intervalHint", {
                duration: formatInterval(format, form.interval_seconds)
              })}
            >
              <NumberInput
                id={`${ids}-interval`}
                integer
                min={60}
                max={86400}
                value={form.interval_seconds}
                onValueChange={(next) =>
                  patch({ interval_seconds: next ?? DEFAULTS.interval_seconds })
                }
                className="h-8 w-28"
              />
            </SettingRow>
            <SettingRow
              htmlFor={`${ids}-auto-pace`}
              label={t("pace.autoPace")}
              hint={t("pace.autoPaceHint")}
            >
              <Switch
                id={`${ids}-auto-pace`}
                checked={form.auto_pace}
                onCheckedChange={(auto_pace) => patch({ auto_pace })}
              />
            </SettingRow>
            <SettingRow
              htmlFor={`${ids}-max-per-tick`}
              label={t("pace.maxPerTick")}
              hint={t("pace.maxPerTickHint")}
            >
              <NumberInput
                id={`${ids}-max-per-tick`}
                integer
                min={1}
                max={10000}
                placeholder={t("pace.auto")}
                value={form.max_per_tick}
                disabled={!form.auto_pace}
                onValueChange={(max_per_tick) => patch({ max_per_tick })}
                className="h-8 w-28"
              />
            </SettingRow>
            <SettingRow
              htmlFor={`${ids}-jitter`}
              label={t("pace.jitter")}
              hint={t("pace.jitterHint")}
            >
              <NumberInput
                id={`${ids}-jitter`}
                min={0}
                max={1}
                value={form.jitter_fraction}
                onValueChange={(next) => patch({ jitter_fraction: next ?? 0 })}
                className="h-8 w-28"
              />
            </SettingRow>
          </SettingGroup>

          <SettingGroup title={t("limits.title")}>
            <SettingRow
              htmlFor={`${ids}-rate`}
              label={t("limits.rate")}
              hint={t("limits.rateHint")}
            >
              <NumberInput
                id={`${ids}-rate`}
                integer
                min={1}
                max={6000}
                value={form.rate_limit_per_minute}
                onValueChange={(next) =>
                  patch({ rate_limit_per_minute: next ?? DEFAULTS.rate_limit_per_minute })
                }
                className="h-8 w-28"
              />
            </SettingRow>
            <SettingRow
              htmlFor={`${ids}-batch`}
              label={t("limits.batch")}
              hint={t("limits.batchHint")}
            >
              <NumberInput
                id={`${ids}-batch`}
                integer
                min={1}
                max={1000}
                value={form.batch_size}
                onValueChange={(next) => patch({ batch_size: next ?? DEFAULTS.batch_size })}
                className="h-8 w-28"
              />
            </SettingRow>
          </SettingGroup>

          <SettingGroup title={t("failures.title")}>
            <SettingRow
              htmlFor={`${ids}-max-failures`}
              label={t("failures.maxFailures")}
              hint={t("failures.maxFailuresHint")}
            >
              <NumberInput
                id={`${ids}-max-failures`}
                integer
                min={1}
                max={100}
                value={form.max_consecutive_failures}
                onValueChange={(next) =>
                  patch({ max_consecutive_failures: next ?? DEFAULTS.max_consecutive_failures })
                }
                className="h-8 w-28"
              />
            </SettingRow>
            <SettingRow
              htmlFor={`${ids}-backoff`}
              label={t("failures.backoff")}
              hint={t("failures.backoffHint", {
                duration: formatInterval(format, form.backoff_base_seconds)
              })}
            >
              <NumberInput
                id={`${ids}-backoff`}
                integer
                min={1}
                max={86400}
                value={form.backoff_base_seconds}
                onValueChange={(next) =>
                  patch({ backoff_base_seconds: next ?? DEFAULTS.backoff_base_seconds })
                }
                className="h-8 w-28"
              />
            </SettingRow>
          </SettingGroup>
        </>
      )}
    </CollectionSettingsPanel>
  );
}
