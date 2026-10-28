"use client";

import { createElement, useId, useMemo, useState } from "react";
import { Pipette } from "lucide-react";
import { useTranslations } from "next-intl";

import StatusMetaBadge from "@/components/status/StatusMetaBadge";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Button } from "@/components/ui/button";
import { ColorSwatch } from "@/components/ui/color-swatch";
import { Combobox, ComboboxCheck } from "@/components/ui/combobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { getStatusIcon, STATUS_ICON_OPTIONS } from "@/lib/registration/status-icons";
import { cn } from "@/lib/utils";
import type { StatusScope } from "@/types/registration.types";

export type StatusFormState = {
  scope: StatusScope;
  icon_slug: string;
  icon_color: string;
  name: string;
  description: string;
  excludes_from_balancer: boolean;
  excludes_from_ready: boolean;
};

export const EMPTY_STATUS_FORM: StatusFormState = {
  scope: "registration",
  icon_slug: "",
  icon_color: "",
  name: "",
  description: "",
  excludes_from_balancer: false,
  excludes_from_ready: false
};

// Swatch palette offered to the admin who is choosing a status's `icon_color`,
// which is persisted per status row. These hexes are the picker's *content*, not
// this page's chrome, so they are exempt from the design-token rule — a themed
// var here would change what gets written to the database when the theme changes.
const STATUS_COLOR_PRESETS = [
  "#94a3b8",
  "#64748b",
  "#ef4444",
  "#f97316",
  "#f59e0b",
  "#eab308",
  "#84cc16",
  "#22c55e",
  "#10b981",
  "#14b8a6",
  "#06b6d4",
  "#38bdf8",
  "#3b82f6",
  "#6366f1",
  "#8b5cf6",
  "#ec4899"
];

/** A hex the admin may have typed without its `#`. */
function normalizeHexColor(value: string): string {
  const normalized = value.trim();
  if (!normalized) {
    return "";
  }
  return normalized.startsWith("#") ? normalized : `#${normalized}`;
}

