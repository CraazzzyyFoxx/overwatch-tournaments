"use client";

import { ShieldAlert } from "lucide-react";
import { redirect, useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { DraftBoard } from "@/components/draft/DraftBoard";
import { tournamentHref } from "@/lib/tournament/url";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { Button } from "@/components/ui/button";

import styles from "@/components/draft/DraftRoom.module.css";
import { DraftRoomSkeleton } from "@/components/draft/DraftRoomSkeleton";
import { shouldShowInitialDraftSkeleton } from "@/components/draft/draft-loading-state";

export default function PublicDraftRoomPage() {
  const t = useTranslations("draftRedesign");
  const params = useParams<{ id: string }>();
  // Legacy numeric ref: this route is addressed by tournament id directly
  // (not by slug), and the backend resolves a numeric ref like any other.
  const tournamentQuery = useTournamentQuery(params.id);
  const tournament = tournamentQuery.data;

  if (tournament && tournament.team_formation !== "draft") {
    redirect(tournamentHref(tournament));
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
}: Readonly<{
  icon: ReactNode;
  title: string;
  hint: string;
  action?: ReactNode;
}>) {
  return (
    <section className="flex min-h-[60svh] flex-col items-center justify-center gap-3 text-center">
      {icon}
      <h1 className="font-onest text-2xl font-semibold">{title}</h1>
      <p className="max-w-lg text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">{hint}</p>
      {action ? <div className="mt-2">{action}</div> : null}
    </section>
  );
}
