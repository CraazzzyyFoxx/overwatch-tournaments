"use client";

import { useId, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { DataTable, type TableCommand } from "@/components/data-table";
import { AuthUserSearchCombobox } from "@/components/kit/ServerSearchCombobox";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { PlayerProfileDialog } from "@/components/admin/PlayerProfileDialog";
import { UserMergeDialog } from "@/components/admin/UserMergeDialog";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useFilters } from "@/components/kit/useFilters";
import { TOURNAMENT_QUERY_PARAM } from "@/components/admin/tournament-filter";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { hasUnsavedChanges } from "@/lib/form-change";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import { rbacService } from "@/services/rbac.service";
import tournamentService from "@/services/tournament.service";
import type { User } from "@/types/user.types";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

import { peopleFilterDefs } from "./filters";
import { authAccountsByPlayerId } from "./model";
import { PersonInspectorActions, PersonInspectorPanel } from "./PersonInspectorPanel";
import { usePeopleColumns } from "./usePeopleColumns";

const PAGE_SIZE = 20;

/**
 * Server-paged. Chip filters ride on GET /admin/users: `unlinked` is no
 * social_account row, `has-account` is `auth_user_id IS NOT NULL`, tournament
 * is a roster EXISTS. Auth labels still come from RBAC (`listUsersAll`).
 *
 * Mounted behind the page's `user.read` gate, so every read here may run.
 */
