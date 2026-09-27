"use client";

import { Fragment, useMemo, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Check, Sparkles, Trash2, UserPlus, X } from "lucide-react";

import {
  AdminDetailTableShell,
  getAdminDetailTableStyles
} from "@/components/admin/AdminDetailTable";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { UserSearchCombobox } from "@/components/admin/UserSearchCombobox";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  PLAYER_ROLE_OPTIONS,
  filterSubRoleOptions,
  normalizePlayerRole,
  subRoleCatalogRole,
  type PlayerRoleOption
} from "@/lib/roster/player-role";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { PlayerCreateInput, PlayerUpdateInput } from "@/types/admin.types";
import type { Player } from "@/types/team.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import { formatSubRoleLabel, sortTeamPlayers } from "@/lib/player";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

interface TeamRosterEditorProps {
  teamId: number;
  tournamentId: number;
  workspaceId: number | null;
  players: Player[];
  /** Grid the tournament scores ranks against; falls back to the workspace grid. */
  divisionGrid: DivisionGridVersion | null;
  canCreatePlayer: boolean;
  canUpdatePlayer: boolean;
  canDeletePlayer: boolean;
}

/** A roster row being composed. `parentId` set means it replaces that player. */
interface RosterDraft {
  parentId: number | null;
  userId: number;
  userName: string;
  name: string;
  role: PlayerRoleOption;
  rank: number;
  subRole: string;
}

const NO_SUB_ROLE = "none";
const NO_SUB_ROLE_LABEL = "No sub-role";

function emptyDraft(parentId: number | null, role: PlayerRoleOption = "Damage"): RosterDraft {
  return { parentId, userId: 0, userName: "", name: "", role, rank: 0, subRole: "" };
}

/**
 * Roster order (role, then rank, substitutes under the slot they cover) plus the
 * nesting depth each row renders at. Walks `related_player_id` upwards with a
 * seen-set so a corrupt cycle degrades to depth 0 instead of hanging.
 */
function buildRosterRows(players: Player[]): Array<{ player: Player; depth: number }> {
  const byId = new Map(players.map((player) => [player.id, player]));

  const depthOf = (player: Player) => {
    const seen = new Set<number>([player.id]);
    let current = player;
    let depth = 0;

    while (current.is_substitution && current.related_player_id != null) {
      const parent = byId.get(current.related_player_id);
      if (!parent || seen.has(parent.id)) break;
      seen.add(parent.id);
      depth += 1;
      current = parent;
    }

    return depth;
  };

  return sortTeamPlayers(players).map((player) => ({ player, depth: depthOf(player) }));
}

/**
 * Text/number field that keeps a local draft and persists on blur or Enter.
 * Escape restores the saved value. Used instead of the pencil-reveal
 * `InlineEditText` because this whole table is an editor: one click on the
 * value, type, tab away.
 */
function CommitField({
  value,
  onCommit,
  label,
  disabled,
  className,
  inputMode
}: Readonly<{
  value: string;
  onCommit: (next: string) => void;
  /** Accessible name, e.g. `Rank of Nickname`. */
  label: string;
  disabled?: boolean;
  className?: string;
  inputMode?: "numeric";
}>) {
  const [draft, setDraft] = useState<string | null>(null);

  const commit = () => {
    if (draft === null) return;
    const next = draft.trim();
    setDraft(null);
    if (next !== value) {
      onCommit(next);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      event.currentTarget.blur();
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setDraft(null);
    }
  };

  return (
    <Input
      aria-label={label}
      value={draft ?? value}
      disabled={disabled}
      inputMode={inputMode}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={handleKeyDown}
      className={cn(
        // Quiet but present: a field the operator can see is a field, without
        // 40 hard-bordered boxes fighting each other down the table.
        "h-8 border-border/50 bg-background/40 px-2 hover:border-input",
        className
      )}
    />
  );
}

/**
 * Role picker whose trigger is the same glyph the rest of the site shows.
 *
 * The accessible name carries the field *and* the current value, because an
 * `aria-label` on a Radix trigger overrides the value it renders — an icon-only
 * trigger labelled just "Role of X" would never announce which role is set.
 */
