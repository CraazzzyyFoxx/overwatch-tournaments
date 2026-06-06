"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, NotebookPen, Plus, Save, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { BalancerPlayerRecord, BalancerPlayerRoleEntry, BalancerRoleCode, BalancerRoleSubtype } from "@/types/balancer-admin.types";
import { useQuery } from "@tanstack/react-query";
import adminService from "@/services/admin.service";
import { useCurrentWorkspaceId } from "@/hooks/useCurrentWorkspace";

const ROLE_OPTIONS: Array<{ value: BalancerRoleCode; label: string }> = [
  { value: "tank", label: "Tank" },
  { value: "dps", label: "Damage" },
  { value: "support", label: "Support" },
];

// Dynamic subtype options are fetched from the workspace sub-roles catalog

function resolveRankFromDivision(divisionNumber: number | null): number | null {
  if (divisionNumber == null) {
    return null;
  }

  const map: Record<number, number> = {
    20: 100,
    19: 250,
    18: 350,
    17: 450,
    16: 550,
    15: 650,
    14: 750,
    13: 850,
    12: 950,
    11: 1050,
    10: 1150,
    9: 1250,
    8: 1350,
    7: 1450,
    6: 1550,
    5: 1650,
    4: 1750,
    3: 1850,
    2: 1950,
    1: 2000,
  };

  return map[divisionNumber] ?? null;
}

function normalizeRoleEntries(entries: BalancerPlayerRoleEntry[]): BalancerPlayerRoleEntry[] {
  const seen = new Set<BalancerRoleCode>();
  const sorted = [...entries].sort((a, b) => a.priority - b.priority);
  const normalized: BalancerPlayerRoleEntry[] = [];

  for (const entry of sorted) {
    if (seen.has(entry.role)) {
      continue;
    }
    seen.add(entry.role);
    const divisionNumber = entry.division_number ?? null;
    normalized.push({
      role: entry.role,
      subtype: entry.subtype ?? null,
      priority: normalized.length + 1,
      division_number: divisionNumber,
      rank_value: entry.rank_value ?? resolveRankFromDivision(divisionNumber),
      is_active: entry.is_active ?? true,
    });
  }

  return normalized;
}

type PoolPlayerCardProps = {
  player: BalancerPlayerRecord;
  onSave: (playerId: number, payload: { role_entries_json: BalancerPlayerRoleEntry[]; is_in_pool: boolean; admin_notes: string | null }) => void;
  onRemove?: (playerId: number) => void;
  saving?: boolean;
};

