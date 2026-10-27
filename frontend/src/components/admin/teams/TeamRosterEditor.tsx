"use client";

import { Fragment, useId, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Check, Sparkles, Trash2, UserPlus, X } from "lucide-react";

import {
  AdminDetailTableShell,
  adminDetailTableStyles as tableStyles
} from "@/components/admin/AdminDetailTable";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { UserSearchCombobox } from "@/components/kit/ServerSearchCombobox";
import DivisionIcon from "@/components/DivisionIcon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { ratedDimension, subRoleOptions } from "@/lib/roster/ontology";
import { roleOf, subRoleOf, toRoleRef } from "@/lib/roster/role-ref";
import { OPEN_SLOT_CODE } from "@/lib/roster/shape";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { PlayerCreateInput, PlayerUpdateInput } from "@/types/admin.types";
import type { Player } from "@/types/team.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

import { CommitField, FlagToggle, RoleSelect, SubRoleSelect } from "./roster-editor/RosterControls";
import { buildRosterRows, emptyDraft, type RosterDraft } from "./roster-editor/model";

interface TeamRosterEditorProps {
  teamId: number;
  tournamentId: number;
  workspaceId: number | null;
  discipline: string | null;
  players: Player[];
  /** Grid the tournament scores ranks against; falls back to the workspace grid. */
  divisionGrid: DivisionGridVersion | null;
  canCreatePlayer: boolean;
  canUpdatePlayer: boolean;
  canDeletePlayer: boolean;
}

/**
 * The roster, editable in place: the flush body of the team hub's roster card,
 * so its count and Add sit on a toolbar line and the rows run edge to edge.
 *
 * Every control persists on its own: role, rank, sub-role and the newcomer flags
 * PATCH the player as soon as they change, so there is no draft to lose and no
 * dialog to open. Structural moves stay explicit — a substitute is added through
 * "Replace", and removing a player is confirmed.
 */
