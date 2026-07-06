"use client";

import { useState, type CSSProperties } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ColumnDef } from "@tanstack/react-table";
import { Plus, Pencil, Trash2, CheckCircle, XCircle } from "lucide-react";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import { notify } from "@/lib/notify";
import { usePermissions } from "@/hooks/usePermissions";
import { hasUnsavedChanges } from "@/lib/form-change";
import { deriveWorkspacePalette } from "@/lib/workspace-theme";
import { PLATFORM_ZONE } from "@/lib/host";
import workspaceService from "@/services/workspace.service";
import { Workspace } from "@/types/workspace.types";
import { useWorkspaceStore } from "@/stores/workspace.store";

interface WorkspaceFormData {
  slug: string;
  name: string;
  description: string;
}

interface WorkspaceUpdateFormData {
  name?: string;
  description?: string;
  is_active?: boolean;
  branding_enabled?: boolean;
  brand_primary?: string | null;
  brand_secondary?: string | null;
  brand_background?: string | null;
  brand_surface?: string | null;
  subdomain?: string | null;
  seo_title?: string | null;
  seo_description?: string | null;
}

function BrandColorField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string | null | undefined;
  onChange: (value: string) => void;
}) {
  const hex = value ?? "";
  const valid = /^#[0-9a-fA-F]{6}$/.test(hex);
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <div className="mt-1 flex items-center gap-2">
        <input
          type="color"
          aria-label={`${label} color`}
          value={valid ? hex : "#000000"}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 w-10 shrink-0 cursor-pointer rounded border border-input bg-transparent p-0.5"
        />
        <Input
          id={id}
          value={hex}
          onChange={(e) => onChange(e.target.value)}
          placeholder="#000000"
          className="font-mono"
        />
      </div>
    </div>
  );
}

const emptyForm: WorkspaceFormData = {
  slug: "",
  name: "",
  description: ""
};

const ACCEPTED_IMAGE_TYPES = "image/webp,image/png,image/jpeg,image/gif";
const MAX_FILE_SIZE = 2 * 1024 * 1024; // 2 MB

