"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { EntityFormDialog } from "@craazzzyyfoxx/admin-kit/kit/EntityFormDialog";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { NumberInput } from "@/components/ui/number-input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@craazzzyyfoxx/admin-kit/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { notify } from "@/lib/notify";
import { ratedDimension, registrationRoles, type RoleOntology } from "@/lib/roster/ontology";
import { roleOf } from "@/lib/roster/role-ref";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
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
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";

interface ResolveRoleConflictDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tournamentId: number;
  formationNodeId: number;
  board: DraftBoard;
  feasibility: DraftFeasibility | null;
  /** The owner game's role dictionary: the roles an organizer may add, their names and the rated dimension. */
  ontology: RoleOntology | null;
}

function playerName(player: DraftPlayer): string {
  return player.identity?.handle ?? `#${player.id}`;
}

export function ResolveRoleConflictDialog({
  open,
  onOpenChange,
  tournamentId,
  formationNodeId,
  board,
  feasibility,
  ontology
}: Readonly<ResolveRoleConflictDialogProps>) {
  const t = useTranslations("draftAdmin.roleConflict");
  const slotLabel = useSlotLabel(ontology);
  const tAdmin = useTranslations("adminTournament.draft");
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
  const availableRoles = player
    ? availableRolesForPlayer(player, registrationRoles(ontology).map((entry) => entry.code))
    : [];

  const resetPreview = () => setPreview(null);
  const request = (previewOnly: boolean): DraftRoleEditRequest | null => {
    // A rank is not optional here: a role with no rank is not playable, so the
    // edit would add a role the draft can never offer. The server enforces
    // `gt=0`; refusing to build the body is how the organizer sees it first.
    const dimension = ontology ? ratedDimension(ontology)?.code : null;
    if (!player || !role || !dimension || !reason.trim() || rankValue == null || rankValue <= 0) return null;
    return {
      role: { dimension, role },
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
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.draftBoard(tournamentId, formationNodeId)
        }),
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.draftFeasibility(board.session.id)
        })
      ]);
      onOpenChange(false);
    },
    onError: (error) => notify.apiError(error, { title: t("commitFailed") })
  });

  const canCommit = canCommitRoleEdit({ player, role, rankValue, reason, preview });
  // One "Tank ×2 · Support ×1" line, not a chip per open team slot.
  const unmatchedSummary = Object.entries(
    (feasibility?.unmatched_slots ?? []).reduce<Record<string, number>>((counts, slot) => {
      counts[slot.slot_code] = (counts[slot.slot_code] ?? 0) + 1;
      return counts;
    }, {})
  )
    .map(([code, count]) => t("slotCount", { role: slotLabel(code), count }))
    .join(" · ");

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
    <EntityFormDialog
      open={open}
      onOpenChange={handleOpenChange}
      title={t("title")}
      description={t("description")}
      onSubmit={() => {
        if (!canCommit) {
          notify.warning(t("completeFields"));
          return;
        }
        commitMutation.mutate();
      }}
      submitLabel={t("commit")}
      isSubmitting={commitMutation.isPending}
      footerStart={
        <Button
          type="button"
          variant="outline"
          disabled={previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
        >
          {t("preview")}
        </Button>
      }
      contentClassName="max-w-3xl"
    >
      {unmatchedSummary && (
        <section>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-danger">
            <AlertTriangle className="h-4 w-4" aria-hidden />
            {t("unmatchedSlots")}
          </h3>
          <p className="mt-1 text-sm tabular-nums">{unmatchedSummary}</p>
        </section>
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
                  {playerName(candidate)} · {candidate.primary_role ? slotLabel(roleOf(candidate.primary_role)) : t("noRole")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {player && (
            <p className="text-xs text-muted-foreground">
              {tAdmin("rolesSummary", {
                label: t("declaredRoles"),
                roles: (player.primary_role
                  ? [player.primary_role, ...player.secondary_roles]
                  : player.secondary_roles
                ).map((entry) => slotLabel(roleOf(entry))).join(", ") || t("noRole")
              })}
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
              aria-label={player ? tAdmin("newRoleFor", { role: t("newRole"), player: playerName(player) }) : t("newRole")}
            >
              <SelectValue placeholder={t("selectRole")} />
            </SelectTrigger>
            <SelectContent>
              {availableRoles.map((entry) => (
                <SelectItem key={entry} value={entry}>{slotLabel(entry)}</SelectItem>
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
          <p className="text-xs text-muted-foreground">{t("rankRequired")}</p>
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
          <p className="text-xs text-muted-foreground">{t("reasonPrivate")}</p>
        </div>
      </div>

      {preview && (
        <section role="status" className="border-t border-border pt-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <ShieldCheck className="h-4 w-4 text-primary" aria-hidden />
            {t(`impact.${roleEditImpact(preview)}`)}
          </h3>
          <div className="mt-4 grid grid-cols-[1fr_auto_1fr] items-center gap-3 text-center">
            <ImpactValue
              label={t("before")}
              value={`${preview.before.matched_slots}/${preview.before.total_open_slots}`}
            />
            <ArrowRight className="h-4 w-4 text-muted-foreground" aria-hidden />
            <ImpactValue
              label={t("after")}
              value={`${preview.after.matched_slots}/${preview.after.total_open_slots}`}
              good={preview.after.is_feasible}
            />
          </div>
        </section>
      )}
    </EntityFormDialog>
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
      <p className={eyebrowClass("muted")}>
        {label}
      </p>
      <p
        className={cn(
          "mt-1 text-xl font-semibold tabular-nums",
          good && "text-success"
        )}
      >
        {value}
      </p>
    </div>
  );
}
