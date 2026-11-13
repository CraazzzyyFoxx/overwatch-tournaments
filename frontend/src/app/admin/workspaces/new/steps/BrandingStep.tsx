"use client";

import { useTranslations } from "next-intl";

import { BrandColorField } from "@/components/admin/workspace-settings/BrandColorField";
import {
  BrandPalettePreview,
  previewPalette
} from "@/components/admin/workspace-settings/BrandPalettePreview";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { Switch } from "@/components/ui/switch";

import { BRAND_SEED_KEYS, type BrandingForm } from "../wizard-model";

const SEED_LABELS: Record<
  (typeof BRAND_SEED_KEYS)[number],
  "primaryAccent" | "secondaryAccent" | "background" | "surface"
> = {
  brand_primary: "primaryAccent",
  brand_secondary: "secondaryAccent",
  brand_background: "background",
  brand_surface: "surface"
};

/**
 * Step 3: the switch and the four seed colours the palette derives from. The
 * six core-palette overrides stay in Settings > Branding: a first setup needs
 * the seeds, not the fine-tuning.
 */
export function BrandingStep({
  value,
  onChange
}: Readonly<{ value: BrandingForm; onChange: (next: BrandingForm) => void }>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.branding");
  const palette = previewPalette(value);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <Label htmlFor="wizard-branding-enabled">{t("siteBranding")}</Label>
          <p className="text-xs text-muted-foreground">{t("siteBrandingHelp")}</p>
        </div>
        <Switch
          id="wizard-branding-enabled"
          checked={value.branding_enabled}
          onCheckedChange={(checked) => onChange({ ...value, branding_enabled: checked })}
        />
      </div>

      <div>
        <h3 className={eyebrowClass("muted")}>{t("seedColours")}</h3>
        <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {BRAND_SEED_KEYS.map((key) => (
            <BrandColorField
              key={key}
              id={`wizard-${key}`}
              label={t(SEED_LABELS[key])}
              value={value[key]}
              onChange={(colour) => onChange({ ...value, [key]: colour })}
            />
          ))}
        </div>
      </div>

      {palette ? (
        <div>
          <h3 className={eyebrowClass("muted")}>{t("preview")}</h3>
          <div className="mt-2">
            <BrandPalettePreview palette={palette} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
