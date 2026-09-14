"use client";

import { useId, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Archive,
  ArrowUpToLine,
  CircleDot,
  ExternalLink,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Trash2
} from "lucide-react";

import { AdminDataTable, adminColumnMeta, createKebabColumn } from "@/components/admin-data-table";
import { StatusIcon } from "@/components/admin/StatusIcon";
import {
  entityFormError,
  onEntityDialogClose
} from "@/components/admin/CatalogToolbarActions";
import { ConfirmDialog } from "@/components/admin/kit/ConfirmDialog";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { ApiError } from "@/lib/api-error";
import { hasUnsavedChanges } from "@/lib/form-change";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import streamService from "@/services/stream.service";
import type {
  TournamentLink,
  TournamentLinkCreateInput,
  TournamentLinkKind,
  TournamentLinkUpdateInput
} from "@/types/stream.types";
import { primaryStreamLinkSortOrder } from "./tournamentLinks.helpers";
import { EmptyNote } from "@/components/admin/kit/EmptyNote";

/** Mirrors `TOURNAMENT_LINK_KINDS` in `backend/shared/models/tournament/link.py`. */
const LINK_KINDS: ReadonlyArray<{ value: TournamentLinkKind; label: string }> = [
  { value: "discord", label: "Discord" },
  { value: "stream", label: "Stream" },
  { value: "vod", label: "VOD" },
  { value: "bracket", label: "Bracket" },
  { value: "rules", label: "Rules" },
  { value: "other", label: "Other" }
];

const KIND_LABELS: Record<TournamentLinkKind, string> = Object.fromEntries(
  LINK_KINDS.map((kind) => [kind.value, kind.label])
) as Record<TournamentLinkKind, string>;

interface LinkForm {
  kind: TournamentLinkKind;
  label: string;
  url: string;
  sort_order: number;
}

// Key order matters: `hasUnsavedChanges` compares JSON, so `getLinkForm` below
// must list the same fields in the same order or every edit dialog opens dirty.
const EMPTY_LINK_FORM: LinkForm = { kind: "discord", label: "", url: "", sort_order: 0 };

function getLinkForm(link: TournamentLink | null): LinkForm {
  if (!link) {
    return { ...EMPTY_LINK_FORM };
  }
  return {
    kind: link.kind,
    label: link.label ?? "",
    url: link.url,
    sort_order: link.sort_order
  };
}

const LINK_FORM_FIELDS = ["kind", "label", "url", "sort_order"] as const;

/**
 * The two rejections this form actually produces are 409 (a link of the same
 * kind and URL already exists on the tournament) and 422 (bad `url`/`kind`).
 * A single "request failed" hides which field to fix, so name them.
 *
 * `parseApiError` already folds pydantic's `loc` into the message as
 * `"url: Input should be a valid URL"` (see `normalizeDetailItem`), so the
 * field name is the prefix. Anything unrecognised is still surfaced verbatim
 * under a synthetic key — `EntityFormDialog` lists every entry.
 */
function linkFieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) {
    return {};
  }

  if (error.status === 409) {
    return {
      url: "This tournament already has a link of this kind with the same URL. Edit that one, or change the URL."
    };
  }

  if (error.status !== 422) {
    return {};
  }

  const fields: Record<string, string> = {};
  error.details.forEach((detail, index) => {
    const [, prefix, message] = /^([a-z_]+)(?:\.[^:]*)?:\s*(.+)$/i.exec(detail.msg) ?? [];
    const known = LINK_FORM_FIELDS.find((field) => field === prefix);
    if (known && message) {
      fields[known] = message;
    } else {
      fields[`detail-${index}`] = detail.msg;
    }
  });
  return fields;
}

export interface TournamentLinksTabProps {
  tournamentId: number;
  canCreate: boolean;
  canUpdate: boolean;
  canDelete: boolean;
  /** `stream.update` in the tournament's workspace — gates the re-poll button. */
  canRepollStreams: boolean;
}

