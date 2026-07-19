"use client";

import { ArrowLeft, Radio, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { redirect, useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { DraftBoard } from "@/app/(site)/tournaments/[id]/draft/_components/DraftBoard";
import { useTournamentQuery } from "@/app/(site)/tournaments/[id]/_hooks/useTournamentClientData";
import { Button } from "@/components/ui/button";

import styles from "./DraftRoom.module.css";
import { DraftRoomSkeleton } from "./DraftRoomSkeleton";
import { shouldShowInitialDraftSkeleton } from "./draft-loading-state";

export default function PublicDraftRoomPage() {
  const t = useTranslations("draftRedesign");
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const tournamentQuery = useTournamentQuery(tournamentId);
  const tournament = tournamentQuery.data;

  if (tournament && tournament.team_formation !== "draft") {
    redirect(`/tournaments/${tournamentId}`);
  }

  if (shouldShowInitialDraftSkeleton(tournamentQuery)) {
    return <DraftRoomSkeleton />;
  }

  const initialLoadError = tournamentQuery.isError && !tournament;

  return (
    <div className={`${styles.room} site-theme`}>
      <main
        className={`${styles.stage} mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6 sm:py-7 xl:px-10`}
      >
        {initialLoadError || !tournament ? (
          <DraftRoomState
            icon={<ShieldAlert className="h-6 w-6 text-[color:var(--aqt-amber)]" />}
            title={t("loadErrorTitle")}
            hint={t("loadErrorHint")}
            action={<Button onClick={() => tournamentQuery.refetch()}>{t("retry")}</Button>}
          />
        ) : (
          <DraftBoard tournament={tournament} />
        )}
      </main>
    </div>
  );
}

function DraftRoomState({
  icon,
  title,
  hint,
  action
}: {
  icon: ReactNode;
  title: string;
  hint: string;
  action?: ReactNode;
}) {
  return (
    <section className="flex min-h-[60svh] flex-col items-center justify-center gap-3 text-center">
      {icon}
      <h1 className="font-onest text-2xl font-semibold">{title}</h1>
      <p className="max-w-lg text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">{hint}</p>
      {action ? <div className="mt-2">{action}</div> : null}
    </section>
  );
}
