"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { CollectionSettingsPanel, useCollectionSettings } from "@/components/admin/CollectionSettingsPanel";
import { formatInterval } from "@/components/kit/format-time";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { NumberInput } from "@/components/ui/number-input";
import { Switch } from "@/components/ui/switch";
import { useFormatter } from "@/lib/datetime/client";
import type { StreamCollectionConfig } from "@/types/admin.types";

const STREAM_COLLECTION_KEY = "stream.collection";

// Mirrors the backend's shipped defaults (`stream.env.example`): polling is OFF
// on a fresh deploy, so filling in the Twitch credentials does not by itself
// start touching Twitch.
const DEFAULTS: StreamCollectionConfig = {
  enabled: false,
  interval_seconds: 60,
  batch_size: 100
};

const read = (stored: Partial<StreamCollectionConfig> | undefined) => ({ ...DEFAULTS, ...stored });

export function StreamSettingsPanel() {
  const t = useTranslations("collectors.settings.streams");
  const format = useFormatter();
  const ids = useId();
  const settings = useCollectionSettings<StreamCollectionConfig>({
    settingKey: STREAM_COLLECTION_KEY,
    read,
    invalidateKeys: [["admin", "streams"]]
  });

  return (
    <CollectionSettingsPanel settings={settings}>
      {(form, patch) => (
        <SettingGroup title={t("title")}>
          <SettingRow htmlFor={`${ids}-enabled`} label={t("enabled")} hint={t("enabledHint")}>
            <Switch
              id={`${ids}-enabled`}
              checked={form.enabled}
              onCheckedChange={(enabled) => patch({ enabled })}
            />
          </SettingRow>
          <SettingRow
            htmlFor={`${ids}-interval`}
            label={t("interval")}
            hint={t("intervalHint", {
              duration: formatInterval(format, form.interval_seconds)
            })}
          >
            {/* min/max are the backend's own bounds: past them it answers 422
                with nothing this form can show. */}
            <NumberInput
              id={`${ids}-interval`}
              integer
              min={30}
              max={3600}
              value={form.interval_seconds}
              onValueChange={(next) => patch({ interval_seconds: next ?? DEFAULTS.interval_seconds })}
              className="h-8 w-28"
            />
          </SettingRow>
          <SettingRow htmlFor={`${ids}-batch`} label={t("batch")} hint={t("batchHint")}>
            <NumberInput
              id={`${ids}-batch`}
              integer
              min={1}
              max={100}
              value={form.batch_size}
              onValueChange={(next) => patch({ batch_size: next ?? DEFAULTS.batch_size })}
              className="h-8 w-28"
            />
          </SettingRow>
        </SettingGroup>
      )}
    </CollectionSettingsPanel>
  );
}
