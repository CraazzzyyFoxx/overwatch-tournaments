"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { notify } from "@/lib/notify";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import draftService from "@/services/draft.service";
import type {
  DraftBoard,
  DraftFeasibility,
  DraftPlayer,
  DraftRole,
  DraftRoleEditRequest,
  DraftRoleEditResponse
} from "@/types/draft.types";

import { availableRolesForPlayer, canCommitRoleEdit, roleEditImpact } from "./admin-control-model";

interface ResolveRoleConflictDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tournamentId: number;
  board: DraftBoard;
  feasibility: DraftFeasibility | null;
}

function playerName(player: DraftPlayer): string {
  return player.battle_tag ?? `#${player.id}`;
}

export function ResolveRoleConflictDialog({
  open,
  onOpenChange,
  tournamentId,
  board,
  feasibility
}: ResolveRoleConflictDialogProps) {
  const t = useTranslations("draftAdmin.roleConflict");
  const queryClient = useQueryClient();
  const [playerId, setPlayerId] = useState<number | null>(null);
  const [role, setRole] = useState<DraftRole | null>(null);
  const [rankValue, setRankValue] = useState<number | null>(null);
  const [rankAbsent, setRankAbsent] = useState(false);
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<DraftRoleEditResponse | null>(null);
  const players = useMemo(
    () => board.players.filter((player) => player.status === "available"),
    [board.players]
  );
  const player = players.find((candidate) => candidate.id === playerId) ?? null;
  const availableRoles = player ? availableRolesForPlayer(player) : [];

  const resetPreview = () => setPreview(null);
  const request = (previewOnly: boolean): DraftRoleEditRequest | null => {
    if (!player || !role || !reason.trim()) return null;
    if (rankValue == null && !rankAbsent) return null;
    return {
      role,
      rank_value: rankValue,
      rank_absence_confirmed: rankAbsent,
      reason: reason.trim(),
      expected_version: player.version,
      preview_only: previewOnly
    };
  };

  const previewMutation = useMutation({
    mutationFn: () => {
      const body = request(true);
      if (!body || !player) throw new Error(t("completeFields"));
      return draftService.editPlayerRole(board.session.id, player.id, body);
    },
    onSuccess: setPreview,
    onError: (error) => notify.apiError(error, { title: t("previewFailed") })
  });
  const commitMutation = useMutation({
    mutationFn: () => {
      const body = request(false);
      if (!body || !player) throw new Error(t("completeFields"));
      return draftService.editPlayerRole(board.session.id, player.id, body);
    },
    onSuccess: async () => {
      notify.success(t("committed"));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.draftBoard(tournamentId) }),
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.draftFeasibility(board.session.id)
        })
      ]);
      onOpenChange(false);
    },
    onError: (error) => notify.apiError(error, { title: t("commitFailed") })
  });

  const canCommit = canCommitRoleEdit({
    player,
    role,
    rankValue,
    rankAbsent,
    reason,
    preview
  });

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setPlayerId(null);
      setRole(null);
      setRankValue(null);
      setRankAbsent(false);
      setReason("");
      setPreview(null);
    }
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        {feasibility && feasibility.unmatched_slots.length > 0 && (
          <div className="rounded-xl border border-[color:var(--aqt-live)]/30 bg-[color:var(--aqt-live)]/10 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <AlertTriangle className="h-4 w-4" />
              {t("unmatchedSlots")}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {feasibility.unmatched_slots.map((slot) => {
                const team = board.teams.find((candidate) => candidate.id === slot.team_id);
                return (
                  <Badge key={`${slot.team_id}-${slot.role}-${slot.ordinal}`} variant="outline">
                    {team?.name ?? `#${slot.team_id}`} · {t(`roles.${slot.role}`)} #{slot.ordinal}
                  </Badge>
                );
              })}
            </div>
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="role-conflict-player">{t("player")}</Label>
            <Select
              value={playerId?.toString() ?? ""}
              onValueChange={(value) => {
                setPlayerId(Number(value));
                setRole(null);
                resetPreview();
              }}
            >
              <SelectTrigger id="role-conflict-player">
                <SelectValue placeholder={t("selectPlayer")} />
              </SelectTrigger>
              <SelectContent>
                {players.map((candidate) => (
                  <SelectItem key={candidate.id} value={candidate.id.toString()}>
                    {playerName(candidate)} · {candidate.primary_role}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {player && (
              <p className="text-xs text-[color:var(--aqt-fg-muted)]">
                {t("declaredRoles")}: {[player.primary_role, ...(player.secondary_roles_json ?? [])].join(", ")}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="role-conflict-role">{t("newRole")}</Label>
            <Select
              value={role ?? ""}
              disabled={!player}
              onValueChange={(value) => {
                setRole(value as DraftRole);
                resetPreview();
              }}
            >
              <SelectTrigger id="role-conflict-role">
                <SelectValue placeholder={t("selectRole")} />
              </SelectTrigger>
              <SelectContent>
                {availableRoles.map((entry) => (
                  <SelectItem key={entry} value={entry}>{t(`roles.${entry}`)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="role-conflict-rank">{t("rank")}</Label>
            <NumberInput
              id="role-conflict-rank"
              integer
              min={0}
              disabled={rankAbsent}
              value={rankValue}
              onValueChange={(next) => {
                setRankValue(next);
                resetPreview();
              }}
            />
            <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm">
              <Checkbox
                checked={rankAbsent}
                onCheckedChange={(checked) => {
                  setRankAbsent(checked === true);
                  if (checked) setRankValue(null);
                  resetPreview();
                }}
              />
              {t("rankAbsent")}
            </label>
          </div>

          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="role-conflict-reason">{t("reason")}</Label>
            <Textarea
              id="role-conflict-reason"
              value={reason}
              onChange={(event) => {
                setReason(event.target.value);
                resetPreview();
              }}
              placeholder={t("reasonPlaceholder")}
            />
            <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("reasonPrivate")}</p>
          </div>
        </div>

        {preview && (
          <div className="rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card-2)] p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 font-medium">
                <ShieldCheck className="h-4 w-4 text-[color:var(--aqt-teal)]" />
                {t(`impact.${roleEditImpact(preview)}`)}
              </div>
              <Badge variant="outline">{t("previewOnly")}</Badge>
            </div>
            <div className="mt-4 grid grid-cols-[1fr_auto_1fr] items-center gap-3 text-center">
              <ImpactValue label={t("before")} value={`${preview.before.matched_slots}/${preview.before.total_open_slots}`} />
              <ArrowRight className="h-4 w-4 text-[color:var(--aqt-fg-faint)]" />
              <ImpactValue label={t("after")} value={`${preview.after.matched_slots}/${preview.after.total_open_slots}`} good={preview.after.is_feasible} />
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" disabled={previewMutation.isPending} onClick={() => previewMutation.mutate()}>
            {t("preview")}
          </Button>
          <Button disabled={!canCommit || commitMutation.isPending} onClick={() => commitMutation.mutate()}>
            <CheckCircle2 className="mr-2 h-4 w-4" />
            {t("commit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ImpactValue({ label, value, good = false }: { label: string; value: string; good?: boolean }) {
  return (
    <div>
      <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">{label}</p>
      <p className={good ? "mt-1 text-xl font-semibold text-[color:var(--aqt-support)]" : "mt-1 text-xl font-semibold"}>{value}</p>
    </div>
  );
}

