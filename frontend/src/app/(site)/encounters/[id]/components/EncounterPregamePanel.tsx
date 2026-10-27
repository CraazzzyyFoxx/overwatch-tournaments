"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Check, X } from "lucide-react";

import { cn } from "@/lib/utils";
import pickBanService from "@/services/pickBan.service";
import type { EncounterTeam } from "@/types/encounter.types";
import type { PickBanKind, PickBanState } from "@/types/tournament.types";
import { duelSeats, seatsBySlot } from "@/lib/encounter/seats";
import { CARD_SUB, CardHead, Fact, FactGrid, SectionHead } from "@/components/match/EncounterAtoms";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { StatusDot } from "@/components/ui/status-dot";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

interface EncounterPregamePanelProps {
  encounterId: number;
  teams: EncounterTeam[];
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
  teams
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
      <SectionHead title={t("encounters.detail.pregame")} />
      <div className="flex flex-col gap-3.5">
        {readiness ? (
          <Card className="overflow-hidden">
            <FactGrid flush>
              {seatsBySlot(teams).map((seat) => (
                <Fact key={seat.id} label={t("encounters.detail.readiness", { slot: seat.slot })}>
                  <ReadyMark ready={readiness[String(seat.id)] ?? false} />
                  {seat.name}
                </Fact>
              ))}
            </FactGrid>
          </Card>
        ) : null}

        {sections.map(({ kind, state, title }) => (
          <PregameSection key={kind} title={title} state={state!} teams={teams} />
        ))}
      </div>
    </section>
  );
}

function usePregameState(kind: PickBanKind, encounterId: number) {
  return useQuery({
    queryKey: encounterQueryKeys.pregameState(encounterId, kind),
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
  teams
}: Readonly<{
  title: string;
  state: PickBanState;
  teams: EncounterTeam[];
}>) {
  const t = useTranslations();
  const session = state.session;
  const decided = state.pool.filter((entry) => entry.status === "picked").length;
  const banned = state.pool.filter((entry) => entry.status === "banned").length;
  const [seatOne, seatTwo] = duelSeats(teams);
  const seatName = (id: number) => teams.find((seat) => seat.id === id)?.name ?? null;

  return (
    <Card className="overflow-hidden">
      <CardHead title={title}>
        {/* Only the running session keeps a chip: it is the one state that moves. */}
        {session && !state.is_complete ? (
          <Badge shape="pill" tone="accent">
            <StatusDot pulse className="text-[color:var(--aqt-status-live)]" />
            {t("encounters.veto.room.statusChip.active")}
          </Badge>
        ) : (
          <span className={cn(CARD_SUB, session && "text-[color:var(--aqt-emerald)]")}>
            {session
              ? t("encounters.veto.room.statusChip.completed")
              : t(`encounters.veto.room.empty.${reasonKey(state)}` as never)}
          </span>
        )}
      </CardHead>

      {session ? (
        <FactGrid>
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
          {session.first_team_id != null ? (
            <Fact label={t("encounters.detail.pregameFirst")}>{seatName(session.first_team_id)}</Fact>
          ) : null}
          {seatOne?.seed != null || seatTwo?.seed != null ? (
            <Fact label={t("encounters.detail.pregameSeeds")}>
              <span className="aqt-tnum">
                {seatOne?.seed != null ? `#${seatOne.seed}` : "—"}
                {" / "}
                {seatTwo?.seed != null ? `#${seatTwo.seed}` : "—"}
              </span>
              <span className={CARD_SUB}>
                {t(`encounters.veto.room.seedSource.${session.seed_source}` as never)}
              </span>
            </Fact>
          ) : null}
          {!state.is_complete && state.acting_team_ids.length > 0 ? (
            <Fact label={t("encounters.detail.pregameTurn")}>
              {state.acting_team_ids.map((id) => seatName(id)).join(" · ")}
            </Fact>
          ) : null}
        </FactGrid>
      ) : null}
    </Card>
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
      className={ready ? "text-[color:var(--aqt-emerald)]" : "text-[color:var(--aqt-fg-faint)]"}
      aria-label={ready ? t("common.checkedIn") : t("common.notCheckedIn")}
    />
  );
}

export type { EncounterPregamePanelProps };
