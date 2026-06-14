"use client";

import { createElement, useMemo, useState } from "react";
import { Check, ChevronsUpDown, Pipette, Plus, Pencil, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import StatusMetaBadge from "@/components/status/StatusMetaBadge";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { getStatusIcon, STATUS_ICON_OPTIONS } from "@/lib/status-icons";
import { mergeStatusOptions } from "@/lib/balancer-statuses";
import { cn } from "@/lib/utils";
import balancerAdminService from "@/services/balancer-admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type {
  BalancerCustomStatus,
  BalancerCustomStatusCreateInput,
  BalancerCustomStatusUpdateInput,
  StatusScope
} from "@/types/balancer-admin.types";

type StatusFormState = {
  scope: StatusScope;
  icon_slug: string;
  icon_color: string;
  name: string;
  description: string;
};

const EMPTY_FORM: StatusFormState = {
  scope: "registration",
  icon_slug: "",
  icon_color: "",
  name: "",
  description: ""
};

const STATUS_COLOR_PRESETS = [
  "#94a3b8",
  "#64748b",
  "#ef4444",
  "#f97316",
  "#f59e0b",
  "#eab308",
  "#84cc16",
  "#22c55e",
  "#10b981",
  "#14b8a6",
  "#06b6d4",
  "#38bdf8",
  "#3b82f6",
  "#6366f1",
  "#8b5cf6",
  "#ec4899"
];

function normalizeHexColor(value: string): string {
  const normalized = value.trim();
  if (!normalized) {
    return "";
  }
  return normalized.startsWith("#") ? normalized : `#${normalized}`;
}

