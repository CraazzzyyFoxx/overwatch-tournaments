"use client";

import { useId, useState } from "react";
import { CheckSquare, XSquare } from "lucide-react";

import { EYEBROW_CLASS, TONE_CLASS } from "@/components/kit/tone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FilterChip } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
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
  /** `matrix` is resource × action; `list` is a flat run of named rows. */
  mode?: "matrix" | "list";
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
const GLOBAL_WILDCARD = "admin.*";

/**
 * Action order, so the matrix reads read → write → destroy rather than
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

function sortActions(left: string, right: string): number {
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

/** `foo_bar` → `foo bar`; `*` is the whole-resource column. */
function humanize(value: string): string {
  return value === "*" ? "All" : value.replaceAll("_", " ");
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
  byAction: Map<string, PermissionCatalogEntry>;
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
  mode = "matrix",
  wildcards,
  readOnly = false
}: Readonly<PermissionPickerProps>) {
  const fieldId = useId();
  const [query, setQuery] = useState("");
  const [grantedOnly, setGrantedOnly] = useState(false);

  const offeredWildcards = wildcards ?? [];
  const heldWildcards = offeredWildcards.filter((wildcard) => value.has(wildcard));

  const isCovered = (entry: PermissionCatalogEntry): boolean =>
    heldWildcards.some((wildcard) => wildcardCovers(wildcard, entry));

  // Roughly 90 entries at the widest, so the narrowing runs on every render
  // rather than through a `useMemo` whose dependency list would have to
  // restate what `value` and `wildcards` already say.
  const needle = query.trim().toLowerCase();
  const visible = catalog.filter((entry) => {
    if (needle && !`${entry.key} ${entry.resource} ${entry.action}`.toLowerCase().includes(needle)) {
      return false;
    }
    return !grantedOnly || value.has(entry.key) || isCovered(entry);
  });

  const byResource = new Map<string, PermissionCatalogEntry[]>();
  for (const entry of visible) {
    const bucket = byResource.get(entry.resource);
    if (bucket) bucket.push(entry);
    else byResource.set(entry.resource, [entry]);
  }
  const groups: ResourceGroup[] = [...byResource.entries()]
    .map(([resource, entries]) => {
      const sorted = [...entries].sort((left, right) => sortActions(left.action, right.action));
      return {
        resource,
        entries: sorted,
        byAction: new Map(sorted.map((entry) => [entry.action, entry]))
      };
    })
    .sort((left, right) => left.resource.localeCompare(right.resource));

  const actions = [...new Set(visible.map((entry) => entry.action))].sort(sortActions);

  const setKeys = (keys: string[], checked: boolean) => {
    const next = new Set(value);
    for (const key of keys) {
      if (checked) next.add(key);
      else next.delete(key);
    }
    onChange(next);
  };

  const selectedCount = catalog.filter((entry) => value.has(entry.key) || isCovered(entry)).length;
  // Narrowing and bulk selection exist for the ~90-entry inventory. A handful
  // of rows needs neither, and a "Grant all" over two rows in a restrictions
  // panel would read as the opposite of what checking them does.
  const showBulkControls = catalog.length > 8;

  const cellCheckbox = (entry: PermissionCatalogEntry) => {
    const covered = isCovered(entry);
    return (
      <Checkbox
        id={`${fieldId}-${entry.key}`}
        aria-label={`Toggle ${entry.key}`}
        checked={covered || value.has(entry.key)}
        disabled={readOnly || covered}
        onCheckedChange={(checked) => setKeys([entry.key], checked === true)}
      />
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className={EYEBROW_CLASS}>Permissions</p>
        <Badge variant="outline" className="tabular-nums">
          {selectedCount}/{catalog.length} selected
        </Badge>
        {showBulkControls ? (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <SearchField
              containerClassName="w-full sm:w-52"
              label="Filter permissions"
              placeholder="Filter permissions…"
              value={query}
              onValueChange={setQuery}
            />
            <FilterChip active={grantedOnly} onClick={() => setGrantedOnly(!grantedOnly)}>
              Selected only
            </FilterChip>
            {readOnly ? null : (
              <>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={visible.length === 0}
                  onClick={() => setKeys(visible.map((entry) => entry.key), true)}
                >
                  <CheckSquare aria-hidden className="size-4" />
                  Select all
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={selectedCount === 0}
                  onClick={() =>
                    setKeys([...visible.map((entry) => entry.key), ...offeredWildcards], false)
                  }
                >
                  <XSquare aria-hidden className="size-4" />
                  Clear all
                </Button>
              </>
            )}
          </div>
        ) : null}
      </div>

      {offeredWildcards.length > 0 ? (
        <ul className="space-y-1.5">
          {offeredWildcards.map((wildcard) => (
            <li key={wildcard}>
              <label
                htmlFor={`${fieldId}-wildcard-${wildcard}`}
                className={cn(
                  "flex items-start gap-2 rounded-md border p-2",
                  readOnly ? "" : "cursor-pointer",
                  TONE_CLASS.danger
                )}
              >
                <Checkbox
                  id={`${fieldId}-wildcard-${wildcard}`}
                  className="mt-0.5"
                  checked={value.has(wildcard)}
                  disabled={readOnly}
                  onCheckedChange={(checked) => setKeys([wildcard], checked === true)}
                />
                <span className="min-w-0">
                  <span className="block font-mono text-xs font-semibold">{wildcard}</span>
                  <span className="mt-0.5 block text-xs">
                    {wildcard === GLOBAL_WILDCARD
                      ? "Everything, including permissions added later. Grant it only where you would grant your own account."
                      : `Every current and future action on ${wildcard.slice(0, wildcard.indexOf("."))}.`}
                  </span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      ) : null}

      {catalog.length === 0 ? (
        <EmptyNote size="sm">
          No permissions are available to grant here.
        </EmptyNote>
      ) : groups.length === 0 ? (
        <EmptyNote size="sm">
          Nothing matches this filter.
        </EmptyNote>
      ) : mode === "list" ? (
        <div className="max-h-[52dvh] space-y-3 overflow-y-auto rounded-md border border-border p-2">
          {groups.map((group) => (
            <div key={group.resource} className="space-y-1">
              <p className={EYEBROW_CLASS}>{humanize(group.resource)}</p>
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
        <div className="max-h-[52dvh] overflow-auto rounded-md border border-border">
          <Table wrapperClassName="min-w-[760px] overflow-visible">
            <TableHeader className="sticky top-0 z-10 bg-background">
              <TableRow className="hover:bg-transparent">
                <TableHead className="sticky left-0 z-20 w-56 bg-background">Resource</TableHead>
                {actions.map((action) => {
                  const columnKeys = groups
                    .map((group) => group.byAction.get(action))
                    .filter((entry): entry is PermissionCatalogEntry => entry !== undefined)
                    .map((entry) => entry.key);
                  return (
                    <TableHead key={action} className="min-w-24 bg-background text-center">
                      <span className="flex flex-col items-center gap-1.5">
                        <Checkbox
                          aria-label={`Toggle every ${action} permission`}
                          checked={
                            columnKeys.length > 0 && columnKeys.every((key) => value.has(key))
                          }
                          disabled={readOnly || columnKeys.length === 0}
                          onCheckedChange={(checked) => setKeys(columnKeys, checked === true)}
                        />
                        <span className="text-xs capitalize">{humanize(action)}</span>
                      </span>
                    </TableHead>
                  );
                })}
              </TableRow>
            </TableHeader>
            <TableBody>
              {groups.map((group) => {
                const rowKeys = group.entries.map((entry) => entry.key);
                const rowGranted = rowKeys.filter((key) => value.has(key)).length;
                return (
                  <TableRow key={group.resource}>
                    <TableCell className="sticky left-0 z-[1] bg-background">
                      <span className="flex items-center gap-3">
                        <Checkbox
                          aria-label={`Toggle every ${group.resource} permission`}
                          checked={rowGranted === rowKeys.length}
                          disabled={readOnly}
                          onCheckedChange={(checked) => setKeys(rowKeys, checked === true)}
                        />
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium">
                            {humanize(group.resource)}
                          </span>
                          <span className="block text-xs tabular-nums text-muted-foreground">
                            {rowGranted}/{rowKeys.length}
                          </span>
                        </span>
                      </span>
                    </TableCell>
                    {actions.map((action) => {
                      const entry = group.byAction.get(action);
                      if (!entry) {
                        return (
                          <TableCell key={action} className="text-center text-muted-foreground">
                            <span aria-hidden>&mdash;</span>
                            <span className="sr-only">Not applicable</span>
                          </TableCell>
                        );
                      }
                      return (
                        <TableCell key={action} className="text-center">
                          <span className="flex justify-center">{cellCheckbox(entry)}</span>
                        </TableCell>
                      );
                    })}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
