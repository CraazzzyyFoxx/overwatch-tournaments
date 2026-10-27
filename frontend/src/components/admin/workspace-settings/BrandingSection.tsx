"use client";

import { useTranslations } from "next-intl";
import { ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { triggerChevronClass } from "@/components/ui/chevron";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Switch } from "@/components/ui/switch";
import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import type { CssVarMap } from "@/lib/workspace/theme";
import { BrandColorField } from "./BrandColorField";
import { BrandPalettePreview, previewPalette } from "./BrandPalettePreview";
import type { WorkspaceSettingsFormState } from "./fields";
import { WorkspaceSettingsFrame } from "./WorkspaceSettingsFrame";
import { useWorkspaceSettingsForm } from "./useWorkspaceSettingsForm";

/** Two colour fields per line from `sm`; the group title labels the grid. */
const COLOUR_GRID_CLASS = "grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2";

type BrandKey = Extract<keyof WorkspaceSettingsFormState, `brand_${string}`>;

/** One colour field: its form key, its label and blank-state words, and what blank paints. */
interface ColourField {
  key: BrandKey;
  label:
    | "primaryAccent"
    | "secondaryAccent"
    | "background"
    | "surface"
    | "accent"
    | "foreground"
    | "mutedSurface"
    | "border"
    | "focusRing"
    | "destructive";
  blank: "platformDefault" | "sameAsPrimary" | "fromBackground" | "derived";
  fallback: (palette: CssVarMap | null) => string;
}

/**
 * What each blank colour resolves to, painted on its swatch: the derived
 * palette's value once there is one, the platform's own token before.
 * `--aqt-*` hold complete colours, shadcn tokens bare triplets (DESIGN §2).
 */
const full = (palette: CssVarMap | null, token: string) => palette?.[token] ?? `var(${token})`;
const triplet = (palette: CssVarMap | null, token: string) =>
  `hsl(${palette?.[token] ?? `var(${token})`})`;

const SEEDS: readonly ColourField[] = [
  { key: "brand_primary", label: "primaryAccent", blank: "platformDefault", fallback: () => "var(--aqt-teal)" },
  { key: "brand_secondary", label: "secondaryAccent", blank: "sameAsPrimary", fallback: (p) => full(p, "--aqt-violet") },
  { key: "brand_background", label: "background", blank: "platformDefault", fallback: () => "var(--aqt-bg)" },
  { key: "brand_surface", label: "surface", blank: "fromBackground", fallback: (p) => full(p, "--aqt-card") }
];

const OVERRIDES: readonly ColourField[] = [
  { key: "brand_accent", label: "accent", blank: "derived", fallback: (p) => triplet(p, "--accent") },
  { key: "brand_foreground", label: "foreground", blank: "derived", fallback: (p) => full(p, "--aqt-fg") },
  { key: "brand_muted", label: "mutedSurface", blank: "derived", fallback: (p) => triplet(p, "--muted") },
  { key: "brand_border", label: "border", blank: "derived", fallback: (p) => full(p, "--aqt-border") },
  { key: "brand_ring", label: "focusRing", blank: "derived", fallback: (p) => triplet(p, "--ring") },
  { key: "brand_destructive", label: "destructive", blank: "derived", fallback: (p) => triplet(p, "--destructive") }
];

/**
 * The workspace's public-site palette: four seed colours, a preview of what
 * they derive to, and six optional overrides.
 *
 * Every colour stays editable while the palette is off: the switch publishes,
 * it does not unlock, so a palette can be built and judged before it goes
 * live. The overrides start folded unless one is set; most workspaces never
 * need them, and six blank fields read as six things left undone.
 */
export function BrandingSection({ workspaceId }: Readonly<{ workspaceId: number | null }>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.branding");
  const settings = useWorkspaceSettingsForm(workspaceId, "branding");
  const { patch, errors, reveal } = settings;

  return (
    <WorkspaceSettingsFrame workspaceId={workspaceId} settings={settings}>
      {({ form: values, workspace }) => {
        const palette = previewPalette(values);
        const field = ({ key, label, fallback, blank }: ColourField) => (
          <BrandColorField
            key={key}
            id={key.replace("_", "-")}
            label={t(label)}
            value={values[key]}
            onChange={(value) => patch({ [key]: value })}
            onBlur={() => reveal(key)}
            fallback={fallback(palette)}
            placeholder={t(blank)}
            error={errors[key]}
          />
        );
        const overridesSaved = OVERRIDES.some(({ key }) => Boolean(workspace[key]));

        return (
          <>
            <SettingGroup id="palette" title={t("siteBranding")} description={t("siteBrandingHelp")}>
              <SettingRow
                htmlFor="branding-enabled"
                label={t("useCustomPalette")}
                hint={t("useCustomPaletteHelp")}
              >
                <Switch
                  id="branding-enabled"
                  checked={values.branding_enabled}
                  onCheckedChange={(checked) => patch({ branding_enabled: checked })}
                />
              </SettingRow>
            </SettingGroup>

            <SettingGroup id="seeds" title={t("seedColours")} description={t("seedColoursHelp")}>
              <div className={COLOUR_GRID_CLASS}>{SEEDS.map(field)}</div>
            </SettingGroup>

            <SettingGroup id="preview" title={t("preview")}>
              {palette ? (
                <BrandPalettePreview palette={palette} />
              ) : (
                <p className="text-caption text-muted-foreground">{t("previewNeedsSeeds")}</p>
              )}
            </SettingGroup>

            <SettingGroup id="overrides" title={t("corePalette")} description={t("corePaletteHelp")}>
              <Collapsible defaultOpen={overridesSaved}>
                <CollapsibleTrigger asChild>
                  <Button type="button" variant="ghost" size="sm" className="group group/trigger -ml-2">
                    <ChevronDown aria-hidden className={triggerChevronClass} />
                    <span className="group-data-[state=open]:hidden">{t("showOverrides")}</span>
                    <span className="hidden group-data-[state=open]:inline">{t("hideOverrides")}</span>
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent className="pt-3">
                  <div className={COLOUR_GRID_CLASS}>{OVERRIDES.map(field)}</div>
                </CollapsibleContent>
              </Collapsible>
            </SettingGroup>

            <SaveBar
              dirty={settings.dirty}
              summary={settings.summary}
              error={settings.error}
              saving={settings.saving}
              onDiscard={settings.discard}
              onSave={settings.save}
            />
          </>
        );
      }}
    </WorkspaceSettingsFrame>
  );
}
