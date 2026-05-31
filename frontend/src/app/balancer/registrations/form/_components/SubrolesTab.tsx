"use client";

import { useState } from "react";
import { Check, Loader2, Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { ROLES, ROLE_LABELS } from "@/lib/roles";

export interface CatalogEntry {
  id: number;
  slug: string;
  label: string;
}

/**
 * Sub-role management + selection. The workspace `PlayerSubRole` catalog is the
 * source of truth — entries can be created/removed here. Toggling a chip selects
 * whether that sub-role is *offered* on this tournament's registration form
 * (a role with no explicit selection offers all of its catalog options).
 */
export function SubrolesTab({
  catalog,
  selection,
  onToggleOffered,
  onCreate,
  onDelete,
  isLoading = false,
  isMutating = false,
  canManage = true,
}: {
  /** Workspace catalog grouped by registration role code, with row ids. */
  catalog: Record<string, CatalogEntry[]>;
  /** Current per-role offered selection (slug list), or undefined = offer all. */
  selection: Record<string, string[] | undefined>;
  onToggleOffered: (role: string, slug: string, nextSlugs: string[]) => void;
  onCreate: (role: string, label: string) => void;
  onDelete: (entry: CatalogEntry) => void;
  isLoading?: boolean;
  isMutating?: boolean;
  canManage?: boolean;
}) {
  const [draftLabels, setDraftLabels] = useState<Record<string, string>>({});

  const submitCreate = (role: string) => {
    const label = (draftLabels[role] ?? "").trim();
    if (!label) {
      return;
    }
    onCreate(role, label);
    setDraftLabels((prev) => ({ ...prev, [role]: "" }));
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sub-roles</CardTitle>
        <CardDescription>
          Manage the workspace sub-role catalog and choose which sub-roles players can pick per
          role. Highlighted chips are offered on the form; leave all enabled to offer every option.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {ROLES.map((role) => {
          const options = catalog[role.code] ?? [];
          const roleSelection = selection[role.code];
          const allSlugs = options.map((option) => option.slug);

          return (
            <div key={role.code} className="space-y-2 rounded-lg border p-4">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{ROLE_LABELS[role.code] ?? role.display}</span>
                {options.length > 0 && roleSelection !== undefined && (
                  <span className="text-[11px] text-muted-foreground">
                    {roleSelection.filter((slug) => allSlugs.includes(slug)).length}/{options.length} offered
                  </span>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-1.5">
                {options.map((option) => {
                  const offered = roleSelection === undefined || roleSelection.includes(option.slug);
                  return (
                    <span
                      key={option.id}
                      className={cn(
                        "group inline-flex items-center gap-1 rounded-md border py-1 pl-2.5 pr-1 text-xs font-medium transition-colors",
                        offered
                          ? "border-primary/30 bg-primary/10 text-primary"
                          : "border-border/60 text-muted-foreground",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => {
                          const effective = roleSelection ?? allSlugs;
                          const next = offered
                            ? effective.filter((slug) => slug !== option.slug)
                            : [...effective, option.slug];
                          onToggleOffered(role.code, option.slug, next);
                        }}
                        className="inline-flex items-center gap-1"
                        title={offered ? "Offered on the form — click to hide" : "Hidden — click to offer"}
                      >
                        {offered && <Check className="size-3" />}
                        {option.label}
                      </button>
                      {canManage && (
                        <button
                          type="button"
                          onClick={() => onDelete(option)}
                          disabled={isMutating}
                          title="Remove from workspace catalog"
                          className="rounded p-0.5 text-muted-foreground/60 transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
                        >
                          <X className="size-3" />
                        </button>
                      )}
                    </span>
                  );
                })}

                {options.length === 0 && (
                  <span className="text-xs italic text-muted-foreground/60">
                    {isLoading ? "Loading…" : "No sub-roles yet."}
                  </span>
                )}
              </div>

              {canManage && (
                <div className="flex items-center gap-2 pt-1">
                  <Input
                    value={draftLabels[role.code] ?? ""}
                    onChange={(e) =>
                      setDraftLabels((prev) => ({ ...prev, [role.code]: e.target.value }))
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        submitCreate(role.code);
                      }
                    }}
                    placeholder={`Add a ${ROLE_LABELS[role.code] ?? role.display} sub-role (e.g. Main Tank)`}
                    className="h-8 max-w-xs text-xs"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8"
                    disabled={isMutating || !(draftLabels[role.code] ?? "").trim()}
                    onClick={() => submitCreate(role.code)}
                  >
                    {isMutating ? (
                      <Loader2 className="mr-1 size-3.5 animate-spin" />
                    ) : (
                      <Plus className="mr-1 size-3.5" />
                    )}
                    Add
                  </Button>
                </div>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
