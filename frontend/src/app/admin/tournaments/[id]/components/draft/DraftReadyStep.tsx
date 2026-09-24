"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowUpRight, CheckCircle2, Play, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { StatusPill } from "@/components/kit/StatusPill";
import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { TONE_CLASS } from "@/components/kit/tone";
import { cn } from "@/lib/utils";
import type { DraftFeasibility, DraftSession } from "@/types/draft.types";

interface DraftReadyStepProps {
  tournamentId: number;
  session: DraftSession;
  feasibility: DraftFeasibility | null;
  pending: boolean;
  onStart: () => void;
  onReseed: () => void;
}

export function DraftReadyStep({
  tournamentId,
  session,
  feasibility,
  pending,
  onStart,
  onReseed
}: Readonly<DraftReadyStepProps>) {
  const t = useTranslations("draftAdmin");
  const ready = feasibility?.is_feasible === true;
  // Going live is the one setup transition captains see instantly and that the
  // wizard cannot walk back, so it is confirmed instead of fired on one click.
  const [startDialogOpen, setStartDialogOpen] = useState(false);

  return (
    <div className="space-y-6">
      <div className={cn("rounded-2xl border p-6", TONE_CLASS[ready ? "success" : "danger"])}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex gap-3">
            {ready ? (
              <CheckCircle2 className="mt-0.5 h-6 w-6 shrink-0" aria-hidden />
            ) : (
              <ShieldAlert className="mt-0.5 h-6 w-6 shrink-0" aria-hidden />
            )}
            <div>
              <h3 className="text-lg font-semibold">
                {ready ? t("readyToStart") : t("notReadyToStart")}
              </h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {ready ? t("readyToStartHint") : t("notReadyToStartHint")}
              </p>
            </div>
          </div>
          <StatusPill tone={ready ? "success" : "danger"}>
            {ready ? t("ready") : t("blocked")}
          </StatusPill>
        </div>
      </div>

      <StatTileGrid className="sm:grid-cols-3 md:grid-cols-3 xl:grid-cols-3">
        <StatTile label={t("teamSize")} value={session.roster_shape.team_size} />
        <StatTile label={t("rounds")} value={session.rounds} />
        <StatTile label={t("pickTime")} value={`${session.pick_time_seconds}s`} />
      </StatTileGrid>

      <div className="flex flex-col gap-3 sm:flex-row">
        <Button size="lg" disabled={pending || !ready} onClick={() => setStartDialogOpen(true)}>
          {pending ? (
            <Spinner className="mr-2" />
          ) : (
            <Play className="mr-2 h-4 w-4" aria-hidden />
          )}
          {t("startDraft")}
        </Button>
        <Button asChild size="lg" variant="outline">
          <Link href={`/draft/${tournamentId}`} target="_blank" rel="noreferrer">
            {t("openLiveBoard")}
            <ArrowUpRight className="ml-2 h-4 w-4" aria-hidden />
          </Link>
        </Button>
        <Button size="lg" variant="ghost" disabled={pending} onClick={onReseed}>
          {t("editSetup")}
        </Button>
      </div>

      <ConfirmDialog
        open={startDialogOpen}
        onOpenChange={setStartDialogOpen}
        intent={{
          title: t("startConfirmTitle"),
          description: t("startConfirmDescription"),
          confirmLabel: t("startDraft"),
          tone: "warning"
        }}
        pending={pending}
        onConfirm={() => {
          setStartDialogOpen(false);
          onStart();
        }}
      />
    </div>
  );
}