export default function WorkspacesPage() {
  const { isSuperuser, isWorkspaceAdmin } = usePermissions();
  const queryClient = useQueryClient();
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces);

  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [selected, setSelected] = useState<Workspace | null>(null);
  const [formData, setFormData] = useState<WorkspaceFormData | WorkspaceUpdateFormData>({
    ...emptyForm
  });
  const [iconFile, setIconFile] = useState<File | null>(null);
  const [iconPreview, setIconPreview] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["admin-workspaces"] });
    fetchWorkspaces();
  };

  const createMutation = useMutation({
    mutationFn: async (data: WorkspaceFormData) => {
      const ws = await workspaceService.create({
        slug: data.slug,
        name: data.name,
        description: data.description || undefined
      });
      if (iconFile) {
        await workspaceService.uploadIcon(ws.id, iconFile);
      }
      return ws;
    },
    onSuccess: () => {
      invalidate();
      setCreateOpen(false);
      setFormData({ ...emptyForm });
      setIconFile(null);
      setIconPreview(null);
      notify.success("Workspace created");
    }
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: WorkspaceUpdateFormData }) => {
      await workspaceService.update(id, data);
      if (iconFile) {
        await workspaceService.uploadIcon(id, iconFile);
      }
    },
    onSuccess: () => {
      invalidate();
      setEditOpen(false);
      setIconFile(null);
      setIconPreview(null);
      notify.success("Workspace updated");
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) =>
      fetch(`/api/v1/workspaces/${id}`, { method: "DELETE" }).then((r) => {
        if (!r.ok) throw new Error("Failed to delete");
      }),
    onSuccess: () => {
      invalidate();
      setDeleteOpen(false);
      notify.success("Workspace deleted");
    }
  });

  const uploadIconMutation = useMutation({
    mutationFn: ({ id, file }: { id: number; file: File }) => workspaceService.uploadIcon(id, file),
    onSuccess: () => {
      invalidate();
      notify.success("Icon uploaded");
    }
  });

  const deleteIconMutation = useMutation({
    mutationFn: (id: number) => workspaceService.deleteIcon(id),
    onSuccess: () => {
      invalidate();
      setIconPreview(null);
      notify.success("Icon removed");
    }
  });

  const handleCreate = () => {
    setFormData({ ...emptyForm });
    setIconFile(null);
    setIconPreview(null);
    setCreateOpen(true);
  };

  const handleEdit = (ws: Workspace) => {
    setSelected(ws);
    setFormData({
      name: ws.name,
      description: ws.description || "",
      branding_enabled: ws.branding_enabled,
      brand_primary: ws.brand_primary,
      brand_secondary: ws.brand_secondary,
      brand_background: ws.brand_background,
      brand_surface: ws.brand_surface,
      subdomain: ws.subdomain,
      seo_title: ws.seo_title,
      seo_description: ws.seo_description,
    });
    setIconFile(null);
    setIconPreview(ws.icon_url || null);
    setEditOpen(true);
  };

  const handleIconSelect = (file: File) => {
    setIconFile(file);
    setIconPreview(URL.createObjectURL(file));
  };

  const handleDelete = (ws: Workspace) => {
    setSelected(ws);
    setDeleteOpen(true);
  };

  const isCreateDirty = createOpen && (hasUnsavedChanges(formData, emptyForm) || iconFile !== null);

  const columns: ColumnDef<Workspace>[] = [
    {
      accessorKey: "id",
      header: "ID",
      cell: ({ row }) => <div className="font-mono text-xs">{row.getValue("id")}</div>
    },
    {
      id: "icon",
      header: "Icon",
      cell: ({ row }) => {
        const ws = row.original;
        return ws.icon_url ? (
          <img src={ws.icon_url} alt={ws.name} className="h-8 w-8 rounded-md border object-cover" />
        ) : (
          <div className="h-8 w-8 rounded-md border bg-muted flex items-center justify-center text-muted-foreground text-xs font-medium">
            {ws.name.charAt(0).toUpperCase()}
          </div>
        );
      }
    },
    {
      accessorKey: "slug",
      header: "Slug",
      cell: ({ row }) => <code className="text-xs">{row.getValue("slug")}</code>
    },
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ row }) => <div className="font-medium">{row.getValue("name")}</div>
    },
    {
      accessorKey: "is_active",
      header: "Status",
      cell: ({ row }) =>
        row.getValue("is_active") ? (
          <StatusIcon icon={CheckCircle} label="Active" variant="success" />
        ) : (
          <StatusIcon icon={XCircle} label="Inactive" variant="muted" />
        )
    },
    {
      id: "actions",
      cell: ({ row }) => {
        const ws = row.original;
        const canManage = isSuperuser || isWorkspaceAdmin(ws.id);
        if (!canManage) return null;

        return (
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" onClick={() => handleEdit(ws)} aria-label="Edit">
              <Pencil className="h-4 w-4" />
            </Button>
            {isSuperuser ? (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => handleDelete(ws)}
                className="text-destructive"
                aria-label="Delete"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            ) : null}
          </div>
        );
      }
    }
  ];

  const editForm = formData as WorkspaceUpdateFormData;
  const brandingPreview = deriveWorkspacePalette({
    branding_enabled: true,
    brand_primary: editForm.brand_primary ?? null,
    brand_secondary: editForm.brand_secondary ?? null,
    brand_background: editForm.brand_background ?? null,
    brand_surface: editForm.brand_surface ?? null,
  });

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        title="Workspaces"
        description="Manage workspaces for isolated tournament environments"
        actions={
          isSuperuser ? (
            <Button onClick={handleCreate}>
              <Plus className="mr-2 h-4 w-4" />
              Create Workspace
            </Button>
          ) : null
        }
      />

      <AdminDataTable
        queryKey={(page, search, pageSize, sortField, sortDir) => [
          "admin-workspaces",
          isSuperuser,
          page,
          search,
          pageSize,
          sortField,
          sortDir
        ]}
        queryFn={async () => {
          const all = await workspaceService.getAll();
          // Non-superusers only see workspaces they admin
          const visible = isSuperuser ? all : all.filter((ws) => isWorkspaceAdmin(ws.id));
          return {
            results: visible,
            total: visible.length,
            page: 1,
            per_page: visible.length
          };
        }}
        columns={columns}
        searchPlaceholder="Search workspaces..."
        emptyMessage="No workspaces found."
      />

      {/* Create Dialog */}
      <EntityFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="Create Workspace"
        description="Create a new isolated workspace for tournaments"
        onSubmit={(e) => {
          e.preventDefault();
          createMutation.mutate(formData as WorkspaceFormData);
        }}
        isSubmitting={createMutation.isPending}
        submittingLabel="Creating..."
        errorMessage={createMutation.isError ? createMutation.error.message : undefined}
        isDirty={isCreateDirty}
      >
        <div className="space-y-4">
          <div>
            <Label htmlFor="slug">Slug *</Label>
            <Input
              id="slug"
              value={(formData as WorkspaceFormData).slug ?? ""}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  slug: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "")
                })
              }
              placeholder="my-workspace"
              required
            />
            <p className="text-xs text-muted-foreground mt-1">
              URL-safe identifier (a-z, 0-9, -, _)
            </p>
          </div>
          <div>
            <Label htmlFor="name">Name *</Label>
            <Input
              id="name"
              value={formData.name ?? ""}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="My Workspace"
              required
            />
          </div>
          <div>
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              value={formData.description ?? ""}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="Optional description"
            />
          </div>
          <div>
            <Label>Icon</Label>
            <div className="mt-1.5">
              <EditableAvatar
                src={iconPreview}
                name={formData.name}
                size={64}
                shape="rounded"
                onSelectFile={handleIconSelect}
                onDelete={
                  iconPreview
                    ? () => {
                        setIconFile(null);
                        setIconPreview(null);
                      }
                    : undefined
                }
                accept={ACCEPTED_IMAGE_TYPES}
                maxSizeBytes={MAX_FILE_SIZE}
                onError={(message) => notify.error(message)}
              />
            </div>
            <p className="text-xs text-muted-foreground mt-1">PNG, JPEG, WebP or GIF, max 2 MB</p>
          </div>
        </div>
      </EntityFormDialog>

      {/* Edit Dialog */}
      <EntityFormDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        title="Edit Workspace"
        description={`Editing "${selected?.name}"`}
        onSubmit={(e) => {
          e.preventDefault();
          if (selected) {
            updateMutation.mutate({ id: selected.id, data: formData as WorkspaceUpdateFormData });
          }
        }}
        isSubmitting={updateMutation.isPending}
        submittingLabel="Saving..."
        errorMessage={updateMutation.isError ? updateMutation.error.message : undefined}
      >
        <div className="space-y-4">
          <div>
            <Label htmlFor="edit-name">Name</Label>
            <Input
              id="edit-name"
              value={formData.name ?? ""}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            />
          </div>
          <div>
            <Label htmlFor="edit-description">Description</Label>
            <Textarea
              id="edit-description"
              value={formData.description ?? ""}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            />
          </div>
          <div>
            <Label>Icon</Label>
            <div className="mt-1.5">
              <EditableAvatar
                src={iconPreview}
                name={formData.name}
                size={64}
                shape="rounded"
                busy={deleteIconMutation.isPending}
                onSelectFile={handleIconSelect}
                onDelete={
                  iconPreview
                    ? () => {
                        if (selected?.icon_url && !iconFile) {
                          deleteIconMutation.mutate(selected.id);
                        } else {
                          setIconFile(null);
                          setIconPreview(selected?.icon_url || null);
                        }
                      }
                    : undefined
                }
                accept={ACCEPTED_IMAGE_TYPES}
                maxSizeBytes={MAX_FILE_SIZE}
                onError={(message) => notify.error(message)}
              />
            </div>
            <p className="text-xs text-muted-foreground mt-1">PNG, JPEG, WebP or GIF, max 2 MB</p>
          </div>

          {/* Branding — applies to the main public site only */}
          <div className="space-y-3 rounded-md border p-3">
            <div className="flex items-center justify-between gap-4">
              <div>
                <Label htmlFor="branding-enabled">Site branding</Label>
                <p className="text-xs text-muted-foreground">
                  Custom palette for this workspace on the main site
                </p>
              </div>
              <Switch
                id="branding-enabled"
                checked={editForm.branding_enabled ?? false}
                onCheckedChange={(checked) =>
                  setFormData({ ...formData, branding_enabled: checked })
                }
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <BrandColorField
                id="brand-primary"
                label="Primary accent"
                value={editForm.brand_primary}
                onChange={(v) => setFormData({ ...formData, brand_primary: v })}
              />
              <BrandColorField
                id="brand-secondary"
                label="Secondary accent"
                value={editForm.brand_secondary}
                onChange={(v) => setFormData({ ...formData, brand_secondary: v })}
              />
              <BrandColorField
                id="brand-background"
                label="Background"
                value={editForm.brand_background}
                onChange={(v) => setFormData({ ...formData, brand_background: v })}
              />
              <BrandColorField
                id="brand-surface"
                label="Surface"
                value={editForm.brand_surface}
                onChange={(v) => setFormData({ ...formData, brand_surface: v })}
              />
            </div>

            {brandingPreview ? (
              <div
                className="rounded-md border p-3"
                style={{ ...brandingPreview, background: "var(--aqt-bg)" } as CSSProperties}
              >
                <div className="text-xs font-medium" style={{ color: "var(--aqt-fg)" }}>
                  Preview
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <span
                    className="rounded px-2 py-1 text-xs font-medium"
                    style={{
                      background: "var(--aqt-teal)",
                      color: "hsl(var(--primary-foreground))",
                    }}
                  >
                    Primary
                  </span>
                  <span
                    className="rounded px-2 py-1 text-xs font-medium"
                    style={{
                      background: "var(--aqt-violet)",
                      color: "hsl(var(--secondary-foreground))",
                    }}
                  >
                    Secondary
                  </span>
                  <span
                    className="rounded px-2 py-1 text-xs"
                    style={{
                      background: "var(--aqt-card)",
                      color: "var(--aqt-fg-muted)",
                      border: "1px solid var(--aqt-border)",
                    }}
                  >
                    Surface
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Set at least a primary accent and a background to preview. Backgrounds are
                clamped to a dark shade to keep text readable.
              </p>
            )}
          </div>

          {/* Domain & SEO — subdomain routing + public metadata */}
          <div className="space-y-3 rounded-md border p-3">
            <div>
              <Label htmlFor="edit-subdomain">Subdomain</Label>
              <Input
                id="edit-subdomain"
                value={editForm.subdomain ?? ""}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    subdomain: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "")
                  })
                }
                placeholder="my-team"
              />
              <p className="text-xs text-muted-foreground mt-1">
                {editForm.subdomain
                  ? `${editForm.subdomain}.${PLATFORM_ZONE}`
                  : "Leave blank to use the platform URL only"}
              </p>
            </div>
            <div>
              <Label htmlFor="edit-seo-title">SEO title</Label>
              <Input
                id="edit-seo-title"
                value={editForm.seo_title ?? ""}
                onChange={(e) => setFormData({ ...formData, seo_title: e.target.value })}
                placeholder="Displayed in browser tabs and search results"
              />
            </div>
            <div>
              <Label htmlFor="edit-seo-description">SEO description</Label>
              <Textarea
                id="edit-seo-description"
                value={editForm.seo_description ?? ""}
                onChange={(e) => setFormData({ ...formData, seo_description: e.target.value })}
                placeholder="Optional meta description shown in search results"
              />
            </div>
          </div>
        </div>
      </EntityFormDialog>

      {/* Delete Dialog */}
      <DeleteConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        onConfirm={() => selected && deleteMutation.mutate(selected.id)}
        title="Delete Workspace"
        description={`Are you sure you want to delete "${selected?.name}"? This will remove all tournaments and data in this workspace.`}
        cascadeInfo={[
          "All tournaments in this workspace",
          "All teams, players, matches, and statistics",
          "All workspace members"
        ]}
        isDeleting={deleteMutation.isPending}
      />
    </div>
  );
}
