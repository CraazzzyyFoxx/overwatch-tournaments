"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { ArrowUpRight, CheckCircle2, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { FactList } from "@/components/kit/FactList";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { DraftFeasibility, DraftSession } from "@/types/draft.types";

interface DraftReadyStepProps {
  tournamentId: number;
  session: DraftSession;
  feasibility: DraftFeasibility | null;
  /** The feasibility request failed and nothing is cached to show instead. */
  feasibilityFailed: boolean;
  onRetryFeasibility: () => void;
  pending: boolean;
  onStart: () => void;
  onReseed: () => void;
}

export function DraftReadyStep({
  tournamentId,
  session,
  feasibility,
  feasibilityFailed,
  onRetryFeasibility,
  pending,
  onStart,
  onReseed
}: Readonly<DraftReadyStepProps>) {
  const t = useTranslations("draftAdmin");
  const ready = feasibility?.is_feasible === true;
  // The status block doubles as Start's visible reason while it is disabled.
  const reasonId = useId();
  // Going live is the one setup transition captains see instantly and that the
  // wizard cannot walk back, so it is confirmed instead of fired on one click.
  const [startDialogOpen, setStartDialogOpen] = useState(false);

  return (
    <div className="space-y-6">
      {feasibility == null && feasibilityFailed ? (
        <div role="alert" className="flex flex-wrap items-center gap-3">
          <p id={reasonId} className="text-sm text-danger">
            {t("loadFailed")}
          </p>
          <Button size="sm" variant="outline" onClick={onRetryFeasibility}>
            {t("retry")}
          </Button>
        </div>
      ) : feasibility == null ? (
        <p id={reasonId} role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner />
          {t("checkingFeasibility")}
        </p>
      ) : ready ? (
        <div className="flex gap-3">
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" aria-hidden />
          <div>
            <h3 className="text-lg font-semibold">{t("readyToStart")}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{t("readyToStartHint")}</p>
          </div>
        </div>
      ) : (
        <Alert id={reasonId} tone="warning">
          <ShieldAlert className="size-4" aria-hidden />
          <AlertTitle>{t("notReadyToStart")}</AlertTitle>
          <AlertDescription>{t("notReadyToStartHint")}</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-col gap-3 sm:flex-row">
        <Button
          size="lg"
          disabled={pending || !ready}
          aria-describedby={ready ? undefined : reasonId}
          onClick={() => setStartDialogOpen(true)}
        >
          {pending && <Spinner className="mr-2" />}
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

      <FactList
        size="sm"
        facts={[
          { label: t("teamSize"), value: session.roster_shape.team_size },
          { label: t("rounds"), value: session.rounds },
          { label: t("pickTime"), value: `${session.pick_time_seconds}s` }
        ]}
      />

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
