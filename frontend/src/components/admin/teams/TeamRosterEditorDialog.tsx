"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeftRight,
  Check,
  ChevronsUpDown,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  UserPlus
} from "lucide-react";

import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { UserSearchCombobox } from "@/components/admin/UserSearchCombobox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { notify } from "@/lib/notify";
import { hasUnsavedChanges } from "@/lib/form-change";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type {
  PlayerCreateInput,
  PlayerSubRole,
  PlayerUpdateInput,
  TeamUpdateInput
} from "@/types/admin.types";
import type { Team, Player } from "@/types/team.types";
import type { MinimizedUser } from "@/types/user.types";
import { formatSubRoleLabel } from "@/utils/player";

type TeamRosterEditorDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "create" | "edit";
  tournamentId: number;
  workspaceId: number | null;
  team?: Team | null;
  canCreateTeam: boolean;
  canUpdateTeam: boolean;
  canCreatePlayer: boolean;
  canUpdatePlayer: boolean;
  canDeletePlayer: boolean;
  onSaved?: (team: Team) => void;
};

type TeamFormState = {
  name: string;
  captain_id: number;
};

type PlayerRoleOption = "Tank" | "Damage" | "Support";

type TeamRosterDraftPlayer = {
  draft_id: string;
  player_id: number | null;
  state: "existing" | "new";
  name: string;
  user_id: number;
  user_name: string;
  role: PlayerRoleOption;
  sub_role: string;
  rank: number;
  is_newcomer: boolean;
  is_newcomer_role: boolean;
  is_substitution: boolean;
  related_player_id: number | null;
  related_draft_id: string | null;
};

type PlayerEditorFormState = {
  name: string;
  user_id: number;
  user_name: string;
  role: PlayerRoleOption;
  sub_role: string;
  rank: number;
  is_newcomer: boolean;
  is_newcomer_role: boolean;
};

type PlayerDialogState = {
  mode: "create-root" | "create-substitute" | "edit";
  targetDraftId: string;
  sourceDraftId?: string;
  parentDraftId?: string | null;
  initialState: PlayerEditorFormState;
};

type TeamRosterDraftTreeNode = {
  player: TeamRosterDraftPlayer;
  children: TeamRosterDraftTreeNode[];
};

const PLAYER_ROLE_OPTIONS: PlayerRoleOption[] = ["Tank", "Damage", "Support"];

function getEmptyTeamForm(): TeamFormState {
  return {
    name: "",
    captain_id: 0
  };
}

function getTeamForm(team: Team): TeamFormState {
  return {
    name: team.name,
    captain_id: team.captain_id
  };
}

function normalizePlayerRole(role: string | null | undefined): PlayerRoleOption {
  const normalized = role?.trim().toLowerCase();

  if (normalized === "tank") {
    return "Tank";
  }

  if (normalized === "support") {
    return "Support";
  }

  return "Damage";
}

function createExistingRosterDraftPlayer(player: Player): TeamRosterDraftPlayer {
  return {
    draft_id: `existing:${player.id}`,
    player_id: player.id,
    state: "existing",
    name: player.name,
    user_id: player.user_id,
    user_name: player.user?.name ?? `User #${player.user_id}`,
    role: normalizePlayerRole(player.role),
    sub_role: player.sub_role ?? "",
    rank: player.rank,
    is_newcomer: player.is_newcomer,
    is_newcomer_role: player.is_newcomer_role,
    is_substitution: player.is_substitution,
    related_player_id: player.related_player_id,
    related_draft_id: null
  };
}

function createRosterDraftFromTeam(team: Team): TeamRosterDraftPlayer[] {
  const drafts = (team.players ?? []).map(createExistingRosterDraftPlayer);
  const draftByPlayerId = new Map(
    drafts
      .filter((draft) => draft.player_id != null)
      .map((draft) => [draft.player_id as number, draft.draft_id])
  );

  return drafts.map((draft) => ({
    ...draft,
    related_draft_id:
      draft.related_player_id != null
        ? (draftByPlayerId.get(draft.related_player_id) ?? null)
        : null
  }));
}

function buildRosterInitialSnapshot(team: Team | null) {
  return {
    team: team ? getTeamForm(team) : getEmptyTeamForm(),
    roster: team ? createRosterDraftFromTeam(team) : []
  };
}

function getRolePriority(role: PlayerRoleOption): number {
  if (role === "Tank") return 1;
  if (role === "Damage") return 2;
  if (role === "Support") return 3;
  return 4;
}