function StatusColorPicker({
  value,
  onChange
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const normalizedValue = normalizeHexColor(value) || "#94a3b8";

  return (
    <div className="space-y-2">
      <Label>Icon color</Label>
      <Popover open={open} onOpenChange={setOpen} modal={false}>
        <PopoverTrigger asChild>
          <Button variant="outline" className="w-full justify-between">
            <span className="flex min-w-0 items-center gap-3">
              <span
                className="size-5 shrink-0 rounded-md border border-border shadow-sm"
                style={{ backgroundColor: normalizedValue }}
              />
              <span className="truncate font-mono text-xs uppercase">
                {normalizeHexColor(value) || "Default"}
              </span>
            </span>
            <Pipette className="ml-2 size-4 shrink-0 opacity-60" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="z-[60] w-[var(--radix-popover-trigger-width)] min-w-[var(--radix-popover-trigger-width)] space-y-4"
          onWheelCapture={(event) => event.stopPropagation()}
          onTouchMove={(event) => event.stopPropagation()}
        >
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
              Presets
            </p>
            <div className="flex flex-wrap gap-2">
              {STATUS_COLOR_PRESETS.map((color) => (
                <button
                  key={color}
                  type="button"
                  className={cn(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border transition hover:scale-[1.03]",
                    normalizeHexColor(value).toLowerCase() === color.toLowerCase() &&
                      "ring-2 ring-ring ring-offset-2 ring-offset-background"
                  )}
                  style={{ backgroundColor: color }}
                  onClick={() => onChange(color)}
                  aria-label={`Pick ${color}`}
                >
                  {normalizeHexColor(value).toLowerCase() === color.toLowerCase() ? (
                    <Check className="size-3.5 text-white drop-shadow" />
                  ) : null}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
              Custom
            </p>
            <div className="flex items-center gap-2">
              <label className="flex h-10 w-12 cursor-pointer items-center justify-center rounded-md border border-input bg-background shadow-sm">
                <input
                  type="color"
                  className="sr-only"
                  value={normalizedValue}
                  onChange={(event) => onChange(event.target.value)}
                />
                <span
                  className="size-6 rounded-md border border-border"
                  style={{ backgroundColor: normalizedValue }}
                />
              </label>
              <Input
                value={value}
                onChange={(event) => onChange(normalizeHexColor(event.target.value))}
                placeholder="#38bdf8"
                className="font-mono uppercase"
              />
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

function StatusForm({
  value,
  onChange,
  disableScope = false
}: {
  value: StatusFormState;
  onChange: (next: StatusFormState) => void;
  disableScope?: boolean;
}) {
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  const previewMeta = useMemo(
    () => ({
      value: value.name || "preview",
      scope: value.scope,
      is_builtin: false,
      kind: "custom" as const,
      is_override: false,
      can_edit: true,
      can_delete: true,
      can_reset: false,
      icon_slug: value.icon_slug || "BadgeHelp",
      icon_color: value.icon_color || null,
      name: value.name || "Preview",
      description: value.description || null
    }),
    [value]
  );
  const selectedIconSlug = value.icon_slug || "BadgeHelp";
  const selectedIcon = createElement(getStatusIcon(selectedIconSlug), {
    className: "size-4",
    style: value.icon_color ? { color: value.icon_color } : undefined
  });

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="status-scope">Scope</Label>
          <Select
            value={value.scope}
            onValueChange={(nextScope) => onChange({ ...value, scope: nextScope as StatusScope })}
          >
            <SelectTrigger id="status-scope" disabled={disableScope}>
              <SelectValue placeholder="Select scope" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="registration">Registration</SelectItem>
              <SelectItem value="balancer">Balancer</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="status-name">Name</Label>
          <Input
            id="status-name"
            value={value.name}
            onChange={(event) => onChange({ ...value, name: event.target.value })}
            placeholder="Awaiting captain"
          />
        </div>
        <div className="space-y-2">
          <Label>Icon</Label>
          <Popover open={iconPickerOpen} onOpenChange={setIconPickerOpen} modal={false}>
            <PopoverTrigger asChild>
              <Button variant="outline" role="combobox" className="w-full justify-between">
                <span className="flex min-w-0 items-center gap-2">
                  {selectedIcon}
                  <span className="truncate">{selectedIconSlug}</span>
                </span>
                <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
              </Button>
            </PopoverTrigger>
            <PopoverContent
              className="z-[60] w-[var(--radix-popover-trigger-width)] min-w-[var(--radix-popover-trigger-width)] p-0"
              align="start"
              onWheelCapture={(event) => event.stopPropagation()}
              onTouchMove={(event) => event.stopPropagation()}
            >
              <Command>
                <CommandInput placeholder="Search icon..." />
                <CommandList
                  className="max-h-[260px]"
                  onWheelCapture={(event) => event.stopPropagation()}
                  onTouchMove={(event) => event.stopPropagation()}
                >
                  <CommandEmpty>No icon found.</CommandEmpty>
                  <CommandGroup>
                    {STATUS_ICON_OPTIONS.map(({ slug, Icon }) => (
                      <CommandItem
                        key={slug}
                        value={slug}
                        onSelect={(nextSlug) => {
                          onChange({ ...value, icon_slug: nextSlug });
                          setIconPickerOpen(false);
                        }}
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <Icon
                            className="size-4"
                            style={value.icon_color ? { color: value.icon_color } : undefined}
                          />
                          <span className="truncate">{slug}</span>
                        </span>
                        <Check
                          className={cn(
                            "ml-auto size-4",
                            value.icon_slug === slug ? "opacity-100" : "opacity-0"
                          )}
                        />
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
        </div>
        <StatusColorPicker
          value={value.icon_color}
          onChange={(nextColor) => onChange({ ...value, icon_color: nextColor })}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="status-description">Description</Label>
        <Textarea
          id="status-description"
          value={value.description}
          onChange={(event) => onChange({ ...value, description: event.target.value })}
          placeholder="Used when a player is waiting for a captain confirmation."
        />
      </div>
      <div className="space-y-2">
        <Label>Preview</Label>
        <div className="rounded-lg border p-3">
          <StatusMetaBadge meta={previewMeta} fallbackValue="preview" />
        </div>
      </div>
    </div>
  );
}

export default function AdminBalancerPage() {
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const { canAccessPermission } = usePermissions();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [editingStatus, setEditingStatus] = useState<BalancerCustomStatus | null>(null);
  const [deletingStatus, setDeletingStatus] = useState<BalancerCustomStatus | null>(null);
  const [form, setForm] = useState<StatusFormState>(EMPTY_FORM);
  const canManageStatuses = canAccessPermission("team.import", workspaceId);

  const statusesQuery = useQuery({
    queryKey: ["balancer-admin", "status-catalog", workspaceId],
    queryFn: () => balancerAdminService.listStatusCatalog(workspaceId as number),
    enabled: workspaceId !== null
  });

  const invalidateStatuses = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["balancer-admin", "status-catalog", workspaceId]
    });
  };

  const createMutation = useMutation({
    mutationFn: (data: BalancerCustomStatusCreateInput) =>
      balancerAdminService.createCustomStatus(workspaceId as number, data),
    onSuccess: async () => {
      await invalidateStatuses();
      setCreateOpen(false);
      setForm(EMPTY_FORM);
      notify.success("Custom status created");
    }
  });

  const updateMutation = useMutation({
    mutationFn: ({ statusId, data }: { statusId: number; data: BalancerCustomStatusUpdateInput }) =>
      balancerAdminService.updateCustomStatus(workspaceId as number, statusId, data),
    onSuccess: async () => {
      await invalidateStatuses();
      setEditingStatus(null);
      setForm(EMPTY_FORM);
      notify.success("Custom status updated");
    }
  });

  const updateBuiltinMutation = useMutation({
    mutationFn: ({
      scope,
      slug,
      data
    }: {
      scope: StatusScope;
      slug: string;
      data: BalancerCustomStatusUpdateInput;
    }) =>
      balancerAdminService.upsertBuiltinStatusOverride(workspaceId as number, scope, slug, data),
    onSuccess: async () => {
      await invalidateStatuses();
      setEditingStatus(null);
      setForm(EMPTY_FORM);
      notify.success("System status updated");
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (statusId: number) =>
      balancerAdminService.deleteCustomStatus(workspaceId as number, statusId),
    onSuccess: async () => {
      await invalidateStatuses();
      setDeletingStatus(null);
      notify.success("Custom status deleted");
    }
  });

  const resetBuiltinMutation = useMutation({
    mutationFn: ({ scope, slug }: { scope: StatusScope; slug: string }) =>
      balancerAdminService.resetBuiltinStatusOverride(workspaceId as number, scope, slug),
    onSuccess: async () => {
      await invalidateStatuses();
      setDeletingStatus(null);
      notify.success("System status reset");
    }
  });

  const grouped = useMemo(() => {
    const rows = statusesQuery.data ?? [];
    return {
      registration: {
        system: rows.filter((row) => row.scope === "registration" && row.kind === "builtin"),
        custom: rows.filter((row) => row.scope === "registration" && row.kind === "custom")
      },
      balancer: {
        system: rows.filter((row) => row.scope === "balancer" && row.kind === "builtin"),
        custom: rows.filter((row) => row.scope === "balancer" && row.kind === "custom")
      },
      options: {
        registration: mergeStatusOptions("registration", rows),
        balancer: mergeStatusOptions("balancer", rows)
      }
    };
  }, [statusesQuery.data]);

  const openCreate = (scope: StatusScope) => {
    setForm({ ...EMPTY_FORM, scope });
    setCreateOpen(true);
  };

  const openEdit = (statusRow: BalancerCustomStatus) => {
    setEditingStatus(statusRow);
    setForm({
      scope: statusRow.scope,
      icon_slug: statusRow.icon_slug ?? "",
      icon_color: statusRow.icon_color ?? "",
      name: statusRow.name,
      description: statusRow.description ?? ""
    });
  };

  if (workspaceId === null) {
    return (
      <div className="space-y-6">
        <AdminPageHeader
          title="Balancer"
          description="Select a workspace to manage custom balancer statuses."
        />
        <Card>
          <CardContent className="pt-6 text-sm text-muted-foreground">
            No workspace selected.
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <AdminPageHeader
        title="Balancer"
        description="Manage workspace-specific custom statuses for registration and balancer flows."
      />

      <div className="grid gap-6 xl:grid-cols-2">
        {(["registration", "balancer"] as const).map((scope) => (
          <Card key={scope}>
            <CardHeader className="flex flex-row items-start justify-between gap-3">
              <div>
                <CardTitle>
                  {scope === "registration" ? "Registration statuses" : "Balancer statuses"}
                </CardTitle>
                <CardDescription>
                  Built-in statuses stay system-controlled. Custom statuses add extra labels for
                  this workspace.
                </CardDescription>
              </div>
              <Button size="sm" onClick={() => openCreate(scope)} disabled={!canManageStatuses}>
                <Plus className="mr-2 size-4" />
                Add
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  System
                </p>
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Status</TableHead>
                        <TableHead>Slug</TableHead>
                        <TableHead>Description</TableHead>
                        <TableHead className="w-[120px] text-right">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {grouped[scope].system.map((statusRow) => (
                        <TableRow key={`${statusRow.scope}-${statusRow.slug}`}>
                          <TableCell>
                            <StatusMetaBadge
                              meta={{
                                value: statusRow.slug,
                                scope: statusRow.scope,
                                is_builtin: true,
                                kind: "builtin",
                                is_override: statusRow.is_override,
                                can_edit: true,
                                can_delete: false,
                                can_reset: statusRow.can_reset,
                                icon_slug: statusRow.icon_slug,
                                icon_color: statusRow.icon_color,
                                name: statusRow.name,
                                description: statusRow.description
                              }}
                              fallbackValue={statusRow.slug}
                            />
                          </TableCell>
                          <TableCell className="font-mono text-xs">{statusRow.slug}</TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {statusRow.description ?? "-"}
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="flex justify-end gap-2">
                              <Button
                                size="icon"
                                variant="ghost"
                                onClick={() => openEdit(statusRow)}
                                disabled={!canManageStatuses}
                              >
                                <Pencil className="size-4" />
                              </Button>
                              {statusRow.can_reset ? (
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  onClick={() => setDeletingStatus(statusRow)}
                                  disabled={!canManageStatuses}
                                >
                                  <Trash2 className="size-4" />
                                </Button>
                              ) : null}
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>
              <div className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Custom
                </p>
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Status</TableHead>
                        <TableHead>Slug</TableHead>
                        <TableHead>Description</TableHead>
                        <TableHead className="w-[120px] text-right">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {grouped[scope].custom.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={4} className="text-sm text-muted-foreground">
                            No custom statuses yet.
                          </TableCell>
                        </TableRow>
                      ) : (
                        grouped[scope].custom.map((statusRow) => (
                          <TableRow key={statusRow.id}>
                            <TableCell>
                              <StatusMetaBadge
                                meta={{
                                  value: statusRow.slug,
                                  scope: statusRow.scope,
                                  is_builtin: false,
                                  kind: "custom",
                                  is_override: false,
                                  can_edit: true,
                                  can_delete: true,
                                  can_reset: false,
                                  icon_slug: statusRow.icon_slug,
                                  icon_color: statusRow.icon_color,
                                  name: statusRow.name,
                                  description: statusRow.description
                                }}
                                fallbackValue={statusRow.slug}
                              />
                            </TableCell>
                            <TableCell className="font-mono text-xs">{statusRow.slug}</TableCell>
                            <TableCell className="text-sm text-muted-foreground">
                              {statusRow.description ?? "-"}
                            </TableCell>
                            <TableCell className="text-right">
                              <div className="flex justify-end gap-2">
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  onClick={() => openEdit(statusRow)}
                                  disabled={!canManageStatuses}
                                >
                                  <Pencil className="size-4" />
                                </Button>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  onClick={() => setDeletingStatus(statusRow)}
                                  disabled={!canManageStatuses}
                                >
                                  <Trash2 className="size-4" />
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create custom status</DialogTitle>
            <DialogDescription>
              The slug is generated automatically from the name and stays stable after edits.
            </DialogDescription>
          </DialogHeader>
          <StatusForm value={form} onChange={setForm} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                createMutation.mutate({
                  scope: form.scope,
                  icon_slug: form.icon_slug || null,
                  icon_color: form.icon_color || null,
                  name: form.name,
                  description: form.description || null
                })
              }
              disabled={createMutation.isPending || !form.name.trim() || !canManageStatuses}
            >
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={editingStatus !== null}
        onOpenChange={(open) => {
          if (!open) {
            setEditingStatus(null);
            setForm(EMPTY_FORM);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingStatus?.kind === "builtin" ? "Edit system status" : "Edit custom status"}
            </DialogTitle>
            <DialogDescription>
              {editingStatus?.kind === "builtin"
                ? "Save a workspace override for this system status without changing its slug or workflow."
                : "Update visual metadata without changing the stored slug."}
            </DialogDescription>
          </DialogHeader>
          <StatusForm value={form} onChange={setForm} disableScope />
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingStatus(null)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (!editingStatus) return;
                const data = {
                  icon_slug: form.icon_slug || null,
                  icon_color: form.icon_color || null,
                  name: form.name,
                  description: form.description || null
                };
                if (editingStatus.kind === "builtin") {
                  updateBuiltinMutation.mutate({
                    scope: editingStatus.scope,
                    slug: editingStatus.slug,
                    data
                  });
                  return;
                }
                updateMutation.mutate({
                  statusId: editingStatus.id,
                  data
                });
              }}
              disabled={
                updateMutation.isPending ||
                updateBuiltinMutation.isPending ||
                !form.name.trim() ||
                !canManageStatuses
              }
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={deletingStatus !== null}
        onOpenChange={(open) => !open && setDeletingStatus(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {deletingStatus?.kind === "builtin" ? "Reset system status" : "Delete custom status"}
            </DialogTitle>
            <DialogDescription>
              {deletingStatus?.kind === "builtin"
                ? "This removes the workspace override and restores the default built-in appearance."
                : "This only removes the catalog entry. Used statuses are protected by the backend and will return an error."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeletingStatus(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (!deletingStatus) return;
                if (deletingStatus.kind === "builtin") {
                  resetBuiltinMutation.mutate({
                    scope: deletingStatus.scope,
                    slug: deletingStatus.slug
                  });
                  return;
                }
                deleteMutation.mutate(deletingStatus.id);
              }}
              disabled={
                deleteMutation.isPending || resetBuiltinMutation.isPending || !canManageStatuses
              }
            >
              {deletingStatus?.kind === "builtin" ? "Reset" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
