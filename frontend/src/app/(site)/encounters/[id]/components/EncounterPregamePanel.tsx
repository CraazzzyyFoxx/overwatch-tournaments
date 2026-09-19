"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Check, X } from "lucide-react";

import { cn } from "@/lib/utils";
import pickBanService from "@/services/pickBan.service";
import type { PickBanKind, PickBanState } from "@/types/tournament.types";
import { Fact, Pill } from "@/components/match/EncounterAtoms";
import styles from "@/components/match/EncounterDetail.module.css";

interface EncounterPregamePanelProps {
  encounterId: number;
  homeName: string;
  awayName: string;
}

/**
 * Pre-game state summary: readiness, seeding and veto/ban progress.
 *
 * The page already fetched exactly this to decide whether to show the pre-game
 * link, then threw it away. Seeds and their provenance in particular exist
 * nowhere else on a public page. Shares `PregameRoomLink`'s query keys, so
 * rendering both costs one request per kind.
 */
export default function EncounterPregamePanel({
  encounterId,
  homeName,
  awayName
}: Readonly<EncounterPregamePanelProps>) {
  const t = useTranslations();
  const mapQuery = usePregameState("map", encounterId);
  const heroQuery = usePregameState("hero", encounterId);

  const sections = (
    [
      { kind: "map" as const, state: mapQuery.data, title: t("encounters.detail.pregameMap") },
      { kind: "hero" as const, state: heroQuery.data, title: t("encounters.detail.pregameHero") }
    ] satisfies { kind: PickBanKind; state: PickBanState | null | undefined; title: string }[]
  ).filter((section) => applies(section.state));

  if (sections.length === 0) return null;

  const readiness = sections[0].state?.readiness;

  return (
    // The section lives here, not in the page: this panel renders nothing for a
    // tournament without pre-game rules, and an empty landmark with a heading
    // would still be announced.
    <section aria-label={t("encounters.detail.pregame")}>
      {/* No section meta: it read "Map veto and hero bans" directly above two
          cards titled "Map veto" and "Hero bans". */}
      <div className={styles.sectionHead}>
        <h2 className={styles.sectionTitle}>{t("encounters.detail.pregame")}</h2>
      </div>
      <div className={styles.statsStack}>
        {readiness ? (
          <div className={styles.card}>
            <div className={cn(styles.factGrid, styles.factGridFlush)}>
              <Fact label={t("encounters.detail.readinessHome")}>
                <ReadyMark ready={readiness.home} />
                {homeName}
              </Fact>
              <Fact label={t("encounters.detail.readinessAway")}>
                <ReadyMark ready={readiness.away} />
                {awayName}
              </Fact>
            </div>
          </div>
        ) : null}

        {sections.map(({ kind, state, title }) => (
          <PregameSection
            key={kind}
            title={title}
            state={state!}
            homeName={homeName}
            awayName={awayName}
          />
        ))}
      </div>
    </section>
  );
}

function usePregameState(kind: PickBanKind, encounterId: number) {
  return useQuery({
    queryKey: ["pregame-state", encounterId, kind],
    queryFn: () => pickBanService.getPickBanState(kind, encounterId),
    staleTime: 30_000
  });
}

/** Same rule `PregameRoomLink` uses: a configured kind, or one already running. */
function applies(state: PickBanState | null | undefined): boolean {
  return state != null && (state.reason !== "not_configured" || state.session != null);
}

function PregameSection({
  title,
  state,
  homeName,
  awayName
}: Readonly<{
  title: string;
  state: PickBanState;
  homeName: string;
  awayName: string;
}>) {
  const t = useTranslations();
  const session = state.session;
  const decided = state.pool.filter(
    (entry) => entry.status === "picked" || entry.status === "played"
  ).length;
  const banned = state.pool.filter((entry) => entry.status === "banned").length;
  const sideName = (side: "home" | "away" | null) =>
    side === "home" ? homeName : side === "away" ? awayName : null;

  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        <h3 className={styles.cardTitle}>{title}</h3>
        {session ? (
          <Pill tone={state.is_complete ? "good" : "accent"} live={!state.is_complete}>
            {state.is_complete
              ? t("encounters.veto.room.statusChip.completed")
              : t("encounters.veto.room.statusChip.active")}
          </Pill>
        ) : (
          <Pill>{t(`encounters.veto.room.empty.${reasonKey(state)}` as never)}</Pill>
        )}
      </div>

      {session ? (
        <div className={styles.factGrid}>
          {/* Not `veto.room.steps.title` ("Veto steps"): this same strip renders
              over the hero-ban session too. */}
          <Fact label={t("encounters.detail.pregameSteps")}>
            {t("encounters.detail.pregameProgress", {
              done: Math.min(
                state.current_step_index ?? state.sequence.length,
                state.sequence.length
              ),
              total: state.sequence.length
            })}
          </Fact>
          <Fact label={t("encounters.detail.pregamePicked")}>{decided}</Fact>
          <Fact label={t("encounters.detail.pregameBanned")}>{banned}</Fact>
          {session.first_side ? (
            <Fact label={t("encounters.detail.pregameFirst")}>{sideName(session.first_side)}</Fact>
          ) : null}
          {session.home_seed != null || session.away_seed != null ? (
            <Fact label={t("encounters.detail.pregameSeeds")}>
              <span className={styles.mono}>
                {session.home_seed != null ? `#${session.home_seed}` : "—"}
                {" / "}
                {session.away_seed != null ? `#${session.away_seed}` : "—"}
              </span>
              <span className={styles.cardSub}>
                {t(`encounters.veto.room.seedSource.${session.seed_source}` as never)}
              </span>
            </Fact>
          ) : null}
          {!state.is_complete && state.turn_side ? (
            <Fact label={t("encounters.detail.pregameTurn")}>{sideName(state.turn_side)}</Fact>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** `reason` is absent once a session exists; fall back to the generic copy. */
function reasonKey(state: PickBanState): string {
  switch (state.reason) {
    case "teams_unknown":
      return "teamsUnknownTitle";
    case "slot_count_mismatch":
      return "slotCountMismatchTitle";
    case "slot_underfilled":
      return "slotUnderfilledTitle";
    case "not_ready":
      return "notReadyTitle";
    case "waiting_map":
      return "waitingMapTitle";
    case "bracket_preview":
      return "bracketPreviewTitle";
    default:
      return "notConfiguredTitle";
  }
}

function ReadyMark({ ready }: Readonly<{ ready: boolean }>) {
  const t = useTranslations();
  const Icon = ready ? Check : X;
  return (
    <Icon
      width={15}
      height={15}
      className={ready ? styles.flagGood : styles.flagOff}
      aria-label={ready ? t("common.checkedIn") : t("common.notCheckedIn")}
    />
  );
}

export type { EncounterPregamePanelProps };
