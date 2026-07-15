"use client";

import Link from "next/link";
import { ArrowUpRight, CheckCircle2, Play, RefreshCw, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
}: DraftReadyStepProps) {
  const t = useTranslations("draftAdmin");
  const ready = feasibility?.is_feasible === true;

  return (
    <div className="space-y-6">
      <div
        className={
          ready
            ? "rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-6"
            : "rounded-2xl border border-destructive/30 bg-destructive/10 p-6"
        }
      >
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex gap-3">
            {ready ? (
              <CheckCircle2 className="mt-0.5 h-6 w-6 text-emerald-600" />
            ) : (
              <ShieldAlert className="mt-0.5 h-6 w-6 text-destructive" />
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
          <Badge variant={ready ? "default" : "destructive"}>
            {ready ? t("ready") : t("blocked")}
          </Badge>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <ReadyMetric label={t("teamSize")} value={session.team_size} />
        <ReadyMetric label={t("rounds")} value={session.rounds} />
        <ReadyMetric label={t("pickTime")} value={`${session.pick_time_seconds}s`} />
      </div>

      <div className="flex flex-col gap-3 sm:flex-row">
        <Button size="lg" disabled={pending || !ready} onClick={onStart}>
          {pending ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
          {t("startDraft")}
        </Button>
        <Button asChild size="lg" variant="outline">
          <Link href={`/draft/${tournamentId}`} target="_blank">
            {t("openLiveBoard")}
            <ArrowUpRight className="ml-2 h-4 w-4" />
          </Link>
        </Button>
        <Button size="lg" variant="ghost" disabled={pending} onClick={onReseed}>
          {t("changeAndReseed")}
        </Button>
      </div>
    </div>
  );
}

function ReadyMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-border/70 bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}