/**
 * Typed link catalog of one tournament (`tournament.tournament_link`) — the
 * Discord invite, official broadcasts, VODs, the bracket, the rules doc.
 *
 * `AdminDataTable` in client mode: `GET /admin/tournament-links` returns a
 * flat array rather than a `PaginatedResponse`, and a tournament has a handful
 * of links, not pages of them — so the rows are handed over whole and the
 * table sorts and pages them locally. Row actions are the admin's single
 * convention, `createKebabColumn`.
 */
export function TournamentLinksTab({
  tournamentId,
  canCreate,
  canUpdate,
  canDelete,
  canRepollStreams
}: Readonly<TournamentLinksTabProps>) {
  const queryClient = useQueryClient();
  const formId = useId();
  const kindFieldId = `${formId}-kind`;
  const labelFieldId = `${formId}-label`;
  const urlFieldId = `${formId}-url`;
  const sortFieldId = `${formId}-sort-order`;

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingLink, setEditingLink] = useState<TournamentLink | null>(null);
  const [deletingLink, setDeletingLink] = useState<TournamentLink | null>(null);
  const [formData, setFormData] = useState<LinkForm>({ ...EMPTY_LINK_FORM });

  const linksQuery = useQuery({
    queryKey: ["admin", "tournament", tournamentId, "links"],
    // Archived rows are included so a soft-deleted link can be restored; the
    // public tournament page only ever reads the active ones.
    queryFn: () => adminService.listTournamentLinks(tournamentId, { activeOnly: false }),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0
  });

  const invalidateLinks = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "tournament", tournamentId, "links"] });

  const closeForm = () => {
    setCreateDialogOpen(false);
    setEditingLink(null);
    setFormData({ ...EMPTY_LINK_FORM });
  };

  const createMutation = useMutation({
    mutationFn: (data: TournamentLinkCreateInput) => adminService.createTournamentLink(data),
    onSuccess: async () => {
      await invalidateLinks();
      closeForm();
      notify.success("Link added");
    }
    // No onError toast: 409/422 land in the dialog as field errors, and a toast
    // on top of them would say the same thing twice.
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: TournamentLinkUpdateInput }) =>
      adminService.updateTournamentLink(id, data),
    onSuccess: async () => {
      await invalidateLinks();
      closeForm();
      notify.success("Link updated");
    }
  });

  // Soft delete: DELETE only flips `is_active`, so deactivation keeps going
  // through it (and stays gated by `tournament_link.delete`) while restoring is
  // a plain update — same split as the workspace sub-role catalog.
  const deactivateMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteTournamentLink(id),
    onSuccess: async () => {
      await invalidateLinks();
      setDeletingLink(null);
      notify.success("Link archived", {
        description: "It is hidden from the tournament page and can be restored here."
      });
    },
    onError: (error) => notify.apiError(error, { title: "Could not archive the link" })
  });

  const restoreMutation = useMutation({
    mutationFn: (id: number) => adminService.updateTournamentLink(id, { is_active: true }),
    onSuccess: async () => {
      await invalidateLinks();
      notify.success("Link restored");
    },
    onError: (error) => notify.apiError(error, { title: "Could not restore the link" })
  });

  // Same PATCH as `restoreMutation` above, just a different field — "primary"
  // is not a flag of its own, only a position in the stream order. Kept as its
  // own mutation rather than folded into `updateMutation` because that one
  // belongs to the dialog: it closes the form and reports "Link updated".
  const makePrimaryMutation = useMutation({
    mutationFn: ({ id, sortOrder }: { id: number; sortOrder: number }) =>
      adminService.updateTournamentLink(id, { sort_order: sortOrder }),
    onSuccess: async () => {
      await invalidateLinks();
      // Leading the order does NOT put the channel on screen: the public block
      // only embeds a player for a channel that is live, and shows a plain link
      // otherwise. Promising an embed here would be a lie the organizer finds
      // out about by reloading the tournament page.
      notify.success("Made the primary broadcast", {
        description:
          "It now leads the official links. The player only embeds a channel that is live, so an offline one stays a link until it goes live."
      });
    },
    onError: (error) =>
      notify.apiError(error, { title: "Could not make it the primary broadcast" })
  });

  const repollMutation = useMutation({
    // `POST /api/streams/tournament/{id}/repoll` already has a client in
    // `stream.service`, so there is no admin-service twin of it. `workspace_id`
    // rides along: `domainBehavior` injects it for every non-`/api/auth` domain,
    // and the hub shell has already synced the store to this tournament's
    // workspace — which is exactly the scope the endpoint authorizes against.
    mutationFn: () => streamService.repollTournament(tournamentId),
    onSuccess: () =>
      // 202, not 200: the poller picks the request up on its next heartbeat.
      // Saying "done" here would be a lie the operator then has to un-learn.
      notify.success("Re-poll queued", {
        description: "Live status refreshes on the poller's next heartbeat — up to 30 seconds."
      }),
    onError: (error) => notify.apiError(error, { title: "Could not queue the re-poll" })
  });

  // Backend orders by `(sort_order, id)`; mirror it so a local refetch never
  // reshuffles rows under the cursor.
  const links = useMemo(() => {
    return [...(linksQuery.data ?? [])].sort(
      (a, b) => a.sort_order - b.sort_order || a.id - b.id
    );
  }, [linksQuery.data]);

  const hasActiveStreamLink = links.some((link) => link.kind === "stream" && link.is_active);

  const columns: ColumnDef<TournamentLink>[] = [
    {
      accessorKey: "kind",
      header: "Kind",
      size: 112,
      cell: ({ row }) => (
        <Badge variant="secondary">{KIND_LABELS[row.original.kind] ?? row.original.kind}</Badge>
      ),
      meta: adminColumnMeta<TournamentLink>({
        searchValue: (link) => KIND_LABELS[link.kind] ?? link.kind
      })
    },
    {
      accessorKey: "label",
      header: "Label",
      cell: ({ row }) => row.original.label ?? <span className="text-muted-foreground">—</span>,
      meta: adminColumnMeta<TournamentLink>({ className: "max-w-[16rem] truncate" })
    },
    {
      accessorKey: "url",
      header: "URL",
      cell: ({ row }) => (
        <a
          href={row.original.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex max-w-full items-center gap-1 truncate text-primary underline-offset-4 hover:underline"
        >
          <span className="truncate">{row.original.url}</span>
          <ExternalLink aria-hidden className="size-3.5 shrink-0" />
        </a>
      ),
      meta: adminColumnMeta<TournamentLink>({ className: "max-w-[22rem]" })
    },
    {
      // ponytail: sort order is a plain number field in the edit dialog, not
      // per-row up/down arrows — no other admin list in this project reorders
      // inline, and a handful of links does not justify inventing the pattern.
      // If these lists ever grow past a screenful, lift the arrow + reindex
      // handling from `StageManager`.
      accessorKey: "sort_order",
      header: "Order",
      size: 80,
      meta: adminColumnMeta<TournamentLink>({ align: "right", numeric: true })
    },
    {
      id: "state",
      header: "State",
      size: 96,
      enableSorting: false,
      meta: adminColumnMeta<TournamentLink>({ align: "center" }),
      cell: ({ row }) =>
        row.original.is_active ? (
          <StatusIcon icon={CircleDot} label="Active" variant="success" />
        ) : (
          <StatusIcon icon={Archive} label="Archived" variant="muted" />
        )
    },
    createKebabColumn<TournamentLink>(
      (link) => {
        // Absent, not disabled, on rows that cannot be promoted — the same
        // choice the archive/restore pair makes. `primaryStreamLinkSortOrder`
        // is null for non-broadcasts, archived rows and the link that already
        // leads the order, and otherwise IS the number to send.
        const primarySortOrder = primaryStreamLinkSortOrder(link, links);
        return [
          {
            label: "Make primary broadcast",
            icon: ArrowUpToLine,
            hidden: !canUpdate || primarySortOrder === null,
            onSelect: () =>
              primarySortOrder !== null &&
              makePrimaryMutation.mutate({ id: link.id, sortOrder: primarySortOrder })
          },
          { label: "Edit", icon: Pencil, hidden: !canUpdate, onSelect: () => openEdit(link) },
          {
            label: "Archive",
            icon: Trash2,
            destructive: true,
            hidden: !canDelete || !link.is_active,
            onSelect: () => setDeletingLink(link)
          },
          {
            label: "Restore",
            icon: RotateCcw,
            hidden: !canUpdate || link.is_active,
            onSelect: () => restoreMutation.mutate(link.id)
          }
        ];
      },
      { rowLabel: (link) => link.label ?? link.url }
    )
  ];

  const isDialogOpen = createDialogOpen || !!editingLink;
  const activeError = editingLink ? updateMutation.error : createMutation.error;
  const fieldErrors = linkFieldErrors(activeError);
  const hasFieldErrors = Object.keys(fieldErrors).length > 0;
  // Field-level messages already say what to fix; the generic lead would only
  // repeat them. Anything else (403, 500, a network blip) still needs a line.
  const formErrorMessage = hasFieldErrors
    ? undefined
    : entityFormError("link", !!editingLink, updateMutation.error, createMutation.error);
  const isFormDirty = isDialogOpen && hasUnsavedChanges(formData, getLinkForm(editingLink));

  const openCreate = () => {
    createMutation.reset();
    updateMutation.reset();
    setFormData({ ...EMPTY_LINK_FORM });
    setCreateDialogOpen(true);
  };

  const openEdit = (link: TournamentLink) => {
    createMutation.reset();
    updateMutation.reset();
    setEditingLink(link);
    setFormData(getLinkForm(link));
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const label = formData.label.trim();
    const url = formData.url.trim();

    if (editingLink) {
      updateMutation.mutate({
        id: editingLink.id,
        data: { kind: formData.kind, label: label || null, url, sort_order: formData.sort_order }
      });
      return;
    }

    createMutation.mutate({
      tournament_id: tournamentId,
      kind: formData.kind,
      label: label || null,
      url,
      sort_order: formData.sort_order
    });
  };

  return (
    <Card>
      {/* No title here: the settings section heading above already names this
          page. The header keeps only what acts on the table. */}
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <p className="text-sm text-muted-foreground">Lower sort order comes first.</p>
        <div className="flex shrink-0 gap-2">
          {/* Nothing to poll without an official stream link, so the button is
              absent rather than disabled — a disabled control invites a guess
              at what would enable it. */}
          {canRepollStreams && hasActiveStreamLink && (
            <Button
              type="button"
              variant="outline"
              onClick={() => repollMutation.mutate()}
              disabled={repollMutation.isPending}
              aria-busy={repollMutation.isPending}
            >
              <RefreshCw
                aria-hidden
                className={`mr-2 h-4 w-4 ${repollMutation.isPending ? "animate-spin" : ""}`}
              />
              Refresh live status
            </Button>
          )}
          {canCreate && (
            <Button type="button" onClick={openCreate}>
              <Plus aria-hidden className="mr-2 h-4 w-4" />
              Add link
            </Button>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {linksQuery.isError ? (
          <EmptyNote>
            Could not load the links for this tournament.
          </EmptyNote>
        ) : (
          <AdminDataTable
            rows={links}
            isLoading={linksQuery.isLoading}
            columns={columns}
            getRowId={(link) => String(link.id)}
            emptyMessage={`No links yet.${canCreate ? " Use “Add link” to add the first one." : ""}`}
          />
        )}
      </CardContent>

      <EntityFormDialog
        open={isDialogOpen}
        onOpenChange={onEntityDialogClose(closeForm)}
        title={editingLink ? "Edit link" : "Add link"}
        description={
          editingLink
            ? "Update where this link points and how it is presented."
            : "Add a Discord invite, broadcast, VOD, bracket or rules link to this tournament."
        }
        onSubmit={handleSubmit}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        submittingLabel={editingLink ? "Saving link…" : "Adding link…"}
        errorMessage={formErrorMessage}
        fieldErrors={fieldErrors}
        isDirty={isFormDirty}
      >
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={kindFieldId}>Kind *</Label>
            <Select
              value={formData.kind}
              onValueChange={(kind) =>
                setFormData({ ...formData, kind: kind as TournamentLinkKind })
              }
            >
              <SelectTrigger
                id={kindFieldId}
                aria-invalid={fieldErrors.kind ? true : undefined}
                aria-describedby={fieldErrors.kind ? `${kindFieldId}-error` : undefined}
              >
                <SelectValue placeholder="Pick a kind" />
              </SelectTrigger>
              <SelectContent>
                {LINK_KINDS.map((kind) => (
                  <SelectItem key={kind.value} value={kind.value}>
                    {kind.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {fieldErrors.kind && (
              <p id={`${kindFieldId}-error`} className="text-xs text-destructive">
                {fieldErrors.kind}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              A stream link is what the live-status poller watches.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor={urlFieldId}>URL *</Label>
            <Input
              id={urlFieldId}
              type="url"
              value={formData.url}
              onChange={(event) => setFormData({ ...formData, url: event.target.value })}
              placeholder="https://twitch.tv/example"
              aria-invalid={fieldErrors.url ? true : undefined}
              aria-describedby={fieldErrors.url ? `${urlFieldId}-error` : undefined}
              required
            />
            {fieldErrors.url && (
              <p id={`${urlFieldId}-error`} className="text-xs text-destructive">
                {fieldErrors.url}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor={labelFieldId}>Label</Label>
            <Input
              id={labelFieldId}
              value={formData.label}
              onChange={(event) => setFormData({ ...formData, label: event.target.value })}
              placeholder="Main broadcast"
              aria-invalid={fieldErrors.label ? true : undefined}
              aria-describedby={fieldErrors.label ? `${labelFieldId}-error` : undefined}
            />
            {fieldErrors.label && (
              <p id={`${labelFieldId}-error`} className="text-xs text-destructive">
                {fieldErrors.label}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              Shown instead of the raw URL. Leave empty to fall back to the kind.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor={sortFieldId}>Sort order</Label>
            <Input
              id={sortFieldId}
              type="number"
              inputMode="numeric"
              step={1}
              className="w-32"
              value={formData.sort_order}
              onChange={(event) =>
                setFormData({ ...formData, sort_order: Number(event.target.value) || 0 })
              }
              aria-invalid={fieldErrors.sort_order ? true : undefined}
              aria-describedby={fieldErrors.sort_order ? `${sortFieldId}-error` : undefined}
            />
            {fieldErrors.sort_order && (
              <p id={`${sortFieldId}-error`} className="text-xs text-destructive">
                {fieldErrors.sort_order}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              Lower comes first; ties fall back to creation order.
            </p>
          </div>
        </div>
      </EntityFormDialog>

      {deletingLink && (
        <ConfirmDialog
          open={!!deletingLink}
          onOpenChange={(open) => !open && setDeletingLink(null)}
          onConfirm={() => deactivateMutation.mutate(deletingLink.id)}
          pending={deactivateMutation.isPending}
          intent={{
            title: "Archive link",
            // Soft delete — the row survives with `is_active: false`. Saying
            // "permanently removed" here would be false.
            description: `“${deletingLink.label ?? deletingLink.url}” disappears from the tournament page. Nothing is destroyed — you can restore it from this table.`,
            confirmLabel: deactivateMutation.isPending ? "Archiving…" : "Archive",
            tone: "danger"
          }}
        />
      )}
    </Card>
  );
}
