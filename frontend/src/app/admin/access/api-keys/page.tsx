"use client";

import { useEffect, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Check, Clipboard, KeyRound, Loader2, Pencil, Plus, Trash2, X } from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { DateTimePicker } from "@/components/ui/date-picker";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
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
import type { AccountApiKey, ApiKeyConfigPolicy, ApiKeyLimits } from "@/types/auth.types";

const PAGE_SIZE = 20;

const DEFAULT_LIMITS: ApiKeyLimits = {
  requests_per_minute: 60,
  jobs_per_day: 100,
  concurrent_jobs: 2,
  max_upload_bytes: 10 * 1024 * 1024,
  max_players: 500
};

const DEFAULT_POLICY: ApiKeyConfigPolicy = {
  allowed_keys: [
    "role_mask",
    "population_size",
    "generation_count",
    "use_captains",
    "max_result_variants"
  ],
  max_values: {
    population_size: 150,
    generation_count: 500,
    max_result_variants: 10
  }
};

const EMPTY_COUNTS: AccountApiKeyStatusCounts = { total: 0, active: 0, expired: 0, revoked: 0 };

type ApiKeyStatus = "active" | "expired" | "revoked";

const STATUS_META: Record<
  ApiKeyStatus,
  { label: string; dotClassName: string; textClassName: string }
> = {
  active: {
    label: "Active",
    dotClassName: "bg-emerald-500",
    textClassName: "text-emerald-500"
  },
  expired: {
    label: "Expired",
    dotClassName: "bg-slate-500",
    textClassName: "text-slate-500"
  },
  revoked: {
    label: "Revoked",
    dotClassName: "bg-amber-500",
    textClassName: "text-amber-500"
  }
};

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "Never";

  return new Date(value).toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short"
  });
}

function formatBytes(value: number): string {
  if (value >= 1024 * 1024) return `${Math.round(value / (1024 * 1024))} MiB`;
  if (value >= 1024) return `${Math.round(value / 1024)} KiB`;
  return `${value} B`;
}

function isPastTimestamp(value: string | null | undefined): boolean {
  if (!value) return false;
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) && timestamp <= Date.now();
}

function toIsoTimestamp(value: string): string | null {
  if (!value) return null;
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? null : timestamp.toISOString();
}

function getApiKeyStatus(apiKey: AccountApiKey): ApiKeyStatus {
  if (apiKey.revoked_at) return "revoked";
  if (isPastTimestamp(apiKey.expires_at)) return "expired";
  return "active";
}

function mergeLimits(limits: Partial<ApiKeyLimits> | undefined): ApiKeyLimits {
  return { ...DEFAULT_LIMITS, ...(limits ?? {}) };
}

function mergePolicy(policy: Partial<ApiKeyConfigPolicy> | undefined): ApiKeyConfigPolicy {
  return {
    allowed_keys: policy?.allowed_keys ?? DEFAULT_POLICY.allowed_keys,
    max_values: policy?.max_values ?? DEFAULT_POLICY.max_values
  };
}

function StatusCell({ status }: { status: ApiKeyStatus }) {
  const meta = STATUS_META[status];

  return (
    <span
      className={cn("inline-flex items-center gap-1.5 text-xs font-medium", meta.textClassName)}
    >
      <span className={cn("size-1.5 rounded-full", meta.dotClassName)} />
      {meta.label}
    </span>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-border/50 bg-muted/20 px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/60">
        {label}
      </p>
      <p className="mt-0.5 truncate text-sm font-semibold text-foreground">{value}</p>
    </div>
  );
}

function LimitsText({ limits }: { limits: Partial<ApiKeyLimits> | undefined }) {
  const merged = mergeLimits(limits);

  return (
    <span className="text-xs text-muted-foreground">
      {merged.requests_per_minute}/min | {merged.jobs_per_day}/day | {merged.concurrent_jobs}{" "}
      concurrent | {formatBytes(merged.max_upload_bytes)}
    </span>
  );
}

function PolicyText({ policy }: { policy: Partial<ApiKeyConfigPolicy> | undefined }) {
  const merged = mergePolicy(policy);
  const caps = Object.entries(merged.max_values ?? {});
  const capSummary =
    caps.length > 0 ? caps.map(([field, cap]) => `${field} <= ${cap}`).join(", ") : "No caps";

  return (
    <div className="max-w-[280px] text-xs text-muted-foreground">
      <p className="truncate">Allowed: {merged.allowed_keys.join(", ") || "None"}</p>
      <p className="truncate">{capSummary}</p>
    </div>
  );
}

