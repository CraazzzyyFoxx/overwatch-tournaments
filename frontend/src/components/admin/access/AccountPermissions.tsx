"use client";

import { AccountDisclosure } from "@/components/admin/access/AccountCard";

/**
 * What the account's roles add up to, one line per resource. A flat wall of
 * `resource.action` badges repeated the resource on every chip; grouped, the
 * question "can they touch matches?" is one line to scan.
 */
export function AccountPermissions({ permissions }: Readonly<{ permissions: string[] }>) {
  const byResource = new Map<string, string[]>();
  for (const permission of permissions) {
    const dot = permission.indexOf(".");
    const resource = dot < 0 ? permission : permission.slice(0, dot);
    const actions = byResource.get(resource) ?? [];
    if (dot >= 0) actions.push(permission.slice(dot + 1));
    byResource.set(resource, actions);
  }
  const rows = [...byResource.entries()].sort(([left], [right]) => left.localeCompare(right));

  return (
    <AccountDisclosure title="Effective permissions" summary={permissions.length}>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">None. Assign a role to grant access.</p>
      ) : (
        <dl className="space-y-1 font-mono text-xs">
          {rows.map(([resource, actions]) => (
            <div key={resource} className="flex gap-3">
              <dt className="w-28 shrink-0 truncate text-muted-foreground" title={resource}>
                {resource}
              </dt>
              <dd className="min-w-0 flex-1 break-words">{actions.sort().join(" · ")}</dd>
            </div>
          ))}
        </dl>
      )}
    </AccountDisclosure>
  );
}