export function PeopleBrowser({ workspaceId }: Readonly<{ workspaceId: number | null }>) {
  const t = useTranslations("adminPeople.people");
  const queryClient = useQueryClient();
  const { canAccessPermission, hasPermission, isSuperuser } = usePermissions();
  const formId = useId();
  const nameFieldId = `${formId}-name`;

  // `id` is the inspector, not a filter: opening a row must not drop the page
  // the row is on, so nothing resets here.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [], shallow: true });
  const openId = searchParams?.get("id") ?? null;

  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  // Optionally link the new player to an existing auth account on creation.
  const [linkAuthUserId, setLinkAuthUserId] = useState<number | null>(null);
  const [linkAuthUserLabel, setLinkAuthUserLabel] = useState("");
  const [profileUser, setProfileUser] = useState<User | null>(null);
  const [mergeUser, setMergeUser] = useState<User | null>(null);
  const [pendingDelete, setPendingDelete] = useState<User | null>(null);
  const [pageRows, setPageRows] = useState<User[]>([]);

  // A player identity is platform-wide: creating, renaming or deleting one
  // reaches every workspace that plays with it, so those stay on the GLOBAL
  // grant. A workspace-scoped `user.read` opens the page and the list, not the
  // writes; `hasPermission` is the global check, `canAccessPermission` also
  // answers to a workspace grant.
  const canCreate = hasPermission("user.create");
  const canUpdate = hasPermission("user.update");
  const canDelete = hasPermission("user.delete");
  const canLinkAuth = hasPermission("auth_user.update");
  const canReadAuth = hasPermission("auth_user.read");
  const canMerge = isSuperuser;
  // Identity (social account) management is superuser-only; display visibility
  // can be toggled by anyone with read access.
  const canManageIdentity = isSuperuser;
  const canSetVisibility = canAccessPermission("user.read", workspaceId);
  const canEditProfile = canUpdate || canManageIdentity || canSetVisibility;

  // The auth side of the "Account" column. Global grant only — without it the
  // column says so rather than pretending every identity is unlinked.
  const authQuery = useQuery({
    queryKey: accessQueryKeys.usersAll(),
    queryFn: () => rbacService.listUsersAll(),
    enabled: canReadAuth
  });

  const tournamentsQuery = useQuery({
    queryKey: tournamentQueryKeys.list(),
    queryFn: () => tournamentService.getAll(null)
  });

  const defs = useMemo(
    () => peopleFilterDefs(tournamentsQuery.data?.results ?? [], t),
    [t, tournamentsQuery.data]
  );

  const filters = useFilters(defs);
  const tournamentFilter = String(filters.values[TOURNAMENT_QUERY_PARAM] ?? "");
  const hasAccountFilter = filters.values["has-account"] === true;
  const unlinkedFilter = filters.values.unlinked === true;

  const authByPlayerId = useMemo(() => authAccountsByPlayerId(authQuery.data ?? []), [authQuery.data]);

  const openRow = pageRows.find((person) => String(person.id) === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;

  const resetCreateForm = () => {
    setCreateName("");
    setLinkAuthUserId(null);
    setLinkAuthUserLabel("");
  };

  const createMutation = useMutation({
    // Create the player, then (optionally) link it to an auth account. The link
    // is a second call; if it fails we still report the player as created and
    // surface a warning rather than throwing — re-submitting would otherwise
    // create a duplicate player. The admin can retry the link from Access.
    mutationFn: async (input: { name: string; authUserId: number | null }) => {
      const person = await adminService.createUser({ name: input.name });
      if (input.authUserId == null) return { person, linkWarning: undefined as { name: string; detail: string } | undefined };
      try {
        await rbacService.assignLinkedPlayer(input.authUserId, { player_id: person.id });
        return { person, linkWarning: undefined as { name: string; detail: string } | undefined };
      } catch (error) {
        const detail = error instanceof Error ? error.message : t("unknownError");
        return {
          person,
          linkWarning: { name: person.name, detail }
        };
      }
    },
    onSuccess: ({ linkWarning }) => {
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.users() });
      queryClient.invalidateQueries({ queryKey: accessQueryKeys.users() });
      setCreateOpen(false);
      resetCreateForm();
      if (linkWarning) notify.error(t("linkFailed", linkWarning));
      else notify.success(t("created"));
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteUser(id),
    onSuccess: () => {
      const removed = pendingDelete;
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.users() });
      setPendingDelete(null);
      if (removed && String(removed.id) === openId) setParams({ id: null });
      notify.success(t("deleted"));
    }
  });

  const columns = usePeopleColumns({
    canReadAuth,
    canEditProfile,
    canMerge,
    canDelete,
    authByPlayerId,
    onEdit: setProfileUser,
    onMerge: setMergeUser,
    onDelete: setPendingDelete
  });

  const isCreateDirty =
    createOpen &&
    hasUnsavedChanges(
      { name: createName, authUserId: linkAuthUserId },
      { name: "", authUserId: null }
    );

  const commands: TableCommand[] = [
    {
      id: "create",
      label: t("create"),
      icon: Plus,
      primary: true,
      hidden: !canCreate,
      onSelect: () => {
        createMutation.reset();
        resetCreateForm();
        setCreateOpen(true);
      }
    }
  ];

  return (
    <>
      <div
        className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}
      >
        <div className="min-w-0">
          <DataTable<User>
            queryKey={(page, search, pageSize, sortField, sortDir) => [
              "admin",
              "users",
              page,
              search,
              pageSize,
              sortField,
              sortDir,
              tournamentFilter,
              hasAccountFilter,
              unlinkedFilter
            ]}
            queryFn={(page, search, pageSize, sortField, sortDir) =>
              adminService.getUsers({
                page,
                per_page: pageSize,
                search: search || undefined,
                sort: sortField ?? undefined,
                order: sortDir,
                tournament_id: tournamentFilter ? Number(tournamentFilter) : undefined,
                has_account: hasAccountFilter || undefined,
                unlinked: unlinkedFilter || undefined
              })
            }
            onPageRowsChange={setPageRows}
            columns={columns}
            initialPageSize={PAGE_SIZE}
            filterKey={filters.filterKey}
            inspectorId={openId}
            getRowId={(person) => String(person.id)}
            toolbar={<FilterBar defs={defs} filters={filters} />}
            commands={commands}
            searchPlaceholder={t("search")}
            emptyMessage={t("empty")}
            onRowClick={(row) => setParams({ id: String(row.original.id) })}
          />
        </div>

        <Inspector
          openId={openRow ? openId : null}
          onClose={() => setParams({ id: null })}
          title={openRow?.name ?? ""}
          openHref={openRow ? `/admin/people/${openRow.id}` : undefined}
          onPrev={
            openIndex > 0 ? () => setParams({ id: String(pageRows[openIndex - 1].id) }) : undefined
          }
          onNext={
            openIndex >= 0 && openIndex < pageRows.length - 1
              ? () => setParams({ id: String(pageRows[openIndex + 1].id) })
              : undefined
          }
          actions={
            openRow ? (
              <PersonInspectorActions
                person={openRow}
                canEditProfile={canEditProfile}
                canMerge={canMerge}
                onEdit={setProfileUser}
                onMerge={setMergeUser}
              />
            ) : null
          }
        >
          {openRow ? (
            <PersonInspectorPanel
              person={openRow}
              account={authByPlayerId.get(openRow.id)}
              canReadAuth={canReadAuth}
            />
          ) : null}
        </Inspector>
      </div>

      <EntityFormDialog
        open={createOpen}
        onOpenChange={(next) => {
          if (!next) {
            setCreateOpen(false);
            resetCreateForm();
          }
        }}
        title={t("createTitle")}
        onSubmit={(event) => {
          event.preventDefault();
          createMutation.mutate({ name: createName, authUserId: linkAuthUserId });
        }}
        isSubmitting={createMutation.isPending}
        submittingLabel={t("creating")}
        errorMessage={
          createMutation.error instanceof Error
            ? t("createError", { detail: createMutation.error.message })
            : undefined
        }
        isDirty={isCreateDirty}
      >
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={nameFieldId}>{t("name")}</Label>
            <Input
              id={nameFieldId}
              value={createName}
              onChange={(event) => setCreateName(event.target.value)}
              placeholder={t("namePlaceholder")}
              required
            />
          </div>
          {canLinkAuth && (
            <div className="space-y-2">
              <Label htmlFor="link-auth-account">{t("linkAccount")}</Label>
              <AuthUserSearchCombobox
                id="link-auth-account"
                value={linkAuthUserId ?? undefined}
                selectedLabel={linkAuthUserLabel || undefined}
                onSelect={(account) => {
                  setLinkAuthUserId(account?.id ?? null);
                  setLinkAuthUserLabel(account?.label ?? "");
                }}
              />
              <p className="text-xs text-muted-foreground">
                {t("linkAccountDescription")}
              </p>
            </div>
          )}
        </div>
      </EntityFormDialog>

      {profileUser ? (
        <PlayerProfileDialog
          key={profileUser.id}
          user={profileUser}
          onClose={() => setProfileUser(null)}
          canEdit={canUpdate}
          canManageIdentity={canManageIdentity}
          canSetVisibility={canSetVisibility}
          workspaceId={workspaceId}
          canMerge={canMerge}
          onMergeRequested={(person) => setMergeUser(person)}
        />
      ) : null}

      {mergeUser ? (
        <UserMergeDialog
          key={mergeUser.id}
          sourceUser={mergeUser}
          open
          onOpenChange={(next) => {
            if (!next) setMergeUser(null);
          }}
          onMerged={() => {
            if (profileUser?.id === mergeUser.id) setProfileUser(null);
            if (String(mergeUser.id) === openId) setParams({ id: null });
            setMergeUser(null);
          }}
        />
      ) : null}

      <ConfirmDialog
        open={pendingDelete != null}
        onOpenChange={(next) => {
          if (!next) setPendingDelete(null);
        }}
        pending={deleteMutation.isPending}
        intent={{
          title: t("deleteTitle"),
          description: t("deleteDescription", { name: pendingDelete?.name ?? t("thisIdentity") }),
          confirmLabel: t("deleteConfirm"),
          tone: "danger"
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </>
  );
}
