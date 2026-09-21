"use client";

import Link from "next/link";
import { useId } from "react";
import { ArrowRight, Check } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ROLES, ROLE_LABELS } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { RolesParams } from "@/types/forms.types";

/** One workspace `PlayerSubRole` row, with the id its chip is keyed by. */
export interface CatalogEntry {
  id: number;
  slug: string;
  label: string;
}

export type SubroleCatalogByRole = Record<string, CatalogEntry[]>;

const FLEX_MODES = ["optional", "all_roles", "forced"] as const;

const DEFAULT_TOP_HEROES = { enabled: false, required: false, max: 5 };

/**
 * The `roles` builtin's `params`, read back with the catalog's defaults.
 *
 * `params` is an untyped bag on the wire because the schema stores one shape
 * per builtin; this is the single place that gives it the `RolesParams` shape,
 * so a form saved before a field existed still opens with the server's default
 * rather than `undefined` reaching a `<Switch>`.
 */
export function rolesParamsOf(params: Record<string, unknown>): RolesParams {
  const raw = params as Partial<RolesParams>;
  const topHeroes = { ...DEFAULT_TOP_HEROES, ...(raw.top_heroes ?? {}) };
  return {
    primary_required: raw.primary_required ?? true,
    additional_required: raw.additional_required ?? false,
    flex_allowed: raw.flex_allowed ?? true,
    flex_mode: raw.flex_mode ?? "optional",
    subroles: raw.subroles ?? {},
    top_heroes: topHeroes
  };
}

/**
 * One switch setting: what it is and why on the left, the control on the right.
 *
 * Shared with `FieldEditor` — the question panel and this params editor are one
 * surface to the organizer, and two copies of the row is how their label sizes
 * and hint spacing start to drift.
 */
export function SwitchRow({
  id,
  label,
  hint,
  checked,
  onCheckedChange,
  disabled = false
}: Readonly<{
  id: string;
  label: string;
  hint?: string;
  checked: boolean;
  onCheckedChange: (next: boolean) => void;
  disabled?: boolean;
}>) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <Label htmlFor={id} className="text-xs">
          {label}
        </Label>
        {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} />
    </div>
  );
}

/**
 * Everything the `roles` builtin decides: role composition, the flex rule, the
 * sub-roles this tournament offers and the top-heroes pickers.
 *
 * All four used to be separate screens' worth of state — two built-in field
 * rows, a Subroles tab and a hidden `max_heroes` — even though they are one
 * question's settings and the server validates them as one `RolesParams`.
 *
 * The sub-role CATALOG is workspace-global and managed in workspace settings;
 * a form only chooses which catalog entries it offers, and a role with no
 * explicit selection offers all of them.
 */