function sortRosterDraftPlayers(players: TeamRosterDraftPlayer[]): TeamRosterDraftPlayer[] {
  const draftById = new Map(players.map((player) => [player.draft_id, player]));
  const children = new Map<string, TeamRosterDraftPlayer[]>();
  const roots: TeamRosterDraftPlayer[] = [];

  for (const player of players) {
    const relatedDraftId = player.related_draft_id;
    if (player.is_substitution && relatedDraftId && draftById.has(relatedDraftId)) {
      const entries = children.get(relatedDraftId) ?? [];
      entries.push(player);
      children.set(relatedDraftId, entries);
      continue;
    }
    roots.push(player);
  }

  for (const entries of children.values()) {
    entries.sort((left, right) => right.rank - left.rank);
  }

  roots.sort((left, right) => {
    const roleDelta = getRolePriority(left.role) - getRolePriority(right.role);
    if (roleDelta !== 0) {
      return roleDelta;
    }
    return right.rank - left.rank;
  });

  const flatten = (player: TeamRosterDraftPlayer): TeamRosterDraftPlayer[] => {
    const descendants = children.get(player.draft_id) ?? [];
    return [player, ...descendants.flatMap(flatten)];
  };

  return roots.flatMap(flatten);
}

function buildRosterDraftTree(players: TeamRosterDraftPlayer[]): TeamRosterDraftTreeNode[] {
  const orderedPlayers = sortRosterDraftPlayers(players);
  const nodeByDraftId = new Map<string, TeamRosterDraftTreeNode>(
    orderedPlayers.map((player) => [player.draft_id, { player, children: [] }])
  );
  const roots: TeamRosterDraftTreeNode[] = [];

  for (const player of orderedPlayers) {
    const node = nodeByDraftId.get(player.draft_id);
    if (!node) {
      continue;
    }
    const parent = player.related_draft_id ? nodeByDraftId.get(player.related_draft_id) : null;
    if (player.is_substitution && parent) {
      parent.children.push(node);
      continue;
    }
    roots.push(node);
  }

  return roots;
}

function collectRosterDraftSubtreeIds(players: TeamRosterDraftPlayer[], draftId: string): string[] {
  const childMap = new Map<string, string[]>();

  for (const player of players) {
    if (!player.related_draft_id) {
      continue;
    }
    const entries = childMap.get(player.related_draft_id) ?? [];
    entries.push(player.draft_id);
    childMap.set(player.related_draft_id, entries);
  }

  const collected: string[] = [];
  const visit = (currentDraftId: string) => {
    collected.push(currentDraftId);
    const childIds = childMap.get(currentDraftId) ?? [];
    for (const childId of childIds) {
      visit(childId);
    }
  };

  visit(draftId);
  return collected;
}

function removeRosterDraftPlayer(
  players: TeamRosterDraftPlayer[],
  draftId: string
): {
  players: TeamRosterDraftPlayer[];
  deletedExistingPlayerId: number | null;
} {
  const subtreeIds = new Set(collectRosterDraftSubtreeIds(players, draftId));
  const deletedPlayer = players.find((player) => player.draft_id === draftId) ?? null;

  return {
    players: players.filter((player) => !subtreeIds.has(player.draft_id)),
    deletedExistingPlayerId: deletedPlayer?.player_id ?? null
  };
}

function buildCaptainOptions(players: TeamRosterDraftPlayer[]): Array<{
  user_id: number;
  label: string;
}> {
  const unique = new Map<number, string>();

  for (const player of sortRosterDraftPlayers(players)) {
    if (player.user_id <= 0 || unique.has(player.user_id)) {
      continue;
    }
    unique.set(player.user_id, player.user_name || player.name || `User #${player.user_id}`);
  }

  return Array.from(unique.entries()).map(([user_id, label]) => ({ user_id, label }));
}

function getPlayerEditorState(draft: TeamRosterDraftPlayer | null): PlayerEditorFormState {
  if (!draft) {
    return {
      name: "",
      user_id: 0,
      user_name: "",
      role: "Damage",
      sub_role: "",
      rank: 0,
      is_newcomer: false,
      is_newcomer_role: false
    };
  }

  return {
    name: draft.name,
    user_id: draft.user_id,
    user_name: draft.user_name,
    role: draft.role,
    sub_role: draft.sub_role,
    rank: draft.rank,
    is_newcomer: draft.is_newcomer,
    is_newcomer_role: draft.is_newcomer_role
  };
}

function resolveRelatedPlayerId(
  draft: TeamRosterDraftPlayer,
  createdIdsByDraftId: Map<string, number>,
  rosterByDraftId: Map<string, TeamRosterDraftPlayer>
) {
  if (!draft.is_substitution) {
    return null;
  }

  if (draft.related_draft_id) {
    const parentDraft = rosterByDraftId.get(draft.related_draft_id);
    if (parentDraft?.player_id != null) {
      return parentDraft.player_id;
    }
    const createdId = createdIdsByDraftId.get(draft.related_draft_id);
    if (createdId != null) {
      return createdId;
    }
  }

  return draft.related_player_id ?? null;
}

