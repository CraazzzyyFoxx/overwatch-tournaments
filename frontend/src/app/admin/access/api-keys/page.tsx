"use client";

import { useEffect, useId, useMemo, useState, type FormEvent } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Check, Clipboard, Gauge, KeyRound, Plus, Trash2, X } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { AdminDataTable, createKebabColumn } from "@/components/data-table";
import { InlineEditText } from "@/components/kit/InlineEditText";
import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { ApiKeyQuotaDialog } from "@/components/admin/quota/ApiKeyQuotaDialog";
import {
  PermissionPicker,
  type PermissionCatalogEntry
} from "@/components/admin/access/PermissionPicker";
import { FilterBar } from "@/components/kit/FilterBar";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { TONE_CLASS, TONE_TEXT, type Tone } from "@/components/kit/tone";
import type { DateFormatter } from "@/components/kit/format-time";
import { Button } from "@/components/ui/button";
import { DateTimePicker } from "@/components/ui/date-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageStateCard } from "@/components/ui/page-state-card";
import { StatusDot } from "@/components/ui/status-dot";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  fetchAccountApiKeys,
  useCreateAccountApiKey,
  useRenameAccountApiKey,
  useRevokeAccountApiKey,
  type AccountApiKeyStatusCounts
} from "@/hooks/use-account-api-keys";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { AccountApiKey } from "@/types/auth.types";
import { EmptyNote } from "@/components/kit/EmptyNote";

const PAGE_SIZE = 20;

/**
 * The catalog wildcard: `resource="*" action="*"`. It grants every permission
 * the owner holds, including ones added to the catalog later, so the picker
 * renders it apart from the per-resource groups and locks what it covers.
 */
const FULL_ACCESS_SCOPE = "admin.*";

/** Scope chips rendered inline in the table before collapsing into a `+N` count. */
const SCOPE_PREVIEW_COUNT = 2;

const EMPTY_COUNTS: AccountApiKeyStatusCounts = { total: 0, active: 0, expired: 0, revoked: 0 };

type ApiKeyStatus = "active" | "expired" | "revoked";

const STATUS_META: Record<ApiKeyStatus, { label: string; tone: Tone }> = {
  active: { label: "Active", tone: "success" },
  expired: { label: "Expired", tone: "neutral" },
  revoked: { label: "Revoked", tone: "warning" }
};

function formatTimestamp(format: DateFormatter, value: string | null | undefined): string {
  if (!value) return "Never";

  return format.dateTime(new Date(value), { dateStyle: "medium", timeStyle: "short" });
}

function getApiKeyStatus(apiKey: AccountApiKey): ApiKeyStatus {
  if (apiKey.revoked_at) return "revoked";
  const expiresAt = apiKey.expires_at ? new Date(apiKey.expires_at).getTime() : NaN;
  if (Number.isFinite(expiresAt) && expiresAt <= Date.now()) return "expired";
  return "active";
}

function StatusCell({ status }: Readonly<{ status: ApiKeyStatus }>) {
  const meta = STATUS_META[status];

  return (
    <span
      className={cn("inline-flex items-center gap-1.5 text-xs font-medium", TONE_TEXT[meta.tone])}
    >
      <StatusDot />
      {meta.label}
    </span>
  );
}

/**
 * Granted scopes for one row. Relies on the `TooltipProvider` mounted by the
 * admin layout. A key with no scopes authenticates but fails every permission
 * check, so it is flagged in the danger tone rather than shown as empty.
 */
