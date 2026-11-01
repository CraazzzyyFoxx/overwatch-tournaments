"use client";

import { useState } from "react";
import { Lock } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import pickBanService from "@/services/pickBan.service";
import type { PickBanGame } from "@/types/tournament.types";
import { Spinner } from "@/components/ui/spinner";

import { MatchImport } from "./MatchImport";
import { acceptedScore, type PickBanSeat } from "./pick-ban-model";

/** Server codes of a game claim a captain can act on (`map_report.submit_game_claim`, `games.select_map`). */
const CLAIM_ERROR_CODES = [
  "stale_state",
  "result_locked",
  "map_locked",
  "side_pick_pending",
  "side_pick_required"
] as const;
type ClaimErrorCode = (typeof CLAIM_ERROR_CODES)[number];

function isClaimErrorCode(code: string | undefined): code is ClaimErrorCode {
  return CLAIM_ERROR_CODES.some((known) => known === code);
}

interface MapReportDialogProps {
  encounterId: number;
  /** The position being reported — the claim is filed against IT, not the map. */
  game: PickBanGame;
  mapName: string;
  /** The duel's two participations in slot order. */
  seats: PickBanSeat[];
  /** The captain's own participation — decides which score field is "yours". */
  viewerTeamId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Catalog for naming the map of a freeplay position. Only read while the
   * game is still `planned`; a vetoed position already carries its map.
   */
  mapChoices?: ReadonlyArray<{ id: number; name: string }>;
  /** Query keys to invalidate once the report lands (encounter + pick-ban state). */
  invalidateKeys: unknown[][];
  /** Offer filing the game's match by its id: a tournament game of a discipline with a match fetcher. */
  matchImport?: boolean;
}

/**
 * Per-game result confirmation: each captain reports their own team's score for
 * ONE position of the series independently. Agreement confirms the game
 * immediately (advancing any pick-ban round waiting on it); disagreement leaves
 * both claims standing as a dispute for an admin (backend: `games.report`).
 *
 * A `planned` game has no map yet — the freeplay case, where the captains name
 * what they played before they can score it, so the map picker is the first
 * field here and `select_map` lands before the claim.
 *
 * A `confirmed` game is read-only: the accepted score is authoritative and only
 * the admin correction command may change it (409 `result_locked` otherwise).
 */
export function MapReportDialog({
  encounterId,
  game,
  mapName,
  seats,
  viewerTeamId,
  open,
  onOpenChange,
  mapChoices,
  invalidateKeys,
  matchImport = false,
}: Readonly<MapReportDialogProps>) {
  const t = useTranslations("pickBan.room.mapReport");
  const tRoom = useTranslations("pickBan.room");
  const queryClient = useQueryClient();
  const opponent = seats.find((seat) => seat.id !== viewerTeamId) ?? null;
  const filed = game.claims.find((claim) => claim.claimant_team_id === viewerTeamId) ?? null;
  const accepted = acceptedScore(game, seats);
  const locked = game.state === "confirmed";
  const scoreOf = (teamId: number | undefined) =>
    filed?.results.find((line) => line.encounter_team_id === teamId)?.score ?? 0;
  // The dialog is mounted on demand, so seeding state is enough to reopen an
  // already-filed report as an edit rather than a blank form.
  const [yourScore, setYourScore] = useState(scoreOf(viewerTeamId));
  const [opponentScore, setOpponentScore] = useState(scoreOf(opponent?.id));
  const [mapId, setMapId] = useState<number | null>(game.map_id);
  const needsMap = game.map_id == null;

  const mutation = useMutation({
    mutationFn: async () => {
      if (game.map_id == null) {
        if (mapId == null) throw new Error("no map");
        await pickBanService.selectGameMap(encounterId, game.id, { map_id: mapId });
      }
      return pickBanService.reportGame(encounterId, game.id, {
        basis_version: game.result_version,
        results: [
          { encounter_team_id: viewerTeamId, score: yourScore },
          ...(opponent ? [{ encounter_team_id: opponent.id, score: opponentScore }] : []),
        ],
      });
    },
    onSuccess: (result) => {
      if (result.disputed) {
        notify.error(t("disputed"), { description: t("disputedHint") });
      } else if (!result.resolved) {
        notify.info(t("waitingOpponent"));
      } else {
        notify.success(t("resolved"));
      }
      onOpenChange(false);
    },
    onError: (error) => {
      // A server code the captain can act on gets its own sentence; anything
      // else falls back to the generic failure with the server's own text.
      const code =
        error instanceof ApiError
          ? error.details.map((detail) => detail.code).find(isClaimErrorCode)
          : undefined;
      if (code != null) {
        notify.error(t("failed"), { description: t(`errors.${code}`) });
        return;
      }
      notify.apiError(error, { title: t("failed") });
    },
    onSettled: () => {
      for (const key of invalidateKeys) void queryClient.invalidateQueries({ queryKey: key });
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{locked ? t("lockedTitle") : t("title")}</DialogTitle>
          <DialogDescription>
            {needsMap ? tRoom("mapResult.pickMap") : mapName}
          </DialogDescription>
        </DialogHeader>

        {locked ? (
          <p className="flex items-start gap-2 text-sm text-[color:var(--aqt-fg-muted)]">
            <Lock className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            {t("lockedHint", { first: accepted?.one ?? 0, second: accepted?.two ?? 0 })}
          </p>
        ) : (
          <>
            {needsMap && mapChoices != null ? (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="map-report-map">{t("mapLabel")}</Label>
                <Select
                  value={mapId != null ? String(mapId) : ""}
                  onValueChange={(value) => setMapId(Number(value))}
                >
                  <SelectTrigger id="map-report-map" aria-label={t("mapLabel")}>
                    <SelectValue placeholder={tRoom("mapResult.pickMap")} />
                  </SelectTrigger>
                  <SelectContent>
                    {mapChoices.map((map) => (
                      <SelectItem key={map.id} value={String(map.id)}>
                        {map.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="map-report-your-score">{t("yourScore")}</Label>
                <NumberInput
                  id="map-report-your-score"
                  min={0}
                  integer
                  value={yourScore}
                  onValueChange={(v) => setYourScore(v ?? 0)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="map-report-opponent-score">{t("opponentScore")}</Label>
                <NumberInput
                  id="map-report-opponent-score"
                  min={0}
                  integer
                  value={opponentScore}
                  onValueChange={(v) => setOpponentScore(v ?? 0)}
                />
              </div>
            </div>
          </>
        )}

        {matchImport ? (
          <div className="border-t border-[color:var(--aqt-border)] pt-4">
            <MatchImport scope={{ encounterId, games: [game] }} />
          </div>
        ) : null}

        <DialogFooter>
          {locked ? (
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t("close")}
            </Button>
          ) : (
            <Button
              disabled={mutation.isPending || (needsMap && mapId == null)}
              onClick={() => mutation.mutate()}
            >
              {mutation.isPending ? (
                <Spinner className="mr-2" />
              ) : null}
              {mutation.isPending ? t("sending") : t("submit")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
