"use client";

import Link from "next/link";
import { ArrowLeft, Flag } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Encounter } from "@/types/encounter.types";
import type { EncounterMapPoolState, EncounterVetoSession } from "@/types/tournament.types";

import { turnDeadlineMs, type VetoSide } from "./veto-model";
import { VetoCountdown } from "./VetoCountdown";

interface VetoHeroProps {
  encounter: Encounter;
  state: EncounterMapPoolState;
  session: EncounterVetoSession;
}

const STATUS_CHIP_CLASSES: Record<EncounterVetoSession["status"], string> = {
  active:
    "border-[color:var(--aqt-teal)]/35 bg-[color:var(--aqt-teal)]/12 text-[color:var(--aqt-teal)]",
  completed:
    "border-[color:var(--aqt-support)]/35 bg-[color:var(--aqt-support)]/12 text-[color:var(--aqt-support)]",
  cancelled: "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-amber)]",
};

export function VetoHero({ encounter, state, session }: VetoHeroProps) {
  const t = useTranslations("encounters.veto.room");
  const deadline = turnDeadlineMs(state);
  const teamName = (side: VetoSide) =>
    side === "home"
      ? encounter.home_team?.name ?? t("side.home")
      : encounter.away_team?.name ?? t("side.away");

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href={`/encounters/${encounter.id}`}
            aria-label={t("back")}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:bg-[color:var(--aqt-card-2)] hover:text-[color:var(--aqt-fg)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <h1 className="font-onest text-xl font-semibold tracking-[-0.01em]">{t("title")}</h1>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em]",
              STATUS_CHIP_CLASSES[session.status],
            )}
          >
            {session.status === "active" ? (
              <span
                aria-hidden
                className="h-1.5 w-1.5 rounded-full bg-[color:var(--aqt-teal)] animate-pulse motion-reduce:animate-none"
                style={{ boxShadow: "0 0 8px var(--aqt-teal)" }}
              />
            ) : null}
            {t(`statusChip.${session.status}`)}
          </span>
          {deadline != null && session.turn_timer_seconds != null ? (
            <div className="ml-auto">
              <VetoCountdown deadline={deadline} totalSeconds={session.turn_timer_seconds} />
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <TeamBlock
            name={teamName("home")}
            seed={session.home_seed}
            accentVar="--aqt-teal"
            first={session.first_side === "home"}
          />
          <span className="font-onest text-lg font-semibold text-[color:var(--aqt-fg-faint)]">
            vs
          </span>
          <TeamBlock
            name={teamName("away")}
            seed={session.away_seed}
            accentVar="--aqt-rose"
            first={session.first_side === "away"}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 text-sm text-[color:var(--aqt-fg-muted)]">
          <Flag className="h-4 w-4 text-[color:var(--aqt-teal)]" aria-hidden />
          <span>{t("firstBanner", { team: teamName(session.first_side) })}</span>
          <Badge variant="outline" className="font-normal text-[color:var(--aqt-fg-muted)]">
            {t(`seedSource.${session.seed_source}`)}
          </Badge>
        </div>
      </CardContent>
    </Card>
  );
}

function TeamBlock({
  name,
  seed,
  accentVar,
  first,
}: {
  name: string;
  seed: number | null;
  accentVar: "--aqt-teal" | "--aqt-rose";
  first: boolean;
}) {
  const t = useTranslations("encounters.veto.room");
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span
        className="min-w-0 truncate font-onest text-lg font-semibold"
        style={{ color: `var(${accentVar})` }}
      >
        {name}
      </span>
      <Badge variant="secondary">
        {seed != null ? t("seedBadge", { seed }) : t("seedUnknown")}
      </Badge>
      {first ? (
        <Badge className="border-transparent bg-[color:var(--aqt-teal)]/15 text-[color:var(--aqt-teal)] hover:bg-[color:var(--aqt-teal)]/15">
          1st
        </Badge>
      ) : null}
    </div>
  );
}