function RoleSelect({
  value,
  onChange,
  label,
  disabled
}: Readonly<{
  value: PlayerRoleOption;
  onChange: (role: PlayerRoleOption) => void;
  /** Field name, e.g. `Role of Nickname`. */
  label: string;
  disabled?: boolean;
}>) {
  return (
    <Select
      value={value}
      onValueChange={(next) => onChange(normalizePlayerRole(next))}
      disabled={disabled}
    >
      <SelectTrigger aria-label={`${label}: ${value}`} className="h-8 w-[4.5rem] gap-1 px-2">
        <SelectValue>
          <PlayerRoleIcon role={value} size={18} decorative />
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {PLAYER_ROLE_OPTIONS.map((role) => (
          <SelectItem key={role} value={role}>
            <span className="flex items-center gap-2">
              <PlayerRoleIcon role={role} size={16} decorative />
              {role}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function SubRoleSelect({
  value,
  options,
  onChange,
  label,
  disabled
}: Readonly<{
  value: string;
  options: Array<{ slug: string; label: string }>;
  onChange: (subRole: string) => void;
  /** Field name, e.g. `Sub-role of Nickname`. */
  label: string;
  disabled?: boolean;
}>) {
  // A saved sub-role missing from the catalog (renamed, deactivated) still needs
  // an option, or Radix renders the trigger empty.
  const items =
    !value || options.some((option) => option.slug === value)
      ? options
      : [...options, { slug: value, label: formatSubRoleLabel(value) ?? value }];
  const selectedLabel = items.find((option) => option.slug === value)?.label ?? NO_SUB_ROLE_LABEL;

  return (
    <Select
      value={value || NO_SUB_ROLE}
      onValueChange={(next) => onChange(next === NO_SUB_ROLE ? "" : next)}
      disabled={disabled}
    >
      <SelectTrigger aria-label={`${label}: ${selectedLabel}`} className="h-8 w-[9.5rem] px-2">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NO_SUB_ROLE}>{NO_SUB_ROLE_LABEL}</SelectItem>
        {items.map((option) => (
          <SelectItem key={option.slug} value={option.slug}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function FlagToggle({
  active,
  label,
  icon: Icon,
  onToggle,
  disabled
}: Readonly<{
  active: boolean;
  label: string;
  icon: typeof Sparkles;
  onToggle: () => void;
  disabled?: boolean;
}>) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className={cn("size-7", active ? "text-warning" : "text-muted-foreground/70")}
          aria-label={label}
          aria-pressed={active}
          disabled={disabled}
          onClick={onToggle}
        >
          <Icon aria-hidden className="size-4" />
        </Button>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}

/**
 * The roster, editable in place.
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
  players,
  divisionGrid,
  canCreatePlayer,
  canUpdatePlayer,
  canDeletePlayer
}: Readonly<TeamRosterEditorProps>) {
  const queryClient = useQueryClient();
  const tableStyles = getAdminDetailTableStyles("compact");
  const [draft, setDraft] = useState<RosterDraft | null>(null);
  const [pendingRemoval, setPendingRemoval] = useState<Player | null>(null);

  const { data: playerSubRoles } = useQuery({
    queryKey: adminQueryKeys.playerSubRoles(workspaceId),
    queryFn: () => adminService.getPlayerSubRoles({ workspace_id: workspaceId! }),
    enabled: workspaceId != null
  });

  const rows = useMemo(() => buildRosterRows(players), [players]);

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

  /**
   * Flex has no rows in the `player_sub_role` catalog, so a Flex row offers
   * nothing and its sub-role select renders inert rather than empty.
   */
  const subRoleOptionsFor = (role: string | null | undefined) =>
    filterSubRoleOptions(playerSubRoles, role).map((subRole) => ({
      slug: subRole.slug,
      label: subRole.label
    }));

  const substituteCount = players.filter((player) => player.is_substitution).length;
  const draftIsValid = draft != null && draft.userId > 0 && draft.name.trim().length > 0;

  const submitDraft = () => {
    if (!draft || !draftIsValid) return;
    addPlayer.mutate({
      name: draft.name.trim(),
      user_id: draft.userId,
      team_id: teamId,
      tournament_id: tournamentId,
      role: draft.role,
      rank: draft.rank,
      sub_role: draft.subRole || null,
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
            selectedName={draft.userName || undefined}
            placeholder="Link a user"
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
            aria-label="New player name"
            value={draft.name}
            placeholder="Roster name"
            className="h-8"
            onChange={(event) =>
              setDraft((current) => (current ? { ...current, name: event.target.value } : current))
            }
          />
        </div>
      </TableCell>
      <TableCell className={tableStyles.cell}>
        <RoleSelect
          value={draft.role}
          label="Role of the new player"
          onChange={(role) =>
            setDraft((current) => (current ? { ...current, role, subRole: "" } : current))
          }
        />
      </TableCell>
      <TableCell className={tableStyles.numericCell}>
        <Input
          aria-label="Rank of the new player"
          value={String(draft.rank)}
          inputMode="numeric"
          className="h-8 w-20 tabular-nums"
          onChange={(event) => {
            const next = Number.parseInt(event.target.value, 10);
            setDraft((current) =>
              current ? { ...current, rank: Number.isFinite(next) && next > 0 ? next : 0 } : current
            );
          }}
        />
      </TableCell>
      <TableCell className={tableStyles.cell}>
        <SubRoleSelect
          value={draft.subRole}
          options={subRoleOptionsFor(draft.role)}
          disabled={subRoleCatalogRole(draft.role) == null}
          label="Sub-role of the new player"
          onChange={(subRole) =>
            setDraft((current) => (current ? { ...current, subRole } : current))
          }
        />
      </TableCell>
      <TableCell className={tableStyles.cell}>
        {draft.parentId != null ? <Badge variant="secondary">Substitute</Badge> : null}
      </TableCell>
      <TableCell className={tableStyles.cell}>
        <div className="flex items-center justify-end gap-1">
          <Button
            type="button"
            size="sm"
            disabled={!draftIsValid || addPlayer.isPending}
            onClick={submitDraft}
          >
            <Check aria-hidden className="mr-1.5 size-4" />
            {addPlayer.isPending ? "Adding…" : "Add"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8"
            aria-label="Cancel adding a player"
            onClick={() => setDraft(null)}
          >
            <X aria-hidden className="size-4" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  ) : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm tabular-nums text-muted-foreground">
          {players.length
            ? `${players.length - substituteCount} starters · ${substituteCount} substitutes`
            : "No players yet — add the first one to make the team valid."}
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
            Add player
          </Button>
        ) : null}
      </div>

      <AdminDetailTableShell>
        <Table>
          <TableHeader>
            <TableRow className={tableStyles.headerRow}>
              <TableHead className={tableStyles.head}>Player</TableHead>
              <TableHead className={tableStyles.head}>Role</TableHead>
              <TableHead className={tableStyles.head}>Rank</TableHead>
              <TableHead className={tableStyles.head}>Sub-role</TableHead>
              <TableHead className={tableStyles.head}>Flags</TableHead>
              <TableHead className={cn(tableStyles.head, "text-right")}>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(({ player, depth }) => {
              const role = normalizePlayerRole(player.role);
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
                        label={`Roster name of ${player.name}`}
                        disabled={!canUpdatePlayer}
                        className="font-medium"
                        onCommit={(name) => {
                          if (name) {
                            patch(player, { name });
                          }
                        }}
                      />
                      <p className="truncate px-2 text-xs text-muted-foreground">
                        {player.user?.name ?? `User #${player.user_id}`}
                      </p>
                    </div>
                  </TableCell>

                  <TableCell className={tableStyles.cell}>
                    <RoleSelect
                      value={role}
                      label={`Role of ${player.name}`}
                      disabled={!canUpdatePlayer}
                      onChange={(next) => patch(player, { role: next, sub_role: null })}
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
                        value={String(player.rank)}
                        label={`Rank of ${player.name}`}
                        disabled={!canUpdatePlayer}
                        inputMode="numeric"
                        className="w-20 tabular-nums"
                        onCommit={(next) => {
                          const rank = Number.parseInt(next, 10);
                          if (Number.isFinite(rank) && rank >= 0) {
                            patch(player, { rank });
                          }
                        }}
                      />
                    </div>
                  </TableCell>

                  <TableCell className={tableStyles.cell}>
                    <SubRoleSelect
                      value={player.sub_role ?? ""}
                      options={subRoleOptionsFor(player.role)}
                      label={`Sub-role of ${player.name}`}
                      disabled={!canUpdatePlayer || subRoleCatalogRole(player.role) == null}
                      onChange={(subRole) => patch(player, { sub_role: subRole || null })}
                    />
                  </TableCell>

                  <TableCell className={tableStyles.cell}>
                    <div className="flex items-center gap-0.5">
                      <FlagToggle
                        active={player.is_newcomer}
                        icon={Sparkles}
                        label={`Newcomer — ${player.name}`}
                        disabled={!canUpdatePlayer}
                        onToggle={() => patch(player, { is_newcomer: !player.is_newcomer })}
                      />
                      <FlagToggle
                        active={player.is_newcomer_role}
                        icon={ArrowLeftRight}
                        label={`New to this role — ${player.name}`}
                        disabled={!canUpdatePlayer}
                        onToggle={() =>
                          patch(player, { is_newcomer_role: !player.is_newcomer_role })
                        }
                      />
                      {player.is_substitution ? <Badge variant="secondary">Sub</Badge> : null}
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
                          aria-label={`Replace ${player.name} with a substitute`}
                          disabled={draft != null}
                          onClick={() => setDraft(emptyDraft(player.id, role))}
                        >
                          Replace
                        </Button>
                      ) : null}
                      {canDeletePlayer ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="size-8 text-destructive"
                          aria-label={`Remove ${player.name} from the roster`}
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
                    This team has no players. A team needs at least one to appear in a bracket.
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
          title: `Remove ${pendingRemoval?.name ?? "player"}`,
          description:
            "The roster record and its match statistics are removed permanently. This cannot be undone.",
          confirmLabel: removePlayer.isPending ? "Removing…" : "Remove",
          tone: "danger",
          cascade: ["Match statistics for this player", "Substitutes linked to this slot"]
        }}
      />
    </div>
  );
}
