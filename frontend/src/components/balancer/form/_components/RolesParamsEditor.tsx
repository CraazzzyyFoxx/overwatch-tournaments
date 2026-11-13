"use client";

import Link from "next/link";
import { useId } from "react";
import { ArrowRight, Check } from "lucide-react";
import { useTranslations } from "next-intl";

import { SettingRow } from "@/components/kit/SettingRow";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { FilterChip } from "@craazzzyyfoxx/admin-kit/ui/filter-chip";
import { Input } from "@craazzzyyfoxx/admin-kit/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@craazzzyyfoxx/admin-kit/ui/select";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { registrationRoles, type RoleOntology } from "@/lib/roster/ontology";
import type { RolesParams } from "@/types/forms.types";

/** One workspace `PlayerSubRole` row, with the id its chip is keyed by. */
interface CatalogEntry {
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
    max_roles: raw.max_roles ?? null,
    top_heroes: topHeroes
  };
}

/**
 * The params with the single-role rule switched on or off. One role means no flex, no second role to require and
 * no all-roles expansion, so turning it on resets exactly those settings; turning it off lifts only the cap
 * (what was reset stays, the organizer re-enables it).
 */
export function withSingleRole(params: RolesParams, single: boolean): RolesParams {
  if (!single) return { ...params, max_roles: null };
  return {
    ...params,
    max_roles: 1,
    flex_allowed: false,
    flex_mode: "optional",
    additional_required: false
  };
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
  ontology,
  catalogLoading = false
}: Readonly<{
  params: RolesParams;
  onChange: (next: RolesParams) => void;
  catalog: SubroleCatalogByRole;
  /** The tournament owner's role dictionary: which roles carry a sub-role row, and their names. `null` while it loads. */
  ontology: RoleOntology | null;
  catalogLoading?: boolean;
}>) {
  const t = useTranslations("registrationFormAdmin.roles");
  const tSub = useTranslations("registrationFormAdmin.subroles");
  const slotLabel = useSlotLabel(ontology);
  const ids = useId();

  return (
    <div className="grid gap-4">
      <div className="grid gap-3">
        <div>
          <SettingRow htmlFor={`${ids}-primary`} label={t("primaryRequired")}>
            <Switch
              id={`${ids}-primary`}
              checked={params.primary_required}
              onCheckedChange={(primary_required) => onChange({ ...params, primary_required })}
            />
          </SettingRow>
          <SettingRow htmlFor={`${ids}-additional`} label={t("additionalRequired")}>
            <Switch
              id={`${ids}-additional`}
              checked={params.additional_required}
              disabled={params.max_roles === 1}
              onCheckedChange={(additional_required) => onChange({ ...params, additional_required })}
            />
          </SettingRow>
          <SettingRow htmlFor={`${ids}-single`} label={t("singleRole")} hint={t("singleRoleHint")}>
            <Switch
              id={`${ids}-single`}
              checked={params.max_roles === 1}
              onCheckedChange={(single) => onChange(withSingleRole(params, single))}
            />
          </SettingRow>
          <SettingRow htmlFor={`${ids}-flex`} label={t("flexAllowed")} hint={t("flexAllowedHint")}>
            <Switch
              id={`${ids}-flex`}
              checked={params.flex_allowed}
              disabled={params.max_roles === 1}
              onCheckedChange={(flex_allowed) => onChange({ ...params, flex_allowed })}
            />
          </SettingRow>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${ids}-mode`} className="text-xs">
            {t("flexMode")}
          </Label>
          <Select
            disabled={params.max_roles === 1}
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

        {registrationRoles(ontology).map((role) => {
          const options = catalog[role.code] ?? [];
          const selection = params.subroles[role.code];
          const allSlugs = options.map((option) => option.slug);
          const roleLabel = slotLabel(role.code);

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
                    <FilterChip
                      key={option.id}
                      active={offered}
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
                    >
                      {offered && <Check className="size-3" aria-hidden />}
                      {option.label}
                    </FilterChip>
                  );
                })}
                {options.length === 0 &&
                  (catalogLoading ? (
                    <div role="status" className="flex gap-1.5">
                      <span className="sr-only">{tSub("loading")}</span>
                      {[0, 1, 2].map((chip) => (
                        <Skeleton key={chip} aria-hidden className="h-8 w-16 rounded-lg" />
                      ))}
                    </div>
                  ) : (
                    <span className="text-xs text-muted-foreground">
                      {tSub("emptyRole", { role: roleLabel })}
                    </span>
                  ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="grid gap-3 border-t pt-4">
        <div>
          <SettingRow htmlFor={`${ids}-heroes`} label={t("topHeroesEnabled")} hint={t("topHeroesHint")}>
            <Switch
              id={`${ids}-heroes`}
              checked={params.top_heroes.enabled}
              onCheckedChange={(enabled) =>
                onChange({ ...params, top_heroes: { ...params.top_heroes, enabled } })
              }
            />
          </SettingRow>
          <SettingRow htmlFor={`${ids}-heroes-required`} label={t("topHeroesRequired")}>
            <Switch
              id={`${ids}-heroes-required`}
              checked={params.top_heroes.required}
              disabled={!params.top_heroes.enabled}
              onCheckedChange={(required) =>
                onChange({ ...params, top_heroes: { ...params.top_heroes, required } })
              }
            />
          </SettingRow>
        </div>
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
