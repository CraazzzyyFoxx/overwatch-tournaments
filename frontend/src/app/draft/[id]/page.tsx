"use client";

import { Loader2, ShieldAlert } from "lucide-react";
import { redirect, useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { DraftBoard } from "@/app/(site)/tournaments/[id]/draft/_components/DraftBoard";
import { useTournamentQuery } from "@/app/(site)/tournaments/[id]/_hooks/useTournamentClientData";
import { Button } from "@/components/ui/button";

import styles from "./DraftRoom.module.css";

export default function PublicDraftRoomPage() {
  const t = useTranslations("draftRedesign");
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const tournamentQuery = useTournamentQuery(tournamentId);
  const tournament = tournamentQuery.data;

  if (tournament && tournament.team_formation !== "draft") {
    redirect(`/tournaments/${tournamentId}`);
  }

  return (
    <div className={`${styles.room} site-theme`}>
      <main className={`${styles.stage} mx-auto w-full max-w-[min(2000px,96vw)] px-4 py-5 sm:px-6 sm:py-7 xl:px-10`}>
        {tournamentQuery.isLoading ? (
          <DraftRoomState
            icon={<Loader2 className="h-6 w-6 animate-spin text-[color:var(--aqt-teal)] motion-reduce:animate-none" />}
            title={t("loadingTitle")}
            hint={t("loadingHint")}
            live
          />
        ) : tournamentQuery.isError || !tournament ? (
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
  action,
  live = false
}: {
  icon: ReactNode;
  title: string;
  hint: string;
  action?: ReactNode;
  live?: boolean;
}) {
  return (
    <section
      className="flex min-h-[60svh] flex-col items-center justify-center gap-3 text-center"
      role={live ? "status" : undefined}
      aria-live={live ? "polite" : undefined}
    >
      {icon}
      <h1 className="font-onest text-2xl font-semibold">{title}</h1>
      <p className="max-w-lg text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">{hint}</p>
      {action ? <div className="mt-2">{action}</div> : null}
    </section>
  );
}
