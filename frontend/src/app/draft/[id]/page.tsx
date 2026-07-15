"use client";

import { ArrowLeft, Loader2, Radio, ShieldAlert } from "lucide-react";
import Link from "next/link";
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
      <header
        className={`${styles.toolbar} sticky top-0 z-40 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]/88 backdrop-blur-xl`}
      >
        <div className="mx-auto flex min-h-16 w-full max-w-[1600px] items-center gap-4 px-4 sm:px-6 xl:px-10">
          <Link
            href={`/tournaments/${tournamentId}`}
            className={`${styles.backLink} inline-flex min-h-11 items-center gap-2 rounded-lg border border-[color:var(--aqt-border-2)] px-3 text-sm font-medium outline-none transition-colors hover:border-[color:var(--aqt-teal)]/60 hover:text-[color:var(--aqt-teal)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]`}
          >
            <ArrowLeft className={`${styles.backArrow} h-4 w-4`} />
            <span className="hidden sm:inline">{t("room.back")}</span>
            <span className="sm:hidden">{t("room.backShort")}</span>
          </Link>

          <div className="min-w-0 border-l border-[color:var(--aqt-border)] pl-4">
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-[color:var(--aqt-fg-faint)]">
              {t("room.coordinate")}
            </p>
            <p className="truncate font-onest text-sm font-semibold text-[color:var(--aqt-fg)]">
              {tournament?.name ?? t("room.loadingName")}
            </p>
          </div>

          <div className="ml-auto flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-[color:var(--aqt-fg-muted)]">
            <Radio className="h-3.5 w-3.5 text-[color:var(--aqt-teal)]" />
            <span className="hidden sm:inline">{t("room.publicBoard")}</span>
          </div>
        </div>
        <span className={styles.rail} aria-hidden />
      </header>

      <main className={`${styles.stage} mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6 sm:py-7 xl:px-10`}>
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
