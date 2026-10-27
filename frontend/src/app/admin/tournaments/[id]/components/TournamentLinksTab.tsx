"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { DataTable, type TableCommand } from "@/components/data-table";
import {
  entityFormError,
  onEntityDialogClose
} from "@/components/admin/CatalogToolbarActions";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { PageStateCard } from "@/components/ui/page-state-card";
import { hasUnsavedChanges } from "@/lib/form-change";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import streamService from "@/services/stream.service";
import type {
  TournamentLink,
  TournamentLinkCreateInput,
  TournamentLinkUpdateInput
} from "@/types/stream.types";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { LinkFormFields } from "./links-tab/LinkFormFields";
import { EMPTY_LINK_FORM, getLinkForm, linkFieldErrors, type LinkForm } from "./links-tab/model";
import { useLinkColumns } from "./links-tab/useLinkColumns";

export interface TournamentLinksTabProps {
  tournamentId: number;
  canCreate: boolean;
  canUpdate: boolean;
  canDelete: boolean;
  /** `stream.update` in the tournament's workspace — gates the re-poll command. */
  canRepollStreams: boolean;
}

/**
 * Typed link catalog of one tournament (`tournament.tournament_link`) — the
 * Discord invite, official broadcasts, VODs, the bracket, the rules doc.
 *
 * `DataTable` in client mode: `GET /admin/tournament-links` returns a
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
  const t = useTranslations("adminTournament.links");
  const workspaceT = useTranslations("adminWorkspace.content");
  const queryClient = useQueryClient();

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingLink, setEditingLink] = useState<TournamentLink | null>(null);
  const [deletingLink, setDeletingLink] = useState<TournamentLink | null>(null);
  const [formData, setFormData] = useState<LinkForm>({ ...EMPTY_LINK_FORM });

  const linksQuery = useQuery({
    queryKey: adminQueryKeys.tournamentLinks(tournamentId),
    // Archived rows are included so a soft-deleted link can be restored; the
    // public tournament page only ever reads the active ones.
    queryFn: () => adminService.listTournamentLinks(tournamentId, { activeOnly: false }),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0
  });

  const invalidateLinks = () =>
    queryClient.invalidateQueries({ queryKey: adminQueryKeys.tournamentLinks(tournamentId) });

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
      notify.success(t("added"));
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
      notify.success(t("updated"));
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
      notify.success(t("archived"), {
        description: t("archiveDescription")
      });
    },
    onError: (error) => notify.apiError(error, { title: t("archiveError") })
  });

  const restoreMutation = useMutation({
    mutationFn: (id: number) => adminService.updateTournamentLink(id, { is_active: true }),
    onSuccess: async () => {
      await invalidateLinks();
      notify.success(t("restored"));
    },
    onError: (error) => notify.apiError(error, { title: t("restoreError") })
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
      notify.success(t("primary"), {
        description: t("primaryDescription")
      });
    },
    onError: (error) =>
      notify.apiError(error, { title: t("primaryError") })
  });

  const repollMutation = useMutation({
    // `POST /api/v1/streams/tournament/{id}/repoll` already has a client in
    // `stream.service`, so there is no admin-service twin of it. `workspace_id`
    // rides along: `domainBehavior` injects it for every domain outside
    // `UNSCOPED_DOMAINS` (lib/api/fetch.ts keys on the domain segment, not a prefix),
    // and the hub shell has already synced the store to this tournament's
    // workspace — which is exactly the scope the endpoint authorizes against.
    mutationFn: () => streamService.repollTournament(tournamentId),
    onSuccess: () =>
      // 202, not 200: the poller picks the request up on its next heartbeat.
      // Saying "done" here would be a lie the operator then has to un-learn.
      notify.success(t("repoll"), {
        description: t("repollDescription")
      }),
    onError: (error) => notify.apiError(error, { title: t("repollError") })
  });

  // Backend orders by `(sort_order, id)`; mirror it so a local refetch never
  // reshuffles rows under the cursor.
  const links = useMemo(() => {
    return [...(linksQuery.data ?? [])].sort(
      (a, b) => a.sort_order - b.sort_order || a.id - b.id
    );
  }, [linksQuery.data]);

  const hasActiveStreamLink = links.some((link) => link.kind === "stream" && link.is_active);

  // The mutation containers are rebuilt on every state transition; `reset` is
  // not, so the memoised `openEdit` hangs on the callbacks instead.
  const { reset: resetCreateMutation } = createMutation;
  const { reset: resetUpdateMutation } = updateMutation;
  const openEdit = useCallback(
    (link: TournamentLink) => {
      resetCreateMutation();
      resetUpdateMutation();
      setEditingLink(link);
      setFormData(getLinkForm(link));
    },
    [resetCreateMutation, resetUpdateMutation]
  );

  const columns = useLinkColumns({
    links,
    canUpdate,
    canDelete,
    onMakePrimary: makePrimaryMutation.mutate,
    onEdit: openEdit,
    onArchive: setDeletingLink,
    onRestore: restoreMutation.mutate
  });

  const isDialogOpen = createDialogOpen || !!editingLink;
  const activeError = editingLink ? updateMutation.error : createMutation.error;
  const fieldErrors = linkFieldErrors(activeError, t("duplicate"));
  const hasFieldErrors = Object.keys(fieldErrors).length > 0;
  // Field-level messages already say what to fix; the generic lead would only
  // repeat them. Anything else (403, 500, a network blip) still needs a line.
  const formErrorMessage = hasFieldErrors
    ? undefined
    : entityFormError(
        workspaceT("linkEntity"),
        !!editingLink,
        updateMutation.error,
        createMutation.error,
        (key, values) => workspaceT(key, values)
      );
  const isFormDirty = isDialogOpen && hasUnsavedChanges(formData, getLinkForm(editingLink));

  const openCreate = () => {
    createMutation.reset();
    updateMutation.reset();
    setFormData({ ...EMPTY_LINK_FORM });
    setCreateDialogOpen(true);
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

  const commands: TableCommand[] = [
    {
      id: "repoll",
      label: t("refresh"),
      onSelect: () => repollMutation.mutate(),
      // Nothing to poll without an official stream link, so the command is
      // absent rather than disabled — a disabled control invites a guess at
      // what would enable it.
      hidden: !(canRepollStreams && hasActiveStreamLink),
      pending: repollMutation.isPending,
      disabled: repollMutation.isPending
    },
    { id: "add", label: t("add"), icon: Plus, onSelect: openCreate, primary: true, hidden: !canCreate }
  ];

  return (
    <>
      {linksQuery.isError ? (
        <PageStateCard
          state="error"
          description={t("loadError")}
          onAction={() => void linksQuery.refetch()}
        />
      ) : (
        <DataTable
          rows={links}
          isLoading={linksQuery.isLoading}
          columns={columns}
          getRowId={(link) => String(link.id)}
          emptyMessage={t("empty")}
          commands={commands}
        />
      )}

      <EntityFormDialog
        open={isDialogOpen}
        onOpenChange={onEntityDialogClose(closeForm)}
        title={editingLink ? t("editTitle") : t("addTitle")}
        description={
          editingLink
            ? t("editDescription")
            : t("addDescription")
        }
        onSubmit={handleSubmit}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        submittingLabel={editingLink ? t("saving") : t("adding")}
        errorMessage={formErrorMessage}
        fieldErrors={fieldErrors}
        isDirty={isFormDirty}
      >
        <LinkFormFields formData={formData} onChange={setFormData} fieldErrors={fieldErrors} />
      </EntityFormDialog>

      {deletingLink && (
        <ConfirmDialog
          open={!!deletingLink}
          onOpenChange={(open) => !open && setDeletingLink(null)}
          onConfirm={() => deactivateMutation.mutate(deletingLink.id)}
          pending={deactivateMutation.isPending}
          intent={{
            title: t("archiveTitle"),
            // Soft delete — the row survives with `is_active: false`. Saying
            // "permanently removed" here would be false.
            description: t("archiveConfirmDescription", {
              name: deletingLink.label ?? deletingLink.url
            }),
            confirmLabel: deactivateMutation.isPending ? t("archiving") : t("archive"),
            tone: "danger"
          }}
        />
      )}
    </>
  );
}