export function TeamRosterEditor({
  teamId,
  tournamentId,
  workspaceId,
  discipline,
  players,
  divisionGrid,
  canCreatePlayer,
  canUpdatePlayer,
  canDeletePlayer
}: Readonly<TeamRosterEditorProps>) {
  const t = useTranslations("adminPeople.roster");
  const roleT = useTranslations("common.roleOntology");
  const subRoleErrorId = useId();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<RosterDraft | null>(null);
  const [pendingRemoval, setPendingRemoval] = useState<Player | null>(null);

  // The roles on offer are the roster's own game's: this team's tournament, never a fixed or browsing vocabulary.
  const ownerMetadata = useDisciplineMetadata(workspaceId ?? "all", workspaceId != null ? discipline : null);
  const ontology = ownerMetadata.data ?? null;
  const ratedCode = ontology ? ratedDimension(ontology)?.code : undefined;
  const metadataFailed = ownerMetadata.isError || (ontology !== null && !ratedCode);

  const subRolesQuery = useQuery({
    queryKey: adminQueryKeys.playerSubRoles(workspaceId, discipline),
    queryFn: ({ signal }) => adminService.getPlayerSubRoles({ workspace_id: workspaceId!, discipline: discipline! }, signal),
    enabled: workspaceId != null && Boolean(discipline)
  });
  const playerSubRoles = subRolesQuery.data;

  const rows = useMemo(() => buildRosterRows(players, ontology), [players, ontology]);

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.team(teamId) }),
      queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.teamsAll() }),
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.tournament(tournamentId) })
    ]);

  const patchPlayer = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: PlayerUpdateInput }) =>
      adminService.updatePlayer(id, payload),
    onSuccess: refresh
  });

  const addPlayer = useMutation({
    mutationFn: (payload: PlayerCreateInput) => adminService.createPlayer(payload),
    onSuccess: async () => {
      setDraft(null);
      await refresh();
    }
  });

  const removePlayer = useMutation({
    mutationFn: (id: number) => adminService.deletePlayer(id),
    onSuccess: async () => {
      setDraft(null);
      setPendingRemoval(null);
      await refresh();
    }
  });

  const savingPlayerId = patchPlayer.isPending ? patchPlayer.variables?.id : undefined;

  const patch = (player: Player, payload: PlayerUpdateInput) =>
    patchPlayer.mutate({ id: player.id, payload });

  /** The game's own role as a reference (`{dimension, role[, sub-role leaf]}`); the open slot is no role at all. */
  const roleRef = (role: string, subRole: string | null) =>
    toRoleRef(role === OPEN_SLOT_CODE ? null : role, subRole, ratedCode ?? "");

  /** The open slot has no rows in the sub-role catalog, so its sub-role select renders inert rather than empty. */
  const subRoleOptionsFor = (role: string) => subRoleOptions(playerSubRoles, ratedCode, role);

  const substituteCount = players.filter((player) => player.is_substitution).length;
  const draftIsValid = draft != null && draft.userId > 0 && draft.name.trim().length > 0;

  const submitDraft = () => {
    if (!draft || !draftIsValid) return;
    addPlayer.mutate({
      name: draft.name.trim(),
      user_id: draft.userId,
      team_id: teamId,
      tournament_id: tournamentId,
      role: roleRef(draft.role, draft.subRole),
      rank: draft.rank,
      is_substitution: draft.parentId != null,
      related_player_id: draft.parentId
    });
  };

  const renderDraftRow = (depth: number) =>
    draft ? (
    <TableRow key="roster-draft" className={cn(tableStyles.row, "bg-muted/20")}>
      <TableCell className={tableStyles.cell}>
        <div
          className="flex flex-col gap-1.5"
          style={depth > 0 ? { paddingLeft: `${depth * 1.25}rem` } : undefined}
        >
          <UserSearchCombobox
            value={draft.userId || undefined}
            selectedLabel={draft.userName}
            placeholder={t("linkUser")}
            onSelect={(user) =>
              setDraft((current) =>
                current
                  ? {
                      ...current,
                      userId: user?.id ?? 0,
                      userName: user?.name ?? "",
                      name: current.name || user?.name || ""
                    }
                  : current
              )
            }
          />
          <Input
            aria-label={t("newPlayer")}
            value={draft.name}
            placeholder={t("rosterName")}
            size="sm"
            onChange={(event) =>
              setDraft((current) => (current ? { ...current, name: event.target.value } : current))
            }
          />
        </div>
      </TableCell>
      <TableCell className={tableStyles.cell}>
        <RoleSelect
          value={draft.role}
          label={t("roleOf")}
          disabled={!ratedCode}
          ontology={ontology}
          onChange={(role) =>
            setDraft((current) => (current ? { ...current, role, subRole: "" } : current))
          }
        />
      </TableCell>
      <TableCell className={tableStyles.numericCell}>
        <Input
          aria-label={t("rankOf")}
          value={draft.rank == null ? "" : String(draft.rank)}
          inputMode="numeric"
          size="sm"
          className="w-20 tabular-nums"
          onChange={(event) => {
            const next = Number.parseInt(event.target.value, 10);
            // Empty (or not a positive number) = no rank.
            setDraft((current) =>
              current ? { ...current, rank: Number.isFinite(next) && next > 0 ? next : null } : current
            );
          }}
        />
      </TableCell>
      <TableCell className={tableStyles.cell}>
        <SubRoleSelect
          value={draft.subRole}
          options={subRoleOptionsFor(draft.role)}
          disabled={subRolesQuery.isError || draft.role === OPEN_SLOT_CODE}
          describedBy={subRolesQuery.isError ? subRoleErrorId : undefined}
          label={t("subRoleOf")}
          onChange={(subRole) =>
            setDraft((current) => (current ? { ...current, subRole } : current))
          }
        />
      </TableCell>
      {/* Flags: a draft has none yet; it is a substitute by being a "Replace" draft. */}
      <TableCell className={tableStyles.cell} />
      <TableCell className={tableStyles.cell}>
        <div className="flex items-center justify-end gap-1">
          <Button
            type="button"
            size="sm"
            disabled={!draftIsValid || addPlayer.isPending}
            onClick={submitDraft}
          >
            <Check aria-hidden className="mr-1.5 size-4" />
            {addPlayer.isPending ? t("adding") : t("add")}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-toolbar"
            aria-label={t("cancel")}
            onClick={() => setDraft(null)}
          >
            <X aria-hidden className="size-4" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  ) : null;

  if (!discipline || workspaceId === null) {
    return (
      <div className="px-5 py-3">
        <EmptyNote tone="danger">{roleT("ownerScopeError")}</EmptyNote>
      </div>
    );
  }
  return (
    <div>
      {subRolesQuery.isError && <p id={subRoleErrorId} role="status" className="px-5 pt-3 text-sm text-muted-foreground">{roleT("roleLoadError")}</p>}
      {metadataFailed && <p role="status" className="px-5 pt-3 text-sm text-muted-foreground">{roleT("metadataError")}</p>}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-5 py-2.5">
        <p className="text-sm tabular-nums text-muted-foreground">
          {players.length
            ? t("rosterCount", { starters: players.length - substituteCount, substitutes: substituteCount })
            : t("empty")}
        </p>
        {canCreatePlayer ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={draft != null}
            onClick={() => setDraft(emptyDraft(null))}
          >
            <UserPlus aria-hidden className="mr-2 size-4" />
            {t("add")}
          </Button>
        ) : null}
      </div>

      {/* Edge cells take the card's own inset, so the columns line up with its title. */}
      <AdminDetailTableShell className="rounded-none border-0 [&_tr>*:first-child]:pl-5 [&_tr>*:last-child]:pr-5">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className={tableStyles.head}>{t("player")}</TableHead>
              <TableHead className={tableStyles.head}>{t("role")}</TableHead>
              <TableHead className={tableStyles.head}>{t("rank")}</TableHead>
              <TableHead className={tableStyles.head}>{t("subRole")}</TableHead>
              <TableHead className={tableStyles.head}>{t("flags")}</TableHead>
              <TableHead className={cn(tableStyles.head, "text-right")}>{t("actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(({ player, depth }) => {
              const role = roleOf(player.role) ?? OPEN_SLOT_CODE;
              const saving = savingPlayerId === player.id;

              return (
                <Fragment key={player.id}>
                <TableRow
                  className={cn(tableStyles.row, saving && "opacity-60")}
                  aria-busy={saving || undefined}
                >
                  <TableCell className={tableStyles.cell}>
                    <div
                      className="min-w-0"
                      style={depth > 0 ? { paddingLeft: `${depth * 1.25}rem` } : undefined}
                    >
                      <CommitField
                        value={player.name}
                        label={t("rosterNameOf", { name: player.name })}
                        disabled={!canUpdatePlayer}
                        onCommit={(name) => {
                          if (name) {
                            patch(player, { name });
                          }
                        }}
                      />
                      <p className="truncate px-2 text-xs text-muted-foreground">
                        {player.user?.name ?? t("userId", { id: player.user_id })}
                      </p>
                    </div>
                  </TableCell>

                  <TableCell className={tableStyles.cell}>
                    <RoleSelect
                      value={role}
                      label={t("roleOfPlayer", { name: player.name })}
                      disabled={!canUpdatePlayer || !ratedCode}
                      ontology={ontology}
                      onChange={(next) => patch(player, { role: roleRef(next, null) })}
                    />
                  </TableCell>

                  <TableCell className={tableStyles.numericCell}>
                    <div className="flex items-center gap-2">
                      <DivisionIcon
                        division={player.division}
                        tournamentGrid={divisionGrid}
                        width={24}
                        height={24}
                      />
                      <CommitField
                        value={player.rank == null ? "" : String(player.rank)}
                        label={t("rankOfPlayer", { name: player.name })}
                        disabled={!canUpdatePlayer}
                        inputMode="numeric"
                        className="w-20 tabular-nums"
                        onCommit={(next) => {
                          // Clearing the field removes the rank; anything else must be a rank >= 1.
                          if (next === "") {
                            patch(player, { rank: null });
                            return;
                          }
                          const rank = Number.parseInt(next, 10);
                          if (Number.isFinite(rank) && rank >= 1) {
                            patch(player, { rank });
                          }
                        }}
                      />
                    </div>
                  </TableCell>

                  <TableCell className={tableStyles.cell}>
                    <SubRoleSelect
                      value={subRoleOf(player.role) ?? ""}
                      options={subRoleOptionsFor(role)}
                      label={t("subRoleOfPlayer", { name: player.name })}
                      disabled={subRolesQuery.isError || !canUpdatePlayer || role === OPEN_SLOT_CODE}
                      describedBy={subRolesQuery.isError ? subRoleErrorId : undefined}
                      onChange={(subRole) => patch(player, { role: roleRef(role, subRole) })}
                    />
                  </TableCell>

                  <TableCell className={tableStyles.cell}>
                    <div className="flex items-center gap-0.5">
                      <FlagToggle
                        active={player.is_newcomer}
                        icon={Sparkles}
                        label={t("newcomer", { name: player.name })}
                        disabled={!canUpdatePlayer}
                        onToggle={() => patch(player, { is_newcomer: !player.is_newcomer })}
                      />
                      <FlagToggle
                        active={player.is_newcomer_role}
                        icon={ArrowLeftRight}
                        label={t("newRole", { name: player.name })}
                        disabled={!canUpdatePlayer}
                        onToggle={() =>
                          patch(player, { is_newcomer_role: !player.is_newcomer_role })
                        }
                      />
                    </div>
                  </TableCell>

                  <TableCell className={tableStyles.cell}>
                    <div className="flex items-center justify-end gap-1">
                      {canCreatePlayer ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          // Keeps the visible word in the accessible name (WCAG 2.5.3).
                          aria-label={t("replace", { name: player.name })}
                          disabled={draft != null}
                          onClick={() => setDraft(emptyDraft(player.id, role))}
                        >
                          {t("replaceAction")}
                        </Button>
                      ) : null}
                      {canDeletePlayer ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="size-8 text-destructive"
                          aria-label={t("remove", { name: player.name })}
                          onClick={() => setPendingRemoval(player)}
                        >
                          <Trash2 aria-hidden className="size-4" />
                        </Button>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
                {draft?.parentId === player.id ? renderDraftRow(depth + 1) : null}
                </Fragment>
              );
            })}

            {draft?.parentId == null ? renderDraftRow(0) : null}

            {!rows.length && !draft ? (
              <TableRow className={tableStyles.row}>
                <TableCell className={tableStyles.cell} colSpan={6}>
                  <span className="text-muted-foreground">
                    {t("empty")}
                  </span>
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </AdminDetailTableShell>

      <ConfirmDialog
        open={pendingRemoval != null}
        onOpenChange={(open) => {
          if (!open) setPendingRemoval(null);
        }}
        onConfirm={() => {
          if (pendingRemoval) removePlayer.mutate(pendingRemoval.id);
        }}
        pending={removePlayer.isPending}
        intent={{
            title: t("removeNamed", { name: pendingRemoval?.name ?? t("player") }),
            description: t("deleteDescription"),
            confirmLabel: removePlayer.isPending ? t("removing") : t("removeAction"),
          tone: "danger",
          cascade: [t("cascadeMatchStats"), t("cascadeSubstitutes")]
        }}
      />
    </div>
  );
}