function ScopesCell({ scopes }: Readonly<{ scopes: readonly string[] }>) {
  if (scopes.length === 0) {
    return (
      <span
        className={cn("inline-flex items-center gap-1.5 text-xs font-medium", TONE_TEXT.danger)}
      >
        <StatusDot />
        No scopes — inert
      </span>
    );
  }

  if (scopes.includes(FULL_ACCESS_SCOPE)) {
    return (
      <span
        className={cn(
          "inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-xs",
          TONE_CLASS.danger
        )}
      >
        {FULL_ACCESS_SCOPE}
      </span>
    );
  }

  const preview = scopes.slice(0, SCOPE_PREVIEW_COUNT);
  const hidden = scopes.length - preview.length;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex max-w-56 flex-wrap items-center gap-1">
          {preview.map((scope) => (
            <span
              key={scope}
              className={cn(
                "rounded-md border px-1.5 py-0.5 font-mono text-xs",
                TONE_CLASS.neutral
              )}
            >
              {scope}
            </span>
          ))}
          {hidden > 0 ? (
            <span className="text-xs tabular-nums text-muted-foreground">+{hidden}</span>
          ) : null}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-72">
        <p className="font-mono text-xs leading-relaxed">{scopes.join(", ")}</p>
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * Workspace API keys (T2, F15).
 *
 * Renaming is inline in the row (`InlineEditText`), revoking is the screen's
 * single `ConfirmDialog`, and creating is an `EntityFormDialog` whose scope
 * list is the shared `PermissionPicker` rather than a private implementation
 * of a checkbox tree. Quotas are the one screen-local concern that earns a
 * dialog of its own: they are a read (two budgets, live counters) and a write
 * in the same breath, which no row control can hold.
 */
export default function AccessAdminApiKeysPage() {
  const format = useFormatter();
  const tQuota = useTranslations("quota");
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const fetchWorkspaces = useWorkspaceStore((state) => state.fetchWorkspaces);
  const { hasWorkspacePermission, isSuperuser, isWorkspaceAdmin } = usePermissions();

  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createExpiresAt, setCreateExpiresAt] = useState("");
  const [createScopes, setCreateScopes] = useState<Set<string>>(new Set());
  const [oneTimeKey, setOneTimeKey] = useState<string | null>(null);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const [pendingRevoke, setPendingRevoke] = useState<AccountApiKey | null>(null);
  const [pendingQuota, setPendingQuota] = useState<AccountApiKey | null>(null);
  const [counts, setCounts] = useState<AccountApiKeyStatusCounts>(EMPTY_COUNTS);
  const [availableScopes, setAvailableScopes] = useState<string[]>([]);
  const createNameId = useId();
  const secretId = useId();

  useEffect(() => {
    if (workspaces.length === 0) {
      void fetchWorkspaces();
    }
  }, [fetchWorkspaces, workspaces.length]);

  const manageableWorkspaces = workspaces.filter(
    (workspace) =>
      isSuperuser ||
      isWorkspaceAdmin(workspace.id) ||
      hasWorkspacePermission(workspace.id, "team.create")
  );

  const defs = useMemo<FilterDef[]>(
    () => [
      {
        key: "workspace",
        label: "Workspace",
        kind: "single",
        options: manageableWorkspaces.map((workspace) => ({
          value: String(workspace.id),
          label: workspace.name
        }))
      }
    ],
    [manageableWorkspaces]
  );
  const filters = useFilters(defs);

  // A key is always scoped to exactly one workspace, so there is no "all"
  // reading: an absent or unusable chip falls back to the workspace the shell
  // is already in, then to the first one this account administers.
  const chipWorkspaceId = Number(filters.values.workspace ?? "");
  const workspaceId =
    manageableWorkspaces.find((workspace) => workspace.id === chipWorkspaceId)?.id ??
    manageableWorkspaces.find((workspace) => workspace.id === currentWorkspaceId)?.id ??
    manageableWorkspaces[0]?.id ??
    null;
  const workspace = manageableWorkspaces.find((entry) => entry.id === workspaceId) ?? null;

  const createMutation = useCreateAccountApiKey();
  const renameMutation = useRenameAccountApiKey(workspaceId);
  const revokeMutation = useRevokeAccountApiKey(workspaceId);

  // `available_scopes` is computed per workspace, so moving the chip drops the
  // draft selection: keeping it would offer the previous workspace's grants.
  const scopeCatalog: PermissionCatalogEntry[] = availableScopes
    .filter((scope) => !scope.endsWith(".*"))
    .map((scope) => {
      const separator = scope.indexOf(".");
      return {
        key: scope,
        resource: separator > 0 ? scope.slice(0, separator) : scope,
        action: separator > 0 ? scope.slice(separator + 1) : "*"
      };
    });
  const scopeWildcards = availableScopes.filter((scope) => scope.endsWith(".*"));

  const columns = useMemo<ColumnDef<AccountApiKey>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Name",
        cell: ({ row }) => {
          const apiKey = row.original;
          return (
            <div className="flex min-w-0 items-center gap-2">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border/60">
                <KeyRound aria-hidden className="size-4 text-muted-foreground" />
              </span>
              <div className="min-w-0">
                <InlineEditText
                  value={apiKey.name}
                  label={`name of API key ${apiKey.name}`}
                  canEdit={getApiKeyStatus(apiKey) === "active"}
                  textClassName="text-sm font-medium"
                  onSave={(next) =>
                    renameMutation.mutateAsync(
                      { id: apiKey.id, name: next },
                      { onSuccess: () => notify.success("API key renamed") }
                    )
                  }
                />
                <p className="truncate font-mono text-xs text-muted-foreground">
                  owt_sk_{apiKey.public_id}_…
                </p>
              </div>
            </div>
          );
        }
      },
      {
        id: "owner",
        header: "Owner",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="truncate text-sm">{row.original.owner_username}</span>
        )
      },
      {
        id: "status",
        header: "Status",
        enableSorting: false,
        cell: ({ row }) => <StatusCell status={getApiKeyStatus(row.original)} />
      },
      {
        id: "scopes",
        header: "Scopes",
        enableSorting: false,
        cell: ({ row }) => <ScopesCell scopes={row.original.scopes} />
      },
      {
        accessorKey: "created_at",
        header: "Created",
        cell: ({ row }) => (
          <span className="text-xs tabular-nums text-muted-foreground">
            {formatTimestamp(format, row.original.created_at)}
          </span>
        )
      },
      {
        accessorKey: "last_used_at",
        header: "Last used",
        cell: ({ row }) => (
          <span className="text-xs tabular-nums text-muted-foreground">
            {formatTimestamp(format, row.original.last_used_at)}
          </span>
        )
      },
      {
        accessorKey: "expires_at",
        header: "Expires",
        cell: ({ row }) => (
          <span className="text-xs tabular-nums text-muted-foreground">
            {formatTimestamp(format, row.original.expires_at)}
          </span>
        )
      },
      createKebabColumn<AccountApiKey>(
        (row) => [
          {
            label: tQuota("apiKey.menuItem"),
            icon: Gauge,
            onSelect: () => setPendingQuota(row)
          },
          {
            label: "Revoke key",
            icon: Trash2,
            destructive: true,
            hidden: getApiKeyStatus(row) !== "active",
            onSelect: () => setPendingRevoke(row)
          }
        ],
        { rowLabel: (row) => `API key ${row.name}` }
      )
    ],
    [format, renameMutation, tQuota]
  );

  if (manageableWorkspaces.length === 0) {
    return (
      <PageStateCard
        state="empty"
        title="You do not administer a workspace yet"
        description="API keys are scoped to a workspace. Ask a superuser for workspace admin rights, then reload this page."
      />
    );
  }

  return (
    <div className="space-y-4">
      <StatTileGrid>
        <StatTile
          label="Total keys"
          value={counts.total}
          detail={workspace ? `In ${workspace.name}` : undefined}
          icon={KeyRound}
        />
        <StatTile label="Active" value={counts.active} tone="success" />
        <StatTile label="Expired" value={counts.expired} tone="neutral" />
        <StatTile label="Revoked" value={counts.revoked} tone="warning" />
      </StatTileGrid>

      {oneTimeKey ? (
        <div className={cn("rounded-xl border p-3", TONE_CLASS.success)}>
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div className="min-w-0 flex-1">
              <Label htmlFor={secretId} className="text-sm font-medium text-foreground">
                One-time secret
              </Label>
              <p className="mt-0.5 text-xs text-muted-foreground">
                This full API key is visible only once. Copy it now — reopening this page will not
                show it again.
              </p>
              <Input
                id={secretId}
                readOnly
                value={oneTimeKey}
                className="mt-2 font-mono text-xs"
                onFocus={(event) => event.currentTarget.select()}
              />
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <output className="text-xs text-muted-foreground">
                {copiedSecret ? (
                  <span className="inline-flex items-center gap-1">
                    <Check aria-hidden className="size-3.5" />
                    Copied to clipboard
                  </span>
                ) : null}
              </output>
              <Button
                variant="outline"
                size="sm"
                aria-label="Copy the API key secret to the clipboard"
                onClick={async () => {
                  await navigator.clipboard.writeText(oneTimeKey);
                  setCopiedSecret(true);
                  notify.success("API key copied");
                }}
              >
                <Clipboard aria-hidden className="size-4" />
                Copy secret
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                aria-label="Dismiss the one-time secret"
                onClick={() => {
                  setOneTimeKey(null);
                  setCopiedSecret(false);
                }}
              >
                <X aria-hidden className="size-4" />
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <AdminDataTable<AccountApiKey>
        columns={columns}
        initialPageSize={PAGE_SIZE}
        pageSizeOptions={[10, 20, 50, 100]}
        searchPlaceholder="Search by name…"
        filterKey={filters.filterKey}
        getRowId={(row) => String(row.id)}
        emptyMessage="No API keys in this workspace yet. Create one to call the balancer public API."
        toolbar={
          <FilterBar
            defs={defs}
            filters={filters}
            trailing={
              <Button
                size="sm"
                onClick={() => {
                  setCreateName("");
                  setCreateExpiresAt("");
                  setCreateScopes(new Set());
                  setCreateOpen(true);
                }}
              >
                <Plus aria-hidden className="size-4" />
                Create key
              </Button>
            }
          />
        }
        renderMobileCard={(row) => (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{row.original.name}</p>
            <p className="truncate font-mono text-xs text-muted-foreground">
              owt_sk_{row.original.public_id}_…
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {STATUS_META[getApiKeyStatus(row.original)].label} ·{" "}
              {row.original.scopes.length} scope
              {row.original.scopes.length === 1 ? "" : "s"}
            </p>
          </div>
        )}
        queryKey={(page, search, pageSize, sortField, sortDir) => [
          "account",
          "api-keys",
          workspaceId,
          page,
          search,
          pageSize,
          sortField,
          sortDir
        ]}
        queryFn={async (page, search, pageSize, sortField, sortDir) => {
          if (workspaceId === null) {
            return { results: [], total: 0, page: 1, per_page: pageSize };
          }
          const result = await fetchAccountApiKeys({
            workspaceId,
            page,
            perPage: pageSize,
            sort: sortField ?? undefined,
            order: sortDir,
            search: search || undefined
          });
          setCounts(result.counts);
          // Never let a missing array reach the picker: it reads `.length`
          // first, and an undefined there took the whole admin page down.
          setAvailableScopes(result.available_scopes ?? []);
          return result;
        }}
      />

      <EntityFormDialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open);
          if (!open) createMutation.reset();
        }}
        title="Create API key"
        description={`The key lives in ${workspace?.name ?? "this workspace"} and carries only the permissions you grant it here — never more than you hold yourself.`}
        submitLabel="Create key"
        submittingLabel="Creating…"
        isSubmitting={createMutation.isPending}
        isDirty={createName.trim().length > 0 || createScopes.size > 0}
        contentClassName="!max-w-2xl"
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          if (createName.trim().length === 0) {
            notify.error("Name the key before creating it.", {
              description: "Use something that says where it is used, such as a bot or CI job."
            });
            return;
          }
          if (workspaceId === null) return;
          if (createScopes.size === 0) {
            // Not a blocker: a scope-less key is a legitimate placeholder. It
            // is only worth saying out loud, because it will 403 on everything.
            notify.warning("Creating a key with no scopes.", {
              description: "It will authenticate but every permission check rejects it."
            });
          }

          const expires = createExpiresAt ? new Date(createExpiresAt) : null;
          createMutation.mutate(
            {
              workspace_id: workspaceId,
              expires_at:
                expires && !Number.isNaN(expires.getTime()) ? expires.toISOString() : null,
              name: createName.trim(),
              scopes: [...createScopes]
            },
            {
              onSuccess: (result) => {
                setOneTimeKey(result.key);
                setCopiedSecret(false);
                setCreateOpen(false);
                setCreateName("");
                setCreateExpiresAt("");
                setCreateScopes(new Set());
                notify.success("API key created", {
                  description: "Copy the secret now. It will not be shown again."
                });
              }
            }
          );
        }}
      >
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor={createNameId}>Name</Label>
            <Input
              id={createNameId}
              required
              maxLength={100}
              value={createName}
              onChange={(event) => setCreateName(event.target.value)}
            />
          </div>

          <DateTimePicker
            id="create-api-key-expires-date"
            timeId="create-api-key-expires-time"
            dateLabel="Expires"
            timeLabel="Time"
            value={createExpiresAt}
            onChange={setCreateExpiresAt}
            placeholder="Never"
            clearLabel="Never"
            minDate={new Date()}
            disabled={createMutation.isPending}
          />

          {availableScopes.length === 0 ? (
            <EmptyNote size="sm">
              You hold no delegatable permissions in this workspace, so every key created here
              would be inert. Ask a workspace admin to grant you the permissions first.
            </EmptyNote>
          ) : (
            <PermissionPicker
              mode="list"
              catalog={scopeCatalog}
              wildcards={scopeWildcards}
              value={createScopes}
              onChange={setCreateScopes}
              readOnly={createMutation.isPending}
            />
          )}
        </div>
      </EntityFormDialog>

      <ConfirmDialog
        open={pendingRevoke !== null}
        onOpenChange={(open) => {
          if (!open) setPendingRevoke(null);
        }}
        pending={revokeMutation.isPending}
        intent={{
          title: "Revoke API key",
          description: `Revoking “${pendingRevoke?.name ?? "this key"}” stops every request that uses it immediately, so any integration still sending it starts failing with 401. The key cannot be restored — issue a new one instead.`,
          confirmLabel: "Revoke key",
          tone: "danger"
        }}
        onConfirm={() => {
          if (!pendingRevoke) return;
          revokeMutation.mutate(pendingRevoke.id, {
            onSuccess: () => {
              setPendingRevoke(null);
              notify.success("API key revoked");
            }
          });
        }}
      />

      {/* Keyed by the key's id: a fresh instance per open means the override
          draft can never carry a previous key's numbers into this one. */}
      <ApiKeyQuotaDialog
        key={pendingQuota?.id ?? "none"}
        apiKey={pendingQuota}
        workspaceId={workspaceId}
        onClose={() => setPendingQuota(null)}
      />
    </div>
  );
}
