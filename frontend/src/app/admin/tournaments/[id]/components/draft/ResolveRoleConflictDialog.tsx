"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
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
import { cn } from "@/lib/utils";
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
import { EYEBROW_CLASS } from "@/components/kit/tone";

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
}: Readonly<ResolveRoleConflictDialogProps>) {
  const t = useTranslations("draftAdmin.roleConflict");
  const queryClient = useQueryClient();
  const [playerId, setPlayerId] = useState<number | null>(null);
  const [role, setRole] = useState<DraftRole | null>(null);
  const [rankValue, setRankValue] = useState<number | null>(null);
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
    // A rank is not optional here: a role with no rank is not playable, so the
    // edit would add a role the draft can never offer. The server enforces
    // `gt=0`; refusing to build the body is how the organizer sees it first.
    if (!player || !role || !reason.trim() || rankValue == null || rankValue <= 0) return null;
    return {
      role,
      rank_value: rankValue,
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

  const canCommit = canCommitRoleEdit({ player, role, rankValue, reason, preview });

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setPlayerId(null);
      setRole(null);
      setRankValue(null);
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
              <AlertTriangle className="h-4 w-4" aria-hidden />
              {t("unmatchedSlots")}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {feasibility.unmatched_slots.map((slot) => {
                const team = board.teams.find((candidate) => candidate.id === slot.team_id);
                return (
                  <Badge
                    key={`${slot.team_id}-${slot.slot_code}-${slot.ordinal}`}
                    variant="outline"
                    className="tabular-nums"
                  >
                    {team?.name ?? `#${slot.team_id}`} · {t(`roles.${slot.slot_code}`)} #{slot.ordinal}
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
              <SelectTrigger id="role-conflict-player" aria-label={t("player")}>
                <SelectValue placeholder={t("selectPlayer")} />
              </SelectTrigger>
              <SelectContent>
                {players.map((candidate) => (
                  <SelectItem key={candidate.id} value={candidate.id.toString()}>
                    {playerName(candidate)} · {candidate.primary_role ?? t("noRole")}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {player && (
              <p className="text-xs text-[color:var(--aqt-fg-muted)]">
                {t("declaredRoles")}:{" "}
                {(player.primary_role
                  ? [player.primary_role, ...player.secondary_roles]
                  : player.secondary_roles
                ).join(", ") || t("noRole")}
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
              <SelectTrigger
                id="role-conflict-role"
                aria-label={player ? `${t("newRole")} · ${playerName(player)}` : t("newRole")}
              >
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
              min={1}
              value={rankValue}
              onValueChange={(next) => {
                setRankValue(next);
                resetPreview();
              }}
            />
            <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("rankRequired")}</p>
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
          <div
            role="status"
            className="rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card-2)] p-4"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 font-medium">
                <ShieldCheck className="h-4 w-4 text-[color:var(--aqt-teal)]" aria-hidden />
                {t(`impact.${roleEditImpact(preview)}`)}
              </div>
              <Badge variant="outline">{t("previewOnly")}</Badge>
            </div>
            <div className="mt-4 grid grid-cols-[1fr_auto_1fr] items-center gap-3 text-center">
              <ImpactValue
                label={t("before")}
                value={`${preview.before.matched_slots}/${preview.before.total_open_slots}`}
              />
              <ArrowRight className="h-4 w-4 text-[color:var(--aqt-fg-faint)]" aria-hidden />
              <ImpactValue
                label={t("after")}
                value={`${preview.after.matched_slots}/${preview.after.total_open_slots}`}
                good={preview.after.is_feasible}
              />
            </div>
          </div>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            disabled={previewMutation.isPending}
            onClick={() => previewMutation.mutate()}
          >
            {t("preview")}
          </Button>
          <Button
            disabled={commitMutation.isPending}
            onClick={() => {
              if (!canCommit) {
                notify.warning(t("completeFields"));
                return;
              }
              commitMutation.mutate();
            }}
          >
            <CheckCircle2 className="mr-2 h-4 w-4" aria-hidden />
            {t("commit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ImpactValue({
  label,
  value,
  good = false
}: Readonly<{
  label: string;
  value: string;
  good?: boolean;
}>) {
  return (
    <div>
      <p className={EYEBROW_CLASS}>
        {label}
      </p>
      <p
        className={cn(
          "mt-1 text-xl font-semibold tabular-nums",
          good && "text-[color:var(--aqt-support)]"
        )}
      >
        {value}
      </p>
    </div>
  );
}