export function PoolPlayerCard({ player, onSave, onRemove, saving = false }: PoolPlayerCardProps) {
  const workspaceId = useCurrentWorkspaceId();
  const { data: subRoles } = useQuery({
    queryKey: ["admin", "player-sub-roles", workspaceId],
    queryFn: () => adminService.getPlayerSubRoles({ workspace_id: workspaceId! }),
    enabled: Boolean(workspaceId),
  });

  const subtypeOptions = useMemo(() => {
    const options: Record<BalancerRoleCode, Array<{ value: string; label: string }>> = {
      tank: [],
      dps: [],
      support: [],
    };

    if (subRoles) {
      for (const sr of subRoles) {
        const roleKey = sr.role === "damage" ? "dps" : (sr.role as BalancerRoleCode);
        if (options[roleKey]) {
          options[roleKey].push({
            value: sr.slug,
            label: sr.label,
          });
        }
      }
    } else {
      // Fallback defaults
      options.dps = [
        { value: "hitscan", label: "Hitscan" },
        { value: "projectile", label: "Projectile" },
      ];
      options.support = [
        { value: "main_heal", label: "Main Heal" },
        { value: "light_heal", label: "Light Heal" },
      ];
    }
    return options;
  }, [subRoles]);

  const [roleEntries, setRoleEntries] = useState<BalancerPlayerRoleEntry[]>(normalizeRoleEntries(player.role_entries_json));
  const [isInPool, setIsInPool] = useState(player.is_in_pool);
  const [notes, setNotes] = useState(player.admin_notes ?? "");
  const [showNotes, setShowNotes] = useState(Boolean(player.admin_notes));
  const [prevPlayer, setPrevPlayer] = useState(player);

  if (player !== prevPlayer) {
    setPrevPlayer(player);
    setRoleEntries(normalizeRoleEntries(player.role_entries_json));
    setIsInPool(player.is_in_pool);
    setNotes(player.admin_notes ?? "");
    setShowNotes(Boolean(player.admin_notes));
  }

  const isDirty = useMemo(() => {
    const originalEntries = normalizeRoleEntries(player.role_entries_json);

    if (isInPool !== player.is_in_pool) {
      return true;
    }

    if (notes !== (player.admin_notes ?? "")) {
      return true;
    }

    if (roleEntries.length !== originalEntries.length) {
      return true;
    }

    return roleEntries.some((entry, index) => {
      const originalEntry = originalEntries[index];

      if (!originalEntry) {
        return true;
      }

      return (
        entry.role !== originalEntry.role ||
        entry.subtype !== originalEntry.subtype ||
        entry.division_number !== originalEntry.division_number
      );
    });
  }, [isInPool, notes, player, roleEntries]);

  const addRole = () => {
    const availableRole = ROLE_OPTIONS.find((option) => !roleEntries.some((entry) => entry.role === option.value));
    if (!availableRole) {
      return;
    }

    setRoleEntries((current) => [
      ...current,
        {
          role: availableRole.value,
          subtype: null,
          priority: current.length + 1,
          division_number: null,
          rank_value: null,
          is_active: true,
        },
      ]);
  };

  const updateEntry = (index: number, nextEntry: BalancerPlayerRoleEntry) => {
    setRoleEntries((current) =>
      normalizeRoleEntries(current.map((entry, currentIndex) => (currentIndex === index ? nextEntry : entry))),
    );
  };

  const moveEntry = (index: number, direction: -1 | 1) => {
    setRoleEntries((current) => {
      const nextIndex = index + direction;
      if (nextIndex < 0 || nextIndex >= current.length) {
        return current;
      }

      const reordered = [...current];
      const [entry] = reordered.splice(index, 1);
      reordered.splice(nextIndex, 0, entry);
      return normalizeRoleEntries(reordered);
    });
  };

  const removeEntry = (index: number) => {
    setRoleEntries((current) => normalizeRoleEntries(current.filter((_, currentIndex) => currentIndex !== index)));
  };

  return (
    <Card className="border-border/60 bg-background/80">
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 pb-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="truncate text-base">{player.battle_tag}</CardTitle>
            {player.is_flex ? <Badge>Flex</Badge> : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 sm:gap-3">
          <div className="flex items-center gap-2">
            <Switch id={`pool-switch-${player.id}`} checked={isInPool} onCheckedChange={setIsInPool} />
            <Label htmlFor={`pool-switch-${player.id}`} className="cursor-pointer text-sm font-normal">
              In pool
            </Label>
          </div>
          {onRemove ? (
            <Button variant="ghost" size="icon" onClick={() => onRemove(player.id)}>
              <Trash2 className="h-4 w-4" />
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-3">
          {roleEntries.length > 0 ? (
            <div className="hidden grid-cols-[minmax(0,1fr)_110px_72px_72px_96px] gap-2 px-1 text-xs text-muted-foreground md:grid">
              <span>Role</span>
              <span>Subtype</span>
              <span>Div</span>
              <span>SR</span>
              <span aria-hidden="true" />
            </div>
          ) : null}
          {roleEntries.map((entry, index) => (
            <div
              key={`${player.id}-${entry.role}-${index}`}
              className="grid gap-2 rounded-xl border p-3 md:grid-cols-[minmax(0,1fr)_110px_72px_72px_96px] md:items-center"
            >
              <div className="space-y-1 md:space-y-0">
                <span className="text-xs text-muted-foreground md:hidden">Role</span>
                <Select value={entry.role} onValueChange={(value) => updateEntry(index, { ...entry, role: value as BalancerRoleCode, subtype: null })}>
                  <SelectTrigger className="h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLE_OPTIONS.filter(
                      (option) => option.value === entry.role || !roleEntries.some((candidate, candidateIndex) => candidate.role === option.value && candidateIndex !== index),
                    ).map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {(() => {
                const roleSubtypeOptions = subtypeOptions[entry.role] || [];
                if (roleSubtypeOptions.length > 0) {
                  return (
                    <div className="space-y-1 md:space-y-0">
                      <span className="text-xs text-muted-foreground md:hidden">Subtype</span>
                      <Select
                        value={entry.subtype ?? "none"}
                        onValueChange={(value) => updateEntry(index, { ...entry, subtype: value === "none" ? null : (value as BalancerRoleSubtype) })}
                      >
                        <SelectTrigger className="h-9">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">—</SelectItem>
                          {roleSubtypeOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  );
                }
                return <div className="hidden md:block" aria-hidden="true" />;
              })()}

              <div className="space-y-1 md:space-y-0">
                <span className="text-xs text-muted-foreground md:hidden">Division</span>
                <Input
                  type="number"
                  min={1}
                  max={20}
                  className="h-9"
                  disabled={!entry.is_active}
                  value={entry.division_number ?? ""}
                  onChange={(event) => {
                    const divisionNumber = event.target.value ? Number(event.target.value) : null;
                    updateEntry(index, {
                      ...entry,
                      division_number: divisionNumber,
                      rank_value: resolveRankFromDivision(divisionNumber),
                    });
                  }}
                />
              </div>

              <div className="space-y-1 md:space-y-0">
                <span className="text-xs text-muted-foreground md:hidden">Rank</span>
                <div className="flex h-9 items-center rounded-md border px-3 text-sm text-muted-foreground">
                  {entry.is_active ? (entry.rank_value ?? "—") : "Off"}
                </div>
              </div>

              <div className="flex items-center gap-1 pt-1 md:justify-end md:pt-0">
                <Button
                  variant={entry.is_active ? "secondary" : "outline"}
                  size="sm"
                  className="h-8"
                  onClick={() =>
                    updateEntry(index, {
                      ...entry,
                      is_active: !entry.is_active,
                    })
                  }
                >
                  {entry.is_active ? "On" : "Off"}
                </Button>
                <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => moveEntry(index, -1)} disabled={index === 0}>
                  <ArrowUp className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => moveEntry(index, 1)}
                  disabled={index === roleEntries.length - 1}
                >
                  <ArrowDown className="h-3.5 w-3.5" />
                </Button>
                <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => removeEntry(index)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          ))}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="secondary" onClick={addRole} disabled={roleEntries.length >= ROLE_OPTIONS.length}>
            <Plus className="mr-2 h-4 w-4" />
            Add role
          </Button>
          <p className="flex items-center text-xs text-muted-foreground">Use On/Off to disable a role without removing it.</p>
        </div>

        {showNotes ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <NotebookPen className="h-4 w-4" />
              <span>Admin notes</span>
            </div>
            <Textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              className="min-h-16"
              placeholder="Admin notes..."
            />
          </div>
        ) : (
          <Button
            type="button"
            variant="link"
            size="sm"
            className="h-auto w-fit p-0 text-xs text-muted-foreground"
            onClick={() => setShowNotes(true)}
          >
            <NotebookPen className="mr-1 h-3.5 w-3.5" />
            Add note
          </Button>
        )}

        <Button
          type="button"
          onClick={() => onSave(player.id, { role_entries_json: normalizeRoleEntries(roleEntries), is_in_pool: isInPool, admin_notes: notes || null })}
          disabled={!isDirty || saving}
        >
          <Save className="mr-2 h-4 w-4" />
          Save player
        </Button>
      </CardContent>
    </Card>
  );
}
