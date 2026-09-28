"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { PickBanKind, PickBanParamSpec } from "@/types/tournament.types";

import { CatalogueChips, CataloguePicker, type CatalogueItem } from "../CataloguePicker";

/** Radix rejects an empty `<SelectItem>` value, and `null` is a real choice. */
const ANY_VALUE = "__any__";

/**
 * The parameter form of one leaf or constraint, built from the engine's own
 * specs (§6 `ParamSpec`).
 *
 * Nothing about any individual leaf is written here: a leaf the backend adds
 * tomorrow gets a working form today, because the spec says what its params
 * are. That is the whole reason the catalog ships specs rather than a list of
 * names — the achievement editor's hand-written field set drifted eight nodes
 * behind its engine, and this one cannot.
 */
export function ParamFields({
  specs,
  params,
  setParam,
  controlName,
  kind,
  groups,
  catalogue,
  disabled,
}: Readonly<{
  specs: PickBanParamSpec[];
  params: Record<string, unknown>;
  setParam: (key: string, value: unknown) => void;
  controlName: (field: string) => string;
  kind: PickBanKind;
  /** Group vocabulary of this kind: hero classes, or map gamemodes. */
  groups: string[];
  catalogue: CatalogueItem[];
  disabled?: boolean;
}>) {
  const t = useTranslations("pickBan.rules");
  const catalogueById = useMemo(
    () => new Map(catalogue.map((option) => [option.id, option])),
    [catalogue]
  );

  const paramLabel = (name: string) => {
    const key = `param.${name}` as "param.op";
    return t.has(key) ? t(key) : name;
  };
  const valueLabel = (name: string, value: string) => {
    const key = `paramValue.${name}.${value}` as "paramValue.by.self";
    return t.has(key) ? t(key) : value;
  };

  if (specs.length === 0) {
    return <p className="text-xs text-muted-foreground">{t("noParams")}</p>;
  }

  return (
    <div className="space-y-1.5 text-xs">
      {specs.map((spec) => {
        const label = paramLabel(spec.name);
        const name = controlName(label);
        const value = params[spec.name];

        if (spec.kind === "bool") {
          return (
            <div key={spec.name} className="flex items-center gap-2">
              <Switch
                checked={value === true}
                disabled={disabled}
                aria-label={name}
                onCheckedChange={(checked) => setParam(spec.name, checked)}
              />
              <span className="text-muted-foreground">{label}</span>
            </div>
          );
        }

        if (spec.kind === "int") {
          return (
            <NumberInput
              key={spec.name}
              className="h-7 text-xs"
              aria-label={name}
              integer
              min={spec.min ?? undefined}
              max={spec.max ?? undefined}
              disabled={disabled}
              placeholder={label}
              value={typeof value === "number" ? value : null}
              onValueChange={(next) => setParam(spec.name, next ?? (spec.nullable ? null : spec.min ?? 0))}
            />
          );
        }

        if (spec.kind === "enum" || spec.kind === "group") {
          const options = spec.kind === "group" ? groups : spec.values ?? [];
          const current = typeof value === "string" ? value : spec.nullable ? ANY_VALUE : "";
          return (
            <Select
              key={spec.name}
              value={current}
              disabled={disabled}
              onValueChange={(next) => setParam(spec.name, next === ANY_VALUE ? null : next)}
            >
              <SelectTrigger className="h-7 text-xs" aria-label={name}>
                <SelectValue placeholder={label} />
              </SelectTrigger>
              <SelectContent>
                {spec.nullable ? <SelectItem value={ANY_VALUE}>{t("anyValue")}</SelectItem> : null}
                {options.map((option) => (
                  <SelectItem key={option} value={option}>
                    {spec.kind === "group" ? option : valueLabel(spec.name, option)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          );
        }

        if (spec.kind === "group_list") {
          const selected = Array.isArray(value) ? (value as string[]) : [];
          return (
            <fieldset key={spec.name} className="flex flex-wrap gap-x-3 gap-y-1">
              <legend className="text-muted-foreground">{label}</legend>
              {groups.map((group) => (
                <Label key={group} className="flex items-center gap-1.5 font-normal">
                  <Checkbox
                    checked={selected.includes(group)}
                    disabled={disabled}
                    onCheckedChange={(checked) =>
                      setParam(
                        spec.name,
                        checked
                          ? [...selected, group]
                          : selected.filter((existing) => existing !== group)
                      )
                    }
                  />
                  {group}
                </Label>
              ))}
            </fieldset>
          );
        }

        // item_list — the same catalogue surface the pool is built with, so a
        // map named in a condition is recognised by its art like everywhere else.
        const itemIds = Array.isArray(value) ? (value as number[]) : [];
        return (
          <div key={spec.name} className="flex flex-col gap-1.5">
            <span className="text-muted-foreground">{label}</span>
            <CataloguePicker
              mode="multi"
              kind={kind}
              options={catalogue}
              disabled={disabled}
              selectedIds={itemIds}
              onToggle={(itemId) =>
                setParam(
                  spec.name,
                  itemIds.includes(itemId)
                    ? itemIds.filter((existing) => existing !== itemId)
                    : [...itemIds, itemId]
                )
              }
              onSelectVisible={(visible) =>
                setParam(spec.name, [...new Set([...itemIds, ...visible])])
              }
              onClearVisible={(visible) =>
                setParam(spec.name, itemIds.filter((existing) => !visible.includes(existing)))
              }
            />
            <CatalogueChips
              itemIds={itemIds}
              catalogue={catalogueById}
              disabled={disabled}
              onRemove={(itemId) =>
                setParam(spec.name, itemIds.filter((existing) => existing !== itemId))
              }
            />
          </div>
        );
      })}
    </div>
  );
}
