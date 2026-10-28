"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check } from "lucide-react";

import { eyebrowClass } from "@/components/ui/eyebrow";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FilterChip } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { EmptyNote } from "@/components/kit/EmptyNote";

/**
 * One grantable permission. `key` is what travels in `value` — the RBAC
 * permission name for a role, the scope string for an API key — so the caller
 * never has to translate between what the picker shows and what it stores.
 */
export interface PermissionCatalogEntry {
  key: string;
  resource: string;
  action: string;
  description?: string;
}

export interface PermissionPickerProps {
  catalog: PermissionCatalogEntry[];
  value: Set<string>;
  onChange: (next: Set<string>) => void;
  /**
   * `chips` is one row per resource holding only that resource's actions as
   * toggle chips; `list` is a flat run of named rows with descriptions.
   */
  mode?: "chips" | "list";
  /**
   * Wildcard keys this picker may grant, e.g. `admin.*` or `team.*`. Holding
   * one checks and LOCKS every row it covers: the individual boxes would be
   * no-ops, and showing them as unchecked would claim the opposite of the
   * truth.
   */
  wildcards?: string[];
  readOnly?: boolean;
}

/** The catalogue-wide wildcard: not the `admin` resource, but "everything". */
export const GLOBAL_WILDCARD = "admin.*";

/**
 * Action order, so a resource reads read → write → destroy rather than
 * alphabetically. Anything unlisted sorts after, alphabetically.
 */
const ACTION_ORDER = [
  "*",
  "read",
  "create",
  "update",
  "delete",
  "assign",
  "import",
  "export",
  "sync",
  "recalculate",
  "calculate",
  "publish",
  "generate",
  "approve",
  "reject",
  "check_in",
  "upload",
  "stream",
  "reprocess",
  "revoke"
];

export function sortActions(left: string, right: string): number {
  const leftIndex = ACTION_ORDER.indexOf(left);
  const rightIndex = ACTION_ORDER.indexOf(right);
  if (leftIndex !== -1 || rightIndex !== -1) {
    return (
      (leftIndex === -1 ? ACTION_ORDER.length : leftIndex) -
      (rightIndex === -1 ? ACTION_ORDER.length : rightIndex)
    );
  }
  return left.localeCompare(right);
}

/** `foo_bar` → `foo bar`. */
export function humanize(value: string): string {
  return value.replaceAll("_", " ");
}

/** Does `wildcard` already grant `entry`? */
export function wildcardCovers(wildcard: string, entry: PermissionCatalogEntry): boolean {
  if (wildcard === GLOBAL_WILDCARD) return true;
  const separator = wildcard.indexOf(".");
  if (separator < 0) return false;
  return (
    wildcard.slice(separator + 1) === "*" && wildcard.slice(0, separator) === entry.resource
  );
}

interface ResourceGroup {
  resource: string;
  entries: PermissionCatalogEntry[];
}

/**
 * The one permission surface in the admin panel.
 *
 * It replaces three implementations of the same idea that had already drifted
 * apart: the role matrix (checkbox grid, ids), the API-key `ScopePicker`
 * (grouped checkboxes, scope strings) and `UserDenyEditor` (switches over a
 * hardcoded pair). They disagreed about grouping, about what a wildcard means
 * and about whether "nothing selected" is legal, so the same question got
 * three different answers depending on which screen asked it.
 *
 * `chips` replaced a resource × action matrix: most actions belong to one
 * resource, so the grid was mostly empty cells and scrolled both ways.
 *
 * Selection is a `Set` of keys the caller owns; this component holds no draft.
 * The narrowing box and the "Granted only" chip are deliberately local: this
 * is a form control, and it is mounted inside a dialog often enough that
 * putting its view state in the URL would leak a dialog's internals into a
 * linkable address.
 */