function buildPlayerCreatePayload(
  draft: TeamRosterDraftPlayer,
  input: {
    teamId: number;
    tournamentId: number;
    relatedPlayerId: number | null;
  }
): PlayerCreateInput {
  return {
    name: draft.name.trim(),
    user_id: draft.user_id,
    team_id: input.teamId,
    tournament_id: input.tournamentId,
    role: draft.role,
    rank: draft.rank,
    sub_role: draft.sub_role || null,
    is_newcomer: draft.is_newcomer,
    is_newcomer_role: draft.is_newcomer_role,
    is_substitution: draft.is_substitution,
    related_player_id: draft.is_substitution ? input.relatedPlayerId : null
  };
}

function buildPlayerUpdatePayload(
  current: TeamRosterDraftPlayer,
  initial: TeamRosterDraftPlayer,
  relatedPlayerId: number | null
): PlayerUpdateInput | null {
  const payload: PlayerUpdateInput = {
    name: current.name.trim(),
    role: current.role,
    rank: current.rank,
    sub_role: current.sub_role || null,
    is_newcomer: current.is_newcomer,
    is_newcomer_role: current.is_newcomer_role,
    is_substitution: current.is_substitution,
    related_player_id: current.is_substitution ? relatedPlayerId : null
  };

  const initialComparable = {
    name: initial.name.trim(),
    role: initial.role,
    rank: initial.rank,
    sub_role: initial.sub_role || null,
    is_newcomer: initial.is_newcomer,
    is_newcomer_role: initial.is_newcomer_role,
    is_substitution: initial.is_substitution,
    related_player_id: initial.is_substitution ? initial.related_player_id : null
  };

  return hasUnsavedChanges(payload, initialComparable) ? payload : null;
}

function clampTeamNumber(value: number, min?: number, max?: number) {
  if (typeof min === "number" && value < min) {
    return min;
  }

  if (typeof max === "number" && value > max) {
    return max;
  }

  return value;
}

function normalizeTeamNumberDraft(value: number) {
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(1)));
}

