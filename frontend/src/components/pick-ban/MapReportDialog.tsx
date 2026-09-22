"use client";

import { useState } from "react";
import { Loader2, Lock } from "lucide-react";
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
import { notify } from "@/lib/notify";
import pickBanService from "@/services/pickBan.service";
import type { PickBanGame } from "@/types/tournament.types";

import { acceptedScore } from "./pick-ban-model";

interface MapReportDialogProps {
  encounterId: number;
  /** The position being reported — the claim is filed against IT, not the map. */
  game: PickBanGame;
  mapName: string;
  /** The captain's own team side — decides which score field is "yours". */
  side: "home" | "away";
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Catalog for naming the map of a freeplay position. Only read while the
   * game is still `planned`; a vetoed position already carries its map.
   */
  mapChoices?: ReadonlyArray<{ id: number; name: string }>;
  /** Query keys to invalidate once the report lands (encounter + pick-ban state). */
  invalidateKeys: unknown[][];
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
  side,
  open,
  onOpenChange,
  mapChoices,
  invalidateKeys,
}: Readonly<MapReportDialogProps>) {
  const t = useTranslations("pickBan.room.mapReport");
  const tRoom = useTranslations("pickBan.room");
  const queryClient = useQueryClient();
  const filed = game.reports.find((report) => report.side === side) ?? null;
  const accepted = acceptedScore(game);
  const locked = game.state === "confirmed";
  // The dialog is mounted on demand, so seeding state is enough to reopen an
  // already-filed report as an edit rather than a blank form.
  const [yourScore, setYourScore] = useState(
    filed == null ? 0 : side === "home" ? filed.home_score : filed.away_score,
  );
  const [opponentScore, setOpponentScore] = useState(
    filed == null ? 0 : side === "home" ? filed.away_score : filed.home_score,
  );
  const [mapId, setMapId] = useState<number | null>(game.map_id);
  const needsMap = game.map_id == null;

  const mutation = useMutation({
    mutationFn: async () => {
      if (game.map_id == null) {
        if (mapId == null) throw new Error("no map");
        await pickBanService.selectGameMap(encounterId, game.id, { map_id: mapId });
      }
      return pickBanService.reportGame(encounterId, game.id, {
        home_score: side === "home" ? yourScore : opponentScore,
        away_score: side === "home" ? opponentScore : yourScore,
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
    onError: (error) => notify.apiError(error, { title: t("failed") }),
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
            {t("lockedHint", { home: accepted?.home ?? 0, away: accepted?.away ?? 0 })}
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
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
              ) : null}
              {mutation.isPending ? t("sending") : t("submit")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