function StatusColorPicker({
  value,
  onChange
}: Readonly<{
  value: string;
  onChange: (next: string) => void;
}>) {
  const t = useTranslations("adminSettings.statuses.form");
  const [open, setOpen] = useState(false);
  const triggerId = useId();
  const hexId = useId();
  // The swatch previews need a literal hex; the DOM API cannot take a CSS
  // variable. Data-shaped, not chrome — exempt.
  const normalizedValue = normalizeHexColor(value) || "#94a3b8";

  return (
    <div className="space-y-2">
      <Label htmlFor={triggerId}>{t("iconColor")}</Label>
      <Popover open={open} onOpenChange={setOpen} modal={false}>
        <PopoverTrigger asChild>
          <Button
            id={triggerId}
            variant="outline"
            className="w-full justify-between"
            aria-haspopup="dialog"
            aria-expanded={open}
          >
            <span className="flex min-w-0 items-center gap-3">
              <span
                className="size-5 shrink-0 rounded-md border border-border"
                style={{ backgroundColor: normalizedValue }}
                aria-hidden
              />
              <span className={cn("truncate text-xs", normalizeHexColor(value) && "font-mono")}>
                {normalizeHexColor(value) || t("default")}
              </span>
            </span>
            <Pipette className="ml-2 size-4 shrink-0 opacity-60" aria-hidden />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="z-[60] w-[var(--radix-popover-trigger-width)] min-w-[var(--radix-popover-trigger-width)] space-y-4"
        >
          <div className="space-y-2">
            <p className={eyebrowClass("muted")} id={`${triggerId}-presets`}>
              {t("presets")}
            </p>
            <div
              className="flex flex-wrap gap-2"
              role="group"
              aria-labelledby={`${triggerId}-presets`}
            >
              {STATUS_COLOR_PRESETS.map((color) => {
                const selected = normalizeHexColor(value).toLowerCase() === color.toLowerCase();
                return (
                  <Button
                    key={color}
                    type="button"
                    variant="outline"
                    size="icon"
                    className={cn(selected && "ring-2 ring-ring ring-offset-2 ring-offset-background")}
                    style={{ backgroundColor: color }}
                    onClick={() => onChange(color)}
                    aria-pressed={selected}
                    aria-label={t("usePreset", { color })}
                  />
                );
              })}
            </div>
          </div>

          <div className="space-y-2">
            <p className={eyebrowClass("muted")}>{t("custom")}</p>
            <div className="flex items-center gap-2">
              <ColorSwatch
                value={normalizeHexColor(value)}
                fallback={normalizedValue}
                label={t("pickCustom")}
                onValueChange={onChange}
              />
              <Label htmlFor={hexId} className="sr-only">
                {t("hexCode")}
              </Label>
              {/* Placeholder shows the expected hex literal — it is example
                  input for a hex-typed field, not a colour this UI paints with. */}
              <Input
                id={hexId}
                value={value}
                onChange={(event) => onChange(normalizeHexColor(event.target.value))}
                placeholder="#38bdf8"
                className="font-mono"
              />
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

/**
 * Create/edit body for one registration- or balancer-scope status.
 *
 * Extracted from the old `/admin/balancer` page so the statuses settings
 * section keeps the icon and colour pickers verbatim while the surrounding
 * screen becomes a single `DataTable`.
 */
export function StatusForm({
  value,
  onChange,
  disableScope = false,
  isBuiltin = false
}: Readonly<{
  value: StatusFormState;
  onChange: (next: StatusFormState) => void;
  disableScope?: boolean;
  /** True when editing a builtin-status override: pool-inclusion is fixed by the system, not admin-editable. */
  isBuiltin?: boolean;
}>) {
  const t = useTranslations("adminSettings.statuses.form");
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  // Two dialogs mount this form, so the field ids have to be per-instance.
  const fieldId = useId();
  const previewMeta = useMemo(
    () => ({
      value: value.name || "preview",
      scope: value.scope,
      is_builtin: false,
      kind: "custom" as const,
      is_override: false,
      can_edit: true,
      can_delete: true,
      can_reset: false,
      icon_slug: value.icon_slug || "BadgeHelp",
      icon_color: value.icon_color || null,
      name: value.name || t("preview"),
      description: value.description || null,
      excludes_from_balancer: value.excludes_from_balancer,
      excludes_from_ready: value.excludes_from_ready
    }),
    [t, value]
  );
  const selectedIconSlug = value.icon_slug || "BadgeHelp";
  // `icon_color` is workspace data, not a semantic tone, so it stays an inline
  // style. The slug beside it carries the meaning; the icon is decoration.
  const selectedIcon = createElement(getStatusIcon(selectedIconSlug), {
    className: "size-4",
    "aria-hidden": true,
    style: value.icon_color ? { color: value.icon_color } : undefined
  });

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor={`${fieldId}-scope`}>{t("scope")}</Label>
          <Select
            value={value.scope}
            onValueChange={(nextScope) => onChange({ ...value, scope: nextScope as StatusScope })}
          >
            <SelectTrigger id={`${fieldId}-scope`} disabled={disableScope}>
              <SelectValue placeholder={t("selectScope")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="registration">{t("registration")}</SelectItem>
              <SelectItem value="balancer">{t("balancer")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${fieldId}-name`}>{t("name")}</Label>
          <Input
            id={`${fieldId}-name`}
            value={value.name}
            onChange={(event) => onChange({ ...value, name: event.target.value })}
            placeholder={t("namePlaceholder")}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${fieldId}-icon`}>{t("icon")}</Label>
          <Combobox
            id={`${fieldId}-icon`}
            open={iconPickerOpen}
            onOpenChange={setIconPickerOpen}
            label={
              <span className="flex min-w-0 items-center gap-2">
                {selectedIcon}
                <span className="truncate">{selectedIconSlug}</span>
              </span>
            }
            labelTitle={selectedIconSlug}
            searchPlaceholder={t("searchIcons")}
            emptyMessage={t("noIconMatches")}
          >
            <CommandGroup>
              {STATUS_ICON_OPTIONS.map(({ slug, Icon }) => (
                <CommandItem
                  key={slug}
                  value={slug}
                  onSelect={(nextSlug) => {
                    onChange({ ...value, icon_slug: nextSlug });
                    setIconPickerOpen(false);
                  }}
                >
                  <Icon
                    className="size-4"
                    aria-hidden
                    style={value.icon_color ? { color: value.icon_color } : undefined}
                  />
                  <span className="min-w-0 flex-1 truncate">{slug}</span>
                  <ComboboxCheck selected={value.icon_slug === slug} />
                </CommandItem>
              ))}
            </CommandGroup>
          </Combobox>
        </div>
        <StatusColorPicker
          value={value.icon_color}
          onChange={(nextColor) => onChange({ ...value, icon_color: nextColor })}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor={`${fieldId}-description`}>{t("description")}</Label>
        <Textarea
          id={`${fieldId}-description`}
          value={value.description}
          onChange={(event) => onChange({ ...value, description: event.target.value })}
          placeholder={t("descriptionPlaceholder")}
        />
      </div>
      {value.scope === "balancer" && !isBuiltin ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5">
          <div className="space-y-0.5">
            <Label htmlFor={`${fieldId}-excludes`}>{t("excludesPool")}</Label>
            <p className="text-xs text-muted-foreground">{t("excludesPoolHelp")}</p>
          </div>
          <Switch
            id={`${fieldId}-excludes`}
            checked={value.excludes_from_balancer}
            onCheckedChange={(checked) => onChange({ ...value, excludes_from_balancer: checked })}
          />
        </div>
      ) : null}
      {value.scope === "balancer" && !isBuiltin ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5">
          <div className="space-y-0.5">
            <Label htmlFor={`${fieldId}-blocks-ready`}>{t("blocksReady")}</Label>
            <p className="text-xs text-muted-foreground">{t("blocksReadyHelp")}</p>
          </div>
          <Switch
            id={`${fieldId}-blocks-ready`}
            checked={value.excludes_from_ready}
            onCheckedChange={(checked) => onChange({ ...value, excludes_from_ready: checked })}
          />
        </div>
      ) : null}
      <div className="space-y-2">
        <p className="text-sm font-medium">{t("preview")}</p>
        <StatusMetaBadge meta={previewMeta} fallbackValue="preview" />
      </div>
    </div>
  );
}