export function PermissionPicker({
  catalog,
  value,
  onChange,
  mode = "chips",
  wildcards,
  readOnly = false
}: Readonly<PermissionPickerProps>) {
  const t = useTranslations("adminAccess.common");
  const tp = useTranslations("adminAccess.permissions");
  const ti = useTranslations("adminAccess.pickerUi");
  const fieldId = useId();
  const [query, setQuery] = useState("");
  // A read-only role is read for what it grants, not for the 130 boxes it does
  // not: start narrowed to the grants when there are any.
  const [grantedOnly, setGrantedOnly] = useState(
    () => mode === "chips" && readOnly && value.size > 0
  );

  const offeredWildcards = wildcards ?? [];
  const heldWildcards = offeredWildcards.filter((wildcard) => value.has(wildcard));

  const isCovered = (entry: PermissionCatalogEntry): boolean =>
    heldWildcards.some((wildcard) => wildcardCovers(wildcard, entry));
  const isGranted = (entry: PermissionCatalogEntry): boolean =>
    value.has(entry.key) || isCovered(entry);

  // Roughly 130 entries at the widest, so the narrowing runs on every render
  // rather than through a `useMemo` whose dependency list would have to
  // restate what `value` and `wildcards` already say.
  const needle = query.trim().toLowerCase();
  const visible = catalog.filter((entry) => {
    if (needle && !`${entry.key} ${entry.resource} ${entry.action}`.toLowerCase().includes(needle)) {
      return false;
    }
    return !grantedOnly || isGranted(entry);
  });

  const byResource = new Map<string, PermissionCatalogEntry[]>();
  for (const entry of visible) {
    const bucket = byResource.get(entry.resource);
    if (bucket) bucket.push(entry);
    else byResource.set(entry.resource, [entry]);
  }
  const groups: ResourceGroup[] = [...byResource.entries()]
    .map(([resource, entries]) => ({
      resource,
      entries: [...entries].sort((left, right) => sortActions(left.action, right.action))
    }))
    .sort((left, right) => left.resource.localeCompare(right.resource));

  const setKeys = (keys: string[], checked: boolean) => {
    const next = new Set(value);
    for (const key of keys) {
      if (checked) next.add(key);
      else next.delete(key);
    }
    onChange(next);
  };

  const selectedCount = catalog.filter(isGranted).length;
  // Narrowing and bulk selection exist for the ~130-entry inventory. A handful
  // of rows needs neither, and a "Grant all" over two rows in a restrictions
  // panel would read as the opposite of what checking them does.
  const showBulkControls = catalog.length > 8;
  // "Selected only" narrows nothing at none or all; it stays while on, so it can be switched off.
  const showSelectedOnly =
    grantedOnly || (selectedCount > 0 && selectedCount < catalog.length);

  const cellCheckbox = (entry: PermissionCatalogEntry) => {
    const covered = isCovered(entry);
    return (
      <Checkbox
        id={`${fieldId}-${entry.key}`}
        aria-label={ti("toggle", { key: entry.key })}
        checked={covered || value.has(entry.key)}
        disabled={readOnly || covered}
        onCheckedChange={(checked) => setKeys([entry.key], checked === true)}
      />
    );
  };

  const actionChip = (entry: PermissionCatalogEntry) => {
    const covered = isCovered(entry);
    return (
      <CheckboxPrimitive.Root
        key={entry.key}
        aria-label={ti("toggle", { key: entry.key })}
        title={entry.description}
        checked={covered || value.has(entry.key)}
        disabled={readOnly || covered}
        onCheckedChange={(checked) => setKeys([entry.key], checked === true)}
        className={cn(
          "inline-flex h-7 items-center gap-1 rounded-md border px-2.5 text-xs font-medium transition-colors",
          "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
          "data-[state=unchecked]:border-border data-[state=unchecked]:text-muted-foreground",
          "enabled:data-[state=unchecked]:hover:border-foreground/30 enabled:data-[state=unchecked]:hover:text-foreground",
          "data-[state=checked]:border-primary/40 data-[state=checked]:bg-primary/10 data-[state=checked]:text-primary",
          "enabled:data-[state=checked]:hover:bg-primary/15",
          "disabled:cursor-not-allowed data-[state=unchecked]:disabled:opacity-50"
        )}
      >
        <CheckboxPrimitive.Indicator>
          <Check aria-hidden className="size-3" />
        </CheckboxPrimitive.Indicator>
        {entry.action === "*" ? ti("all") : humanize(entry.action)}
      </CheckboxPrimitive.Root>
    );
  };

  // A switch that is off and locked says nothing a reader needs.
  const shownWildcards = mode === "chips" && readOnly ? heldWildcards : offeredWildcards;

  return (
    <div className={mode === "chips" ? "space-y-3" : "space-y-2"}>
      <div className="flex flex-wrap items-center gap-2">
        <p className={eyebrowClass("muted")}>{t("permissions")}</p>
        <span className="text-caption tabular-nums text-muted-foreground">
          {t("selectedSummary", { selected: selectedCount, total: catalog.length })}
        </span>
        {showBulkControls ? (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <SearchField
              containerClassName="w-full sm:w-52"
              label={t("filterPermissions")}
              placeholder={t("searchPermissions")}
              value={query}
              onValueChange={setQuery}
            />
            {showSelectedOnly ? (
              <FilterChip active={grantedOnly} onClick={() => setGrantedOnly(!grantedOnly)}>
                {t("selectedOnly")}
              </FilterChip>
            ) : null}
            {readOnly ? null : (
              <>
                <Button
                  type="button"
                  variant={mode === "chips" ? "ghost" : "outline"}
                  size="sm"
                  disabled={visible.length === 0}
                  onClick={() => setKeys(visible.map((entry) => entry.key), true)}
                >
                  {t("selectAll")}
                </Button>
                <Button
                  type="button"
                  variant={mode === "chips" ? "ghost" : "outline"}
                  size="sm"
                  disabled={selectedCount === 0}
                  onClick={() =>
                    setKeys([...visible.map((entry) => entry.key), ...offeredWildcards], false)
                  }
                >
                  {t("clearAll")}
                </Button>
              </>
            )}
          </div>
        ) : null}
      </div>

      {shownWildcards.length === 0 ? null : mode === "chips" ? (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {shownWildcards.map((wildcard) => {
            const held = value.has(wildcard);
            const global = wildcard === GLOBAL_WILDCARD;
            const resource = wildcard.slice(0, wildcard.indexOf("."));
            return (
              <li
                key={wildcard}
                className={cn(
                  "flex items-center gap-4 px-4 py-3 transition-colors",
                  held && (global ? "bg-danger/5" : "bg-primary/5")
                )}
              >
                <label
                  htmlFor={`${fieldId}-wildcard-${wildcard}`}
                  className={cn("min-w-0 flex-1", readOnly ? "" : "cursor-pointer")}
                >
                  <span className="flex flex-wrap items-baseline gap-x-2 text-sm font-medium text-foreground">
                    {global ? ti("fullAccess") : humanize(resource)}
                    <code
                      className={cn(
                        "font-mono text-xs font-normal",
                        global && held ? "text-danger" : "text-muted-foreground"
                      )}
                    >
                      {wildcard}
                    </code>
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {global ? tp("everything") : tp("everythingScoped", { resource })}
                  </span>
                </label>
                <Switch
                  id={`${fieldId}-wildcard-${wildcard}`}
                  checked={held}
                  disabled={readOnly}
                  onCheckedChange={(checked) => setKeys([wildcard], checked)}
                />
              </li>
            );
          })}
        </ul>
      ) : (
        <ul className="space-y-1.5">
          {offeredWildcards.map((wildcard) => (
            <li key={wildcard}>
              <label
                htmlFor={`${fieldId}-wildcard-${wildcard}`}
                className={cn("flex items-start gap-2", readOnly ? "" : "cursor-pointer")}
              >
                <Checkbox
                  id={`${fieldId}-wildcard-${wildcard}`}
                  className="mt-0.5"
                  checked={value.has(wildcard)}
                  disabled={readOnly}
                  onCheckedChange={(checked) => setKeys([wildcard], checked === true)}
                />
                <span className="min-w-0">
                  <span
                    className={cn(
                      "block font-mono text-xs font-semibold",
                      wildcard === GLOBAL_WILDCARD && "text-danger"
                    )}
                  >
                    {wildcard}
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {wildcard === GLOBAL_WILDCARD
                      ? tp("everything")
                      : tp("everythingScoped", {
                          resource: wildcard.slice(0, wildcard.indexOf("."))
                        })}
                  </span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}

      {catalog.length === 0 ? (
        <EmptyNote size="sm">
          {t("actionUnavailable")}
        </EmptyNote>
      ) : groups.length === 0 ? (
        <EmptyNote size="sm">
          {t("nothingHere")}
        </EmptyNote>
      ) : mode === "list" ? (
        <div className="max-h-[52dvh] space-y-3 overflow-y-auto rounded-md border border-border p-2">
          {groups.map((group) => (
            <div key={group.resource} className="space-y-1">
              <p className={eyebrowClass("muted")}>
                {group.resource === "*" ? ti("all") : humanize(group.resource)}
              </p>
              <ul className="grid gap-x-3 gap-y-1 sm:grid-cols-2">
                {group.entries.map((entry) => (
                  <li key={entry.key} className="min-w-0">
                    <label
                      htmlFor={`${fieldId}-${entry.key}`}
                      className={cn(
                        "flex items-start gap-2 text-xs",
                        readOnly || isCovered(entry) ? "text-muted-foreground" : "cursor-pointer"
                      )}
                    >
                      {cellCheckbox(entry)}
                      <span className="min-w-0">
                        <span className="block truncate font-mono">{entry.key}</span>
                        {entry.description ? (
                          <span className="block text-muted-foreground">{entry.description}</span>
                        ) : null}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {groups.map((group) => {
            // The narrowing hides chips, not grants: the count and "All" speak
            // for the whole resource.
            const whole = catalog.filter((entry) => entry.resource === group.resource);
            const rowKeys = whole.map((entry) => entry.key);
            const rowGranted = whole.filter(isGranted).length;
            const rowLocked = whole.every(isCovered);
            const allGranted = rowGranted === rowKeys.length;
            return (
              <li
                key={group.resource}
                className="grid gap-x-4 gap-y-2 px-4 py-3 sm:grid-cols-[10rem_minmax(0,1fr)_auto] sm:items-start"
              >
                <div className="flex min-w-0 items-baseline gap-2 sm:block sm:pt-1">
                  <p className="truncate text-sm font-medium text-foreground">
                    {group.resource === "*" ? ti("all") : humanize(group.resource)}
                  </p>
                  <p className="text-xs tabular-nums text-muted-foreground">
                    {rowGranted}/{rowKeys.length}
                  </p>
                </div>
                <div className="flex flex-wrap gap-1.5">{group.entries.map(actionChip)}</div>
                {readOnly || rowLocked ? null : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-pressed={allGranted}
                    aria-label={ti("toggleResource", { resource: group.resource })}
                    className={cn(
                      "h-7 justify-self-start px-2 text-xs sm:justify-self-end",
                      allGranted ? "text-primary" : "text-muted-foreground"
                    )}
                    onClick={() => setKeys(rowKeys, !allGranted)}
                  >
                    {ti("all")}
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
