"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Lock } from "lucide-react";

import { Card } from "@/components/ui/card";
import { RowButton } from "@/components/ui/row-button";
import { SearchField } from "@/components/ui/search-field";
import type { RbacRole } from "@/types/rbac.types";

/**
 * The master column of Roles (T4, F15).
 *
 * Selecting a role is navigation (`?role=`), not local state, so a role's
 * editor can be linked to — which is what the old screen's dialog could not
 * do. The narrowing box is local: it filters rows already in memory (a scope
 * holds a dozen roles, fetched whole), so there is nothing to put in the URL.
 */
export function RoleList({
  roles,
  selectedRoleId,
  onSelect,
  actions
}: Readonly<{
  roles: RbacRole[];
  selectedRoleId: number | null;
  onSelect: (roleId: number) => void;
  /** The scope switch and Create role, above the narrowing box. */
  actions?: ReactNode;
}>) {
  const t = useTranslations("adminAccess.common");
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const visible = needle
    ? roles.filter((role) => role.name.toLowerCase().includes(needle))
    : roles;

  return (
    <Card>
      <div className="space-y-2 border-b border-border p-3">
        {actions}
        <SearchField
          label={t("filterRoles")}
          placeholder={t("searchRoles")}
          value={query}
          onValueChange={setQuery}
        />
      </div>

      {visible.length === 0 ? (
        <p className="p-3 text-sm text-muted-foreground">
          {roles.length === 0
            ? t("noRoles")
            : t("nothingHere")}
        </p>
      ) : (
        <ul className="flex flex-col gap-1 p-2">
          {visible.map((role) => {
            const selected = role.id === selectedRoleId;
            return (
              <li key={role.id}>
                <RowButton
                  aria-current={selected ? "true" : undefined}
                  onClick={() => onSelect(role.id)}
                  className="flex items-center justify-between gap-2 rounded-md px-2.5 py-2"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-foreground">
                      {role.name}
                    </span>
                    {role.description ? (
                      <span className="block truncate text-xs text-muted-foreground">
                        {role.description}
                      </span>
                    ) : null}
                  </span>
                  {role.is_system ? (
                    <Lock
                      role="img"
                      aria-label={t("system")}
                      className="size-3.5 shrink-0 text-muted-foreground"
                    >
                      <title>{t("system")}</title>
                    </Lock>
                  ) : null}
                </RowButton>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