function DefaultPolicyPreview() {
  return (
    <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
      <div className="rounded-md border border-border/60 bg-muted/20 p-2">
        <p className="font-medium text-foreground">Limits</p>
        <p className="mt-1">
          {DEFAULT_LIMITS.requests_per_minute}/min, {DEFAULT_LIMITS.jobs_per_day}/day,{" "}
          {DEFAULT_LIMITS.concurrent_jobs} concurrent
        </p>
      </div>
      <div className="rounded-md border border-border/60 bg-muted/20 p-2">
        <p className="font-medium text-foreground">Policy</p>
        <p className="mt-1">Allowed keys: {DEFAULT_POLICY.allowed_keys.join(", ")}</p>
      </div>
    </div>
  );
}

export default function AccessAdminApiKeysPage() {
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const fetchWorkspaces = useWorkspaceStore((state) => state.fetchWorkspaces);
  const { hasWorkspacePermission, isSuperuser, isWorkspaceAdmin } = usePermissions();
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<number | null>(currentWorkspaceId);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("Balancer API");
  const [createWorkspaceId, setCreateWorkspaceId] = useState<number | null>(currentWorkspaceId);
  const [createExpiresAt, setCreateExpiresAt] = useState("");
  const [oneTimeKey, setOneTimeKey] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<AccountApiKey | null>(null);
  const [renameName, setRenameName] = useState("");
  const [revokeTarget, setRevokeTarget] = useState<AccountApiKey | null>(null);
  const [counts, setCounts] = useState<AccountApiKeyStatusCounts>(EMPTY_COUNTS);

  useEffect(() => {
    if (workspaces.length === 0) {
      void fetchWorkspaces();
    }
  }, [fetchWorkspaces, workspaces.length]);

  const manageableWorkspaces = workspaces.filter(
    (workspace) =>
      isSuperuser ||
      isWorkspaceAdmin(workspace.id) ||
      hasWorkspacePermission(workspace.id, "team.import")
  );
  const selectedWorkspaceIsManageable =
    selectedWorkspaceId !== null &&
    manageableWorkspaces.some((workspace) => workspace.id === selectedWorkspaceId);
  const currentWorkspaceIsManageable =
    currentWorkspaceId !== null &&
    manageableWorkspaces.some((workspace) => workspace.id === currentWorkspaceId);
  const createWorkspaceIsManageable =
    createWorkspaceId !== null &&
    manageableWorkspaces.some((workspace) => workspace.id === createWorkspaceId);
  const effectiveSelectedWorkspaceId = selectedWorkspaceIsManageable
    ? selectedWorkspaceId
    : currentWorkspaceIsManageable
      ? currentWorkspaceId
      : (manageableWorkspaces[0]?.id ?? null);
  const effectiveCreateWorkspaceId = createWorkspaceIsManageable
    ? createWorkspaceId
    : effectiveSelectedWorkspaceId;
  const selectedWorkspace =
    manageableWorkspaces.find((workspace) => workspace.id === effectiveSelectedWorkspaceId) ?? null;

  const createMutation = useCreateAccountApiKey();
  const renameMutation = useRenameAccountApiKey(effectiveSelectedWorkspaceId);
  const revokeMutation = useRevokeAccountApiKey(effectiveSelectedWorkspaceId);

  const openRenameDialog = (apiKey: AccountApiKey) => {
    setRenameTarget(apiKey);
    setRenameName(apiKey.name);
  };

  const handleCreate = () => {
    if (effectiveCreateWorkspaceId === null || createName.trim().length === 0) return;

    createMutation.mutate(
      {
        workspace_id: effectiveCreateWorkspaceId,
        expires_at: toIsoTimestamp(createExpiresAt),
        name: createName.trim()
      },
      {
        onSuccess: (result) => {
          setOneTimeKey(result.key);
          setSelectedWorkspaceId(result.api_key.workspace_id);
          setCreateWorkspaceId(result.api_key.workspace_id);
          setCreateExpiresAt("");
          setCreateName("Balancer API");
          setIsCreateOpen(false);
          notify.success("API key created", {
            description: "Copy the secret now. It will not be shown again."
          });
        }
      }
    );
  };

  const handleRename = () => {
    if (!renameTarget || renameName.trim().length === 0) return;

    renameMutation.mutate(
      { id: renameTarget.id, name: renameName.trim() },
      {
        onSuccess: () => {
          setRenameTarget(null);
          setRenameName("");
          notify.success("API key renamed");
        }
      }
    );
  };

  const handleRevoke = () => {
    if (!revokeTarget) return;

    revokeMutation.mutate(revokeTarget.id, {
      onSuccess: () => {
        setRevokeTarget(null);
        notify.success("API key revoked");
      }
    });
  };

  const copyOneTimeKey = async () => {
    if (!oneTimeKey) return;
    await navigator.clipboard.writeText(oneTimeKey);
    notify.success("API key copied");
  };

  const columns: ColumnDef<AccountApiKey>[] = [
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ row }) => {
        const apiKey = row.original;
        return (
          <div className="flex min-w-0 items-center gap-2">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border/60 bg-muted/20">
              <KeyRound className="size-4 text-muted-foreground" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">{apiKey.name}</p>
              <p className="truncate font-mono text-xs text-muted-foreground">
                aqt_sk_{apiKey.public_id}_...
              </p>
            </div>
          </div>
        );
      }
    },
    {
      id: "status",
      header: "Status",
      enableSorting: false,
      cell: ({ row }) => <StatusCell status={getApiKeyStatus(row.original)} />
    },
    {
      accessorKey: "created_at",
      header: "Created",
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">{formatTimestamp(row.original.created_at)}</span>
      )
    },
    {
      accessorKey: "last_used_at",
      header: "Last Used",
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">
          {formatTimestamp(row.original.last_used_at)}
        </span>
      )
    },
    {
      accessorKey: "expires_at",
      header: "Expires",
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">{formatTimestamp(row.original.expires_at)}</span>
      )
    },
    {
      id: "limits",
      header: "Limits",
      enableSorting: false,
      cell: ({ row }) => <LimitsText limits={row.original.limits} />
    },
    {
      id: "policy",
      header: "Policy",
      enableSorting: false,
      cell: ({ row }) => <PolicyText policy={row.original.config_policy} />
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => {
        const apiKey = row.original;
        if (getApiKeyStatus(apiKey) !== "active") {
          return <span className="text-xs text-muted-foreground/60">No actions</span>;
        }
        return (
          <div className="flex justify-end gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="size-8 rounded-md"
              disabled={renameMutation.isPending || revokeMutation.isPending}
              onClick={() => openRenameDialog(apiKey)}
            >
              <Pencil className="size-4" />
              <span className="sr-only">Rename API key</span>
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="size-8 rounded-md text-destructive hover:text-destructive"
              disabled={revokeMutation.isPending}
              onClick={() => setRevokeTarget(apiKey)}
            >
              <Trash2 className="size-4" />
              <span className="sr-only">Revoke API key</span>
            </Button>
          </div>
        );
      }
    }
  ];

  if (manageableWorkspaces.length === 0) {
    return (
      <div className="space-y-4">
        <AdminPageHeader
          title="API Keys"
          description="Manage workspace-scoped credentials for the balancer public API."
        />
        <div className="rounded-lg border border-dashed border-border/70 px-4 py-6 text-sm text-muted-foreground">
          No workspaces are available for API keys.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <AdminPageHeader
        title="API Keys"
        description="Manage workspace-scoped credentials for the balancer public API."
        actions={
          <Button onClick={() => setIsCreateOpen(true)}>
            <Plus className="size-4" />
            Create key
          </Button>
        }
      />

      <div className="rounded-xl border border-border/50 bg-card/50">
        <div className="flex flex-col gap-3 border-b border-border/40 p-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="w-full space-y-1.5 lg:max-w-xs">
            <label className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
              Workspace
            </label>
            <Select
              value={
                effectiveSelectedWorkspaceId !== null
                  ? String(effectiveSelectedWorkspaceId)
                  : undefined
              }
              onValueChange={(value) => {
                const nextWorkspaceId = Number(value);
                setSelectedWorkspaceId(nextWorkspaceId);
                setCreateWorkspaceId(nextWorkspaceId);
              }}
            >
              <SelectTrigger className="h-9 bg-muted/20">
                <SelectValue placeholder="Select workspace" />
              </SelectTrigger>
              <SelectContent>
                {manageableWorkspaces.map((workspace) => (
                  <SelectItem key={workspace.id} value={String(workspace.id)}>
                    {workspace.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2 sm:grid-cols-4 lg:min-w-[520px]">
            <Metric label="Workspace" value={selectedWorkspace?.name ?? "Selected"} />
            <Metric label="Active" value={counts.active} />
            <Metric label="Expired" value={counts.expired} />
            <Metric label="Revoked" value={counts.revoked} />
          </div>
        </div>

        {oneTimeKey ? (
          <div className="bg-emerald-500/5 px-3 py-3">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">One-time secret</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  This full API key is visible only once.
                </p>
                <code className="mt-2 block overflow-x-auto rounded-md border border-emerald-500/20 bg-background/80 p-2 text-xs text-emerald-700 dark:text-emerald-300">
                  {oneTimeKey}
                </code>
              </div>
              <div className="flex shrink-0 gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 rounded-md"
                  onClick={() => void copyOneTimeKey()}
                >
                  <Clipboard className="size-4" />
                  Copy
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8 rounded-md"
                  onClick={() => setOneTimeKey(null)}
                >
                  <X className="size-4" />
                  <span className="sr-only">Dismiss secret</span>
                </Button>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <AdminDataTable
        initialPageSize={PAGE_SIZE}
        pageSizeOptions={[10, 20, 50, 100]}
        queryKey={(page, search, pageSize, sortField, sortDir) => [
          "account",
          "api-keys",
          effectiveSelectedWorkspaceId,
          page,
          search,
          pageSize,
          sortField,
          sortDir
        ]}
        queryFn={async (page, search, pageSize, sortField, sortDir) => {
          if (effectiveSelectedWorkspaceId === null) {
            return { results: [], total: 0, page: 1, per_page: pageSize };
          }
          const result = await fetchAccountApiKeys({
            workspaceId: effectiveSelectedWorkspaceId,
            page,
            perPage: pageSize,
            sort: sortField ?? undefined,
            order: sortDir,
            search: search || undefined
          });
          setCounts(result.counts);
          return result;
        }}
        columns={columns}
        searchPlaceholder="Search by name..."
        emptyMessage="No API keys for this workspace."
      />

      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="max-w-md rounded-xl">
          <DialogHeader>
            <DialogTitle>Create API key</DialogTitle>
            <DialogDescription>
              The key is scoped to one workspace and can use the balancer public API.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
                Name
              </label>
              <Input
                value={createName}
                onChange={(event) => setCreateName(event.target.value)}
                maxLength={100}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
                Workspace
              </label>
              <Select
                value={
                  effectiveCreateWorkspaceId !== null
                    ? String(effectiveCreateWorkspaceId)
                    : undefined
                }
                onValueChange={(value) => setCreateWorkspaceId(Number(value))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select workspace" />
                </SelectTrigger>
                <SelectContent>
                  {manageableWorkspaces.map((workspace) => (
                    <SelectItem key={workspace.id} value={String(workspace.id)}>
                      {workspace.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
            <DefaultPolicyPreview />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsCreateOpen(false)}
              disabled={createMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={
                createMutation.isPending ||
                effectiveCreateWorkspaceId === null ||
                createName.trim().length === 0
              }
            >
              {createMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Plus className="size-4" />
              )}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={renameTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setRenameTarget(null);
            setRenameName("");
          }
        }}
      >
        <DialogContent className="max-w-md rounded-xl">
          <DialogHeader>
            <DialogTitle>Rename API key</DialogTitle>
            <DialogDescription>Update the display name used in this admin list.</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
              Name
            </label>
            <Input
              value={renameName}
              onChange={(event) => setRenameName(event.target.value)}
              maxLength={100}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setRenameTarget(null);
                setRenameName("");
              }}
              disabled={renameMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              onClick={handleRename}
              disabled={renameMutation.isPending || renameName.trim().length === 0}
            >
              {renameMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Check className="size-4" />
              )}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={revokeTarget !== null}
        onOpenChange={(open) => !open && setRevokeTarget(null)}
      >
        <AlertDialogContent className="rounded-xl">
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke API key?</AlertDialogTitle>
            <AlertDialogDescription>
              Existing requests with this key will stop validating. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={revokeMutation.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={revokeMutation.isPending}
              onClick={handleRevoke}
            >
              {revokeMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Trash2 className="size-4" />
              )}
              Revoke
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