export function RolesParamsEditor({
  params,
  onChange,
  catalog,
  catalogLoading = false
}: Readonly<{
  params: RolesParams;
  onChange: (next: RolesParams) => void;
  catalog: SubroleCatalogByRole;
  catalogLoading?: boolean;
}>) {
  const t = useTranslations("registrationFormAdmin.roles");
  const tSub = useTranslations("registrationFormAdmin.subroles");
  const ids = useId();

  return (
    <div className="grid gap-4">
      <div className="grid gap-3">
        <SwitchRow
          id={`${ids}-primary`}
          label={t("primaryRequired")}
          checked={params.primary_required}
          onCheckedChange={(primary_required) => onChange({ ...params, primary_required })}
        />
        <SwitchRow
          id={`${ids}-additional`}
          label={t("additionalRequired")}
          checked={params.additional_required}
          onCheckedChange={(additional_required) => onChange({ ...params, additional_required })}
        />
        <SwitchRow
          id={`${ids}-flex`}
          label={t("flexAllowed")}
          hint={t("flexAllowedHint")}
          checked={params.flex_allowed}
          onCheckedChange={(flex_allowed) => onChange({ ...params, flex_allowed })}
        />
        <div className="grid gap-1.5">
          <Label htmlFor={`${ids}-mode`} className="text-xs">
            {t("flexMode")}
          </Label>
          <Select
            value={params.flex_mode}
            onValueChange={(value) =>
              onChange({ ...params, flex_mode: value as RolesParams["flex_mode"] })
            }
          >
            <SelectTrigger id={`${ids}-mode`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FLEX_MODES.map((mode) => (
                <SelectItem key={mode} value={mode}>
                  {t(`mode_${mode}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">{t(`modeHint_${params.flex_mode}`)}</p>
        </div>
      </div>

      <div className="grid gap-3 border-t pt-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h5 className="text-sm font-medium">{tSub("title")}</h5>
            <p className="text-xs text-muted-foreground">{tSub("description")}</p>
          </div>
          <Button variant="outline" size="sm" asChild className="shrink-0">
            <Link href="/admin/settings/sub-roles">
              {tSub("editCatalog")}
              <ArrowRight className="ml-2 size-3.5" aria-hidden />
            </Link>
          </Button>
        </div>

        {ROLES.map((role) => {
          const options = catalog[role.code] ?? [];
          const selection = params.subroles[role.code];
          const allSlugs = options.map((option) => option.slug);
          const roleLabel = ROLE_LABELS[role.code] ?? role.display;

          return (
            <div key={role.code} className="grid gap-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium">{roleLabel}</span>
                {options.length > 0 && selection !== undefined && (
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {tSub("offeredCount", {
                      count: selection.filter((slug) => allSlugs.includes(slug)).length,
                      total: options.length
                    })}
                  </span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {options.map((option) => {
                  const offered = selection === undefined || selection.includes(option.slug);
                  return (
                    <button
                      key={option.id}
                      type="button"
                      aria-pressed={offered}
                      title={offered ? tSub("chipOffered") : tSub("chipHidden")}
                      onClick={() => {
                        const effective = selection ?? allSlugs;
                        const next = offered
                          ? effective.filter((slug) => slug !== option.slug)
                          : [...effective, option.slug];
                        onChange({
                          ...params,
                          subroles: { ...params.subroles, [role.code]: next }
                        });
                      }}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                        offered
                          ? "border-primary/30 bg-primary/10 text-primary"
                          : "border-border/60 text-muted-foreground hover:text-foreground"
                      )}
                    >
                      {offered && <Check className="size-3" aria-hidden />}
                      {option.label}
                    </button>
                  );
                })}
                {options.length === 0 && (
                  <span className="text-xs text-muted-foreground">
                    {catalogLoading ? tSub("loading") : tSub("emptyRole", { role: roleLabel })}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="grid gap-3 border-t pt-4">
        <SwitchRow
          id={`${ids}-heroes`}
          label={t("topHeroesEnabled")}
          hint={t("topHeroesHint")}
          checked={params.top_heroes.enabled}
          onCheckedChange={(enabled) =>
            onChange({ ...params, top_heroes: { ...params.top_heroes, enabled } })
          }
        />
        <SwitchRow
          id={`${ids}-heroes-required`}
          label={t("topHeroesRequired")}
          checked={params.top_heroes.required}
          disabled={!params.top_heroes.enabled}
          onCheckedChange={(required) =>
            onChange({ ...params, top_heroes: { ...params.top_heroes, required } })
          }
        />
        <div className="grid gap-1.5">
          <Label htmlFor={`${ids}-heroes-max`} className="text-xs">
            {t("topHeroesMax")}
          </Label>
          <Input
            id={`${ids}-heroes-max`}
            type="number"
            min={1}
            max={20}
            className="w-24"
            disabled={!params.top_heroes.enabled}
            value={params.top_heroes.max}
            onChange={(event) => {
              // Clamped here rather than reported: the server's bound is 1..20
              // and a 0 typed into a spinner is a slip, not a request.
              const parsed = Number(event.target.value);
              const max = Number.isFinite(parsed) ? Math.min(20, Math.max(1, parsed)) : 5;
              onChange({ ...params, top_heroes: { ...params.top_heroes, max } });
            }}
          />
        </div>
      </div>
    </div>
  );
}