function TeamNumberInput({
  id,
  value,
  onChange,
  min,
  max,
  step = 1,
  suffix,
  disabled = false
}: {
  id: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState(normalizeTeamNumberDraft(value));

  useEffect(() => {
    setDraft(normalizeTeamNumberDraft(value));
  }, [value]);

  const commitValue = (nextDraft: string) => {
    const nextValue = Number.parseFloat(nextDraft);

    if (Number.isNaN(nextValue)) {
      setDraft(normalizeTeamNumberDraft(value));
      return;
    }

    const clamped = clampTeamNumber(nextValue, min, max);
    setDraft(normalizeTeamNumberDraft(clamped));
    onChange(clamped);
  };

  const stepValue = (direction: -1 | 1) => {
    const nextValue = clampTeamNumber(value + step * direction, min, max);
    setDraft(normalizeTeamNumberDraft(nextValue));
    onChange(nextValue);
  };

  return (
    <div className="flex h-10 overflow-hidden rounded-md border border-input bg-background/80 shadow-sm focus-within:ring-1 focus-within:ring-ring">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-full w-10 shrink-0 rounded-r-none border-r"
        onClick={() => stepValue(-1)}
        disabled={disabled || (typeof min === "number" && value <= min)}
        aria-label={`Decrease ${id}`}
      >
        <span className="sr-only">Decrease</span>-
      </Button>
      <div className="flex min-w-0 flex-1 items-center">
        <Input
          id={id}
          type="text"
          inputMode="decimal"
          value={draft}
          onChange={(event) => {
            const nextDraft = event.target.value.replace(/[^\d.-]/g, "");
            setDraft(nextDraft);

            if (nextDraft && nextDraft !== "-" && nextDraft !== "." && nextDraft !== "-.") {
              commitValue(nextDraft);
            }
          }}
          onBlur={() => commitValue(draft)}
          disabled={disabled}
          className="h-full rounded-none border-0 bg-transparent text-center shadow-none focus-visible:ring-0"
        />
        {suffix ? (
          <span className="shrink-0 pr-3 text-xs font-medium text-muted-foreground">{suffix}</span>
        ) : null}
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-full w-10 shrink-0 rounded-l-none border-l"
        onClick={() => stepValue(1)}
        disabled={disabled || (typeof max === "number" && value >= max)}
        aria-label={`Increase ${id}`}
      >
        <span className="sr-only">Increase</span>+
      </Button>
    </div>
  );
}

function SearchableSelect({
  value,
  options,
  onChange,
  placeholder,
  searchPlaceholder,
  emptyMessage,
  disabled = false
}: {
  value: string;
  options: Array<{ value: string; label: string; meta?: string }>;
  onChange: (value: string) => void;
  placeholder: string;
  searchPlaceholder: string;
  emptyMessage: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const selected = options.find((option) => option.value === value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className="h-10 w-full justify-between border-border/60 bg-background/80 font-normal hover:bg-background/90"
        >
          <span className="truncate" title={selected?.label ?? placeholder}>
            {selected?.label ?? placeholder}
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[var(--radix-popover-trigger-width)] p-0">
        <Command>
          <CommandInput placeholder={searchPlaceholder} />
          <CommandList>
            <CommandEmpty>{emptyMessage}</CommandEmpty>
            <CommandGroup>
              {options.map((option) => (
                <CommandItem
                  key={option.value}
                  value={`${option.label} ${option.meta ?? ""} ${option.value}`}
                  onSelect={() => {
                    onChange(option.value);
                    setOpen(false);
                  }}
                >
                  <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                    <span className="truncate">{option.label}</span>
                    {option.meta ? (
                      <span className="shrink-0 text-xs text-muted-foreground">{option.meta}</span>
                    ) : null}
                  </div>
                  <Check
                    className={cn(
                      "ml-2 h-4 w-4",
                      value === option.value ? "opacity-100" : "opacity-0"
                    )}
                  />
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

function filterSubRoleOptions(subRoles: PlayerSubRole[] | undefined, role: PlayerRoleOption) {
  const catalogRole = role === "Tank" ? "tank" : role === "Support" ? "support" : "damage";
  return (subRoles ?? []).filter((subRole) => subRole.role === catalogRole);
}

function invalidateTeamQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  tournamentId: number,
  teamId?: number
) {
  void Promise.all([
    queryClient.invalidateQueries({ queryKey: ["teams"] }),
    queryClient.invalidateQueries({ queryKey: ["tournaments"] }),
    queryClient.invalidateQueries({ queryKey: ["admin", "tournament", tournamentId] }),
    queryClient.invalidateQueries({ queryKey: ["admin", "tournament", tournamentId, "teams"] }),
    teamId != null
      ? queryClient.invalidateQueries({ queryKey: ["admin", "team", teamId] })
      : Promise.resolve()
  ]);
}

export function TeamRosterEditorDialog({
  open,
  onOpenChange,
  mode,
  tournamentId,
  workspaceId,
  team = null,
  canCreateTeam,
  canUpdateTeam,
  canCreatePlayer,
  canUpdatePlayer,
  canDeletePlayer,
  onSaved
}: TeamRosterEditorDialogProps) {
  const queryClient = useQueryClient();
  const draftCounterRef = useRef(0);
  const isEditing = mode === "edit";
  const canManageRoster = canCreatePlayer || canUpdatePlayer || canDeletePlayer;
  const initialTeamSnapshot = isEditing && team ? getTeamForm(team) : getEmptyTeamForm();
  const initialRosterSnapshot = isEditing && team ? createRosterDraftFromTeam(team) : [];

  const [teamFormData, setTeamFormData] = useState<TeamFormState>(initialTeamSnapshot);
  const [rosterDraftPlayers, setRosterDraftPlayers] =
    useState<TeamRosterDraftPlayer[]>(initialRosterSnapshot);
  const [deletedExistingPlayerIds, setDeletedExistingPlayerIds] = useState<number[]>([]);
  const [teamFormError, setTeamFormError] = useState<string | undefined>();
  const [playerDialogOpen, setPlayerDialogOpen] = useState(false);
  const [playerDialogState, setPlayerDialogState] = useState<PlayerDialogState | null>(null);
  const [playerFormData, setPlayerFormData] = useState<PlayerEditorFormState>(
    getPlayerEditorState(null)
  );
  const [playerFormError, setPlayerFormError] = useState<string | undefined>();

  const { data: playerSubRoles } = useQuery({
    queryKey: ["admin", "player-sub-roles", workspaceId],
    queryFn: () => adminService.getPlayerSubRoles({ workspace_id: workspaceId! }),
    enabled: Boolean(open && workspaceId)
  });

  const rosterByDraftId = useMemo(
    () => new Map(rosterDraftPlayers.map((player) => [player.draft_id, player])),
    [rosterDraftPlayers]
  );
  const rosterTree = useMemo(() => buildRosterDraftTree(rosterDraftPlayers), [rosterDraftPlayers]);
  const captainOptions = useMemo(
    () => buildCaptainOptions(rosterDraftPlayers),
    [rosterDraftPlayers]
  );

  const createNextDraftId = () => {
    draftCounterRef.current += 1;
    return `new:${draftCounterRef.current}`;
  };

  const resetPlayerDialog = () => {
    setPlayerDialogOpen(false);
    setPlayerDialogState(null);
    setPlayerFormData(getPlayerEditorState(null));
    setPlayerFormError(undefined);
  };

  const syncCaptainSelection = (nextRoster: TeamRosterDraftPlayer[]) => {
    const nextOptions = buildCaptainOptions(nextRoster);
    setTeamFormData((current) => ({
      ...current,
      captain_id: nextOptions.some((option) => option.user_id === current.captain_id)
        ? current.captain_id
        : 0
    }));
  };

  const openPlayerCreateDialog = (parentDraft?: TeamRosterDraftPlayer) => {
    const draftId = createNextDraftId();
    const dialogState: PlayerDialogState = {
      mode: parentDraft ? "create-substitute" : "create-root",
      targetDraftId: draftId,
      parentDraftId: parentDraft?.draft_id ?? null,
      initialState: getPlayerEditorState(null)
    };

    setPlayerDialogState(dialogState);
    setPlayerFormData(dialogState.initialState);
    setPlayerFormError(undefined);
    setPlayerDialogOpen(true);
  };

  const openPlayerEditDialog = (draft: TeamRosterDraftPlayer) => {
    const dialogState: PlayerDialogState = {
      mode: "edit",
      targetDraftId: draft.draft_id,
      sourceDraftId: draft.draft_id,
      parentDraftId: draft.related_draft_id,
      initialState: getPlayerEditorState(draft)
    };

    setPlayerDialogState(dialogState);
    setPlayerFormData(dialogState.initialState);
    setPlayerFormError(undefined);
    setPlayerDialogOpen(true);
  };

  const handleRemoveRosterPlayer = (draft: TeamRosterDraftPlayer) => {
    const canDeleteDraft = draft.state === "new" ? canCreatePlayer : canDeletePlayer;
    if (!canDeleteDraft) {
      return;
    }

    const nextState = removeRosterDraftPlayer(rosterDraftPlayers, draft.draft_id);
    setRosterDraftPlayers(nextState.players);
    if (nextState.deletedExistingPlayerId != null) {
      setDeletedExistingPlayerIds((current) =>
        current.includes(nextState.deletedExistingPlayerId as number)
          ? current
          : [...current, nextState.deletedExistingPlayerId as number]
      );
    }
    syncCaptainSelection(nextState.players);
  };

  const saveTeamMutation = useMutation({
    meta: { suppressErrorToast: true },
    mutationFn: async (variables: {
      teamData: TeamFormState;
      roster: TeamRosterDraftPlayer[];
      deletedIds: number[];
      initialTeam: Team | null;
      canPatchTeam: boolean;
    }) => {
      const { teamData, roster, deletedIds, initialTeam, canPatchTeam } = variables;

      const initialByPlayerId = new Map(
        (initialTeam ? createRosterDraftFromTeam(initialTeam) : [])
          .filter((player) => player.player_id != null)
          .map((player) => [player.player_id as number, player])
      );

      let savedTeam: Team;
      let deferCaptainPatch = false;

      if (!isEditing) {
        savedTeam = await adminService.createTeam({
          name: teamData.name.trim(),
          tournament_id: tournamentId,
          captain_id: teamData.captain_id
        });
      } else if (canPatchTeam) {
        const captainInExistingRoster = roster.some(
          (player) => player.state === "existing" && player.user_id === teamData.captain_id
        );
        const initialPatch: TeamUpdateInput = {
          name: teamData.name.trim()
        };

        if (captainInExistingRoster) {
          initialPatch.captain_id = teamData.captain_id;
        } else {
          deferCaptainPatch = true;
        }

        savedTeam = await adminService.updateTeam(team!.id, initialPatch);
      } else {
        savedTeam = team!;
      }

      const rosterMap = new Map(roster.map((player) => [player.draft_id, player]));
      const createdIdsByDraftId = new Map<string, number>();

      for (const player of roster) {
        if (player.player_id != null) {
          createdIdsByDraftId.set(player.draft_id, player.player_id);
        }
      }

      const newBasePlayers = roster.filter(
        (player) => player.state === "new" && !player.is_substitution
      );
      for (const draft of newBasePlayers) {
        const createdPlayer = await adminService.createPlayer(
          buildPlayerCreatePayload(draft, {
            teamId: savedTeam.id,
            tournamentId,
            relatedPlayerId: null
          })
        );
        createdIdsByDraftId.set(draft.draft_id, createdPlayer.id);
      }

      let pendingSubstitutes = roster.filter(
        (player) => player.state === "new" && player.is_substitution
      );
      while (pendingSubstitutes.length > 0) {
        const unresolved: TeamRosterDraftPlayer[] = [];
        let progressed = false;

        for (const draft of pendingSubstitutes) {
          const relatedPlayerId = resolveRelatedPlayerId(draft, createdIdsByDraftId, rosterMap);
          if (relatedPlayerId == null) {
            unresolved.push(draft);
            continue;
          }

          const createdPlayer = await adminService.createPlayer(
            buildPlayerCreatePayload(draft, {
              teamId: savedTeam.id,
              tournamentId,
              relatedPlayerId
            })
          );
          createdIdsByDraftId.set(draft.draft_id, createdPlayer.id);
          progressed = true;
        }

        if (!progressed) {
          throw new Error("Unable to resolve substitute chain before save.");
        }

        pendingSubstitutes = unresolved;
      }

      for (const draft of roster) {
        if (draft.state !== "existing" || draft.player_id == null) {
          continue;
        }

        const initialDraft = initialByPlayerId.get(draft.player_id);
        if (!initialDraft) {
          continue;
        }

        const relatedPlayerId = resolveRelatedPlayerId(draft, createdIdsByDraftId, rosterMap);
        const payload = buildPlayerUpdatePayload(draft, initialDraft, relatedPlayerId);
        if (!payload) {
          continue;
        }

        await adminService.updatePlayer(draft.player_id, payload);
      }

      for (const playerId of deletedIds) {
        await adminService.deletePlayer(playerId);
      }

      if (isEditing && canPatchTeam && deferCaptainPatch) {
        await adminService.updateTeam(savedTeam.id, { captain_id: teamData.captain_id });
      }

      return savedTeam;
    },
    onSuccess: (savedTeam) => {
      invalidateTeamQueries(queryClient, tournamentId, savedTeam.id);
      onSaved?.(savedTeam);
      onOpenChange(false);
      notify.success(isEditing ? "Team roster updated" : "Team and roster created");
    },
    onError: (error: Error) => {
      setTeamFormError(error.message);
    }
  });

  const handlePlayerDialogSubmit = (event: FormEvent) => {
    event.preventDefault();

    if (!playerDialogState) {
      return;
    }

    if (!playerFormData.name.trim()) {
      setPlayerFormError("Player name is required.");
      return;
    }

    const existingDraft =
      playerDialogState.sourceDraftId != null
        ? (rosterByDraftId.get(playerDialogState.sourceDraftId) ?? null)
        : null;

    const requiresUser = existingDraft?.state !== "existing";
    if (requiresUser && playerFormData.user_id <= 0) {
      setPlayerFormError("Linked user is required.");
      return;
    }

    const nextDraft: TeamRosterDraftPlayer = {
      draft_id: playerDialogState.targetDraftId,
      player_id: existingDraft?.player_id ?? null,
      state: existingDraft?.state ?? "new",
      name: playerFormData.name.trim(),
      user_id: existingDraft?.state === "existing" ? existingDraft.user_id : playerFormData.user_id,
      user_name:
        existingDraft?.state === "existing"
          ? existingDraft.user_name
          : playerFormData.user_name || playerFormData.name.trim(),
      role: playerFormData.role,
      sub_role: playerFormData.sub_role,
      rank: playerFormData.rank,
      is_newcomer: playerFormData.is_newcomer,
      is_newcomer_role: playerFormData.is_newcomer_role,
      is_substitution:
        playerDialogState.mode === "create-substitute"
          ? true
          : (existingDraft?.is_substitution ?? false),
      related_player_id:
        playerDialogState.mode === "create-substitute"
          ? playerDialogState.parentDraftId
            ? (rosterByDraftId.get(playerDialogState.parentDraftId)?.player_id ?? null)
            : null
          : (existingDraft?.related_player_id ?? null),
      related_draft_id:
        playerDialogState.mode === "create-substitute"
          ? (playerDialogState.parentDraftId ?? null)
          : (existingDraft?.related_draft_id ?? null)
    };

    const nextRoster =
      playerDialogState.mode === "edit" && playerDialogState.sourceDraftId
        ? rosterDraftPlayers.map((player) =>
            player.draft_id === playerDialogState.sourceDraftId ? nextDraft : player
          )
        : [...rosterDraftPlayers, nextDraft];

    setRosterDraftPlayers(nextRoster);
    resetPlayerDialog();
  };

  const handleTeamSubmit = (event: FormEvent) => {
    event.preventDefault();

    if (!teamFormData.name.trim()) {
      setTeamFormError("Team name is required.");
      return;
    }

    if (rosterDraftPlayers.length === 0) {
      setTeamFormError("At least one roster member is required.");
      return;
    }

    if (!captainOptions.some((option) => option.user_id === teamFormData.captain_id)) {
      setTeamFormError("Captain must be selected from the current roster.");
      return;
    }

    if (!isEditing && !canCreateTeam) {
      setTeamFormError("You do not have permission to create teams.");
      return;
    }

    if (isEditing && !canUpdateTeam && !canManageRoster) {
      setTeamFormError("You do not have permission to update this team.");
      return;
    }

    saveTeamMutation.mutate({
      teamData: teamFormData,
      roster: rosterDraftPlayers,
      deletedIds: deletedExistingPlayerIds,
      initialTeam: team,
      canPatchTeam: isEditing ? canUpdateTeam : true
    });
  };

  const rosterSnapshot = buildRosterInitialSnapshot(isEditing ? team : null);
  const isTeamDirty =
    open &&
    hasUnsavedChanges(
      {
        team: teamFormData,
        roster: rosterDraftPlayers,
        deletedIds: deletedExistingPlayerIds
      },
      {
        team: rosterSnapshot.team,
        roster: rosterSnapshot.roster,
        deletedIds: [] as number[]
      }
    );

  const playerDialogDraft = playerDialogState?.sourceDraftId
    ? (rosterByDraftId.get(playerDialogState.sourceDraftId) ?? null)
    : null;
  const playerDialogInitial = playerDialogState?.initialState ?? getPlayerEditorState(null);
  const isPlayerDirty = playerDialogOpen && hasUnsavedChanges(playerFormData, playerDialogInitial);
  const playerSubRoleOptions = filterSubRoleOptions(playerSubRoles, playerFormData.role);
  const playerSubRoleSelectOptions = [
    { value: "none", label: "No sub-role" },
    ...playerSubRoleOptions.map((subRole) => ({
      value: subRole.slug,
      label: subRole.label,
      meta: subRole.slug
    }))
  ];

  const renderRosterNodes = (nodes: TeamRosterDraftTreeNode[], depth = 0): React.ReactNode =>
    nodes.map((node) => {
      const draft = node.player;
      const canEditDraft = draft.state === "new" ? canCreatePlayer : canUpdatePlayer;
      const canDeleteDraft = draft.state === "new" ? canCreatePlayer : canDeletePlayer;

      return (
        <div key={draft.draft_id} className={cn("space-y-2", depth > 0 && "ml-5 border-l pl-4")}>
          <div className="rounded-lg border border-border/60 bg-background/60 p-3">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{draft.name || "Unnamed player"}</span>
                  <Badge variant="outline">{draft.role}</Badge>
                  {draft.is_substitution ? <Badge variant="secondary">Substitute</Badge> : null}
                  {draft.state === "new" ? <Badge variant="outline">New</Badge> : null}
                </div>
                <div className="text-sm text-muted-foreground">
                  {draft.user_id > 0
                    ? `${draft.user_name} · Rank ${draft.rank}`
                    : "User not selected yet"}
                </div>
                <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <span>{formatSubRoleLabel(draft.sub_role) ?? "No sub-role"}</span>
                  {draft.is_newcomer ? (
                    <StatusIcon icon={Sparkles} label="Newcomer" variant="warning" />
                  ) : null}
                  {draft.is_newcomer_role ? (
                    <StatusIcon icon={ArrowLeftRight} label="Newcomer role" variant="info" />
                  ) : null}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {canCreatePlayer ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => openPlayerCreateDialog(draft)}
                  >
                    <UserPlus className="mr-2 h-4 w-4" />
                    Add Substitute
                  </Button>
                ) : null}
                {canEditDraft ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => openPlayerEditDialog(draft)}
                  >
                    <Pencil className="h-4 w-4" />
                  </Button>
                ) : null}
                {canDeleteDraft ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="text-destructive"
                    onClick={() => handleRemoveRosterPlayer(draft)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                ) : null}
              </div>
            </div>
          </div>
          {node.children.length ? renderRosterNodes(node.children, depth + 1) : null}
        </div>
      );
    });

  return (
    <>
      <EntityFormDialog
        open={open}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setTeamFormError(undefined);
            resetPlayerDialog();
          }
          onOpenChange(nextOpen);
        }}
        title={isEditing ? "Edit Team & Roster" : "Create Team & Roster"}
        description="Manage team identity, captain assignment, and the full tournament roster in one place."
        onSubmit={handleTeamSubmit}
        isSubmitting={saveTeamMutation.isPending}
        submittingLabel={isEditing ? "Saving team..." : "Creating team..."}
        errorMessage={teamFormError}
        isDirty={isTeamDirty}
        contentClassName="h-[min(900px,calc(100vh-2rem))] max-h-[calc(100dvh-2rem)] max-w-4xl"
      >
        <div className="space-y-5">
          <div className="rounded-md border border-border/60 bg-muted/20 p-3">
            <p className="text-sm font-medium">
              {isEditing ? "Edit team data and roster" : "Create a team with its starting roster"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Captain can only be selected from the roster below. Deleting a player removes its
              substitute chain.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="workspace-team-name">Team Name</Label>
            <Input
              id="workspace-team-name"
              value={teamFormData.name}
              disabled={isEditing && !canUpdateTeam}
              placeholder="Team name"
              onChange={(event) =>
                setTeamFormData((current) => ({ ...current, name: event.target.value }))
              }
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="workspace-team-captain">Captain</Label>
            <Select
              value={teamFormData.captain_id > 0 ? String(teamFormData.captain_id) : ""}
              onValueChange={(value) =>
                setTeamFormData((current) => ({
                  ...current,
                  captain_id: Number.parseInt(value, 10)
                }))
              }
              disabled={isEditing && !canUpdateTeam}
            >
              <SelectTrigger id="workspace-team-captain">
                <SelectValue placeholder="Select captain from roster" />
              </SelectTrigger>
              <SelectContent>
                {captainOptions.map((option) => (
                  <SelectItem key={option.user_id} value={String(option.user_id)}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {captainOptions.length
                ? "Captain options update automatically from the active roster."
                : "Add at least one player before choosing a captain."}
            </p>
          </div>

          <div className="space-y-3 rounded-lg border border-border/60 p-4">
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-sm font-medium">Roster</p>
                <p className="text-xs text-muted-foreground">
                  {rosterDraftPlayers.length
                    ? `${rosterDraftPlayers.length} active roster records`
                    : "No roster members yet."}
                </p>
              </div>
              {canCreatePlayer ? (
                <Button type="button" variant="outline" onClick={() => openPlayerCreateDialog()}>
                  <Plus className="mr-2 h-4 w-4" />
                  Add Player
                </Button>
              ) : null}
            </div>

            {rosterTree.length ? (
              <div className="space-y-3">{renderRosterNodes(rosterTree)}</div>
            ) : (
              <div className="rounded-lg border border-dashed border-border/70 bg-muted/20 p-4 text-sm text-muted-foreground">
                Create at least one player to make the team valid.
              </div>
            )}
          </div>
        </div>
      </EntityFormDialog>

      <EntityFormDialog
        open={playerDialogOpen}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            resetPlayerDialog();
          } else {
            setPlayerDialogOpen(true);
          }
        }}
        title={
          playerDialogState?.mode === "edit"
            ? "Edit Roster Member"
            : playerDialogState?.mode === "create-substitute"
              ? "Add Substitute"
              : "Add Player"
        }
        description="Changes here stay local until you save the team dialog."
        onSubmit={handlePlayerDialogSubmit}
        isSubmitting={false}
        errorMessage={playerFormError}
        isDirty={isPlayerDirty}
      >
        <div className="space-y-4">
          <div>
            <Label htmlFor="team-roster-player-name">Player Name</Label>
            <Input
              id="team-roster-player-name"
              value={playerFormData.name}
              onChange={(event) =>
                setPlayerFormData((current) => ({ ...current, name: event.target.value }))
              }
            />
          </div>

          <div>
            <Label htmlFor="team-roster-player-user">Linked User</Label>
            <UserSearchCombobox
              id="team-roster-player-user"
              value={
                playerDialogDraft?.state === "existing"
                  ? playerDialogDraft.user_id
                  : playerFormData.user_id || undefined
              }
              selectedName={
                playerDialogDraft?.state === "existing"
                  ? playerDialogDraft.user_name
                  : playerFormData.user_name || undefined
              }
              placeholder="Search user by name"
              searchPlaceholder="Search user..."
              disabled={playerDialogDraft?.state === "existing"}
              allowClear={playerDialogDraft?.state !== "existing"}
              onSelect={(user: MinimizedUser | undefined) =>
                setPlayerFormData((current) => ({
                  ...current,
                  user_id: user?.id ?? 0,
                  user_name: user?.name ?? "",
                  name: current.name || user?.name || ""
                }))
              }
            />
            {playerDialogDraft?.state === "existing" ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Linked user cannot be changed for persisted roster members.
              </p>
            ) : null}
          </div>

          <div>
            <Label htmlFor="team-roster-player-role">Role</Label>
            <Select
              value={playerFormData.role}
              onValueChange={(value) =>
                setPlayerFormData((current) => ({
                  ...current,
                  role: normalizePlayerRole(value),
                  sub_role: ""
                }))
              }
            >
              <SelectTrigger id="team-roster-player-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PLAYER_ROLE_OPTIONS.map((role) => (
                  <SelectItem key={role} value={role}>
                    {role}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label htmlFor="team-roster-player-sub-role">Sub-role</Label>
            <SearchableSelect
              value={playerFormData.sub_role || "none"}
              options={playerSubRoleSelectOptions}
              placeholder="Select sub-role"
              searchPlaceholder="Search sub-role..."
              emptyMessage="No sub-roles found."
              onChange={(value) =>
                setPlayerFormData((current) => ({
                  ...current,
                  sub_role: value === "none" ? "" : value
                }))
              }
            />
          </div>

          <div>
            <Label htmlFor="team-roster-player-rank">Rank</Label>
            <TeamNumberInput
              id="team-roster-player-rank"
              value={playerFormData.rank}
              min={0}
              step={1}
              onChange={(value) =>
                setPlayerFormData((current) => ({
                  ...current,
                  rank: value
                }))
              }
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center space-x-2">
              <Checkbox
                id="team-roster-player-newcomer"
                checked={playerFormData.is_newcomer}
                onCheckedChange={(checked) =>
                  setPlayerFormData((current) => ({
                    ...current,
                    is_newcomer: checked === true
                  }))
                }
              />
              <Label htmlFor="team-roster-player-newcomer" className="cursor-pointer">
                Newcomer
              </Label>
            </div>

            <div className="flex items-center space-x-2">
              <Checkbox
                id="team-roster-player-newcomer-role"
                checked={playerFormData.is_newcomer_role}
                onCheckedChange={(checked) =>
                  setPlayerFormData((current) => ({
                    ...current,
                    is_newcomer_role: checked === true
                  }))
                }
              />
              <Label htmlFor="team-roster-player-newcomer-role" className="cursor-pointer">
                Newcomer role
              </Label>
            </div>
          </div>
        </div>
      </EntityFormDialog>
    </>
  );
}
