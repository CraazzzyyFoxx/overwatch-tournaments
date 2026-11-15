"use client";

import { Check, Hourglass } from "lucide-react";
import { useTranslations } from "next-intl";

import TeamName, { type TeamNameInput } from "@/components/TeamName";
import EncounterRosterPanel from "@/components/match/EncounterRosterPanel";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { cn } from "@/lib/utils";
import { seatAt, seatTeam, seatsBySlot } from "@/lib/encounter/seats";
import type { Encounter } from "@/types/encounter.types";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";

interface PregameReadinessProps {
  encounter: Encounter;
  /** `EncounterTeam.id` (as a string) -> whether that captain confirmed. */
  readiness: Record<string, boolean>;
  /** The participation the viewer captains; null for a spectator: they watch the gate, they never confirm. */
  viewerTeamId: number | null;
  pending: boolean;
  onReady: () => void;
}

/**
 * The readiness gate as the room's own content, not a modal over placeholders.
 *
 * This used to be an `AlertDialog` floating over two `Skeleton` blocks, which
 * read as "the room is loading" — a shimmer that never resolves, because there
 * is genuinely nothing to load yet: the backend does not create either session
 * (`pick_ban_session.ensure_pick_ban_session`) until both captains confirm, so
 * the pool and the step sequence do not exist and cannot be rendered. Faking
 * them promised content that was not coming, and the modal's backdrop hid the
 * one thing that IS real in this state — the header's matchup and series
 * standing.
 *
 * So the room renders for real: header above, and this panel where the pool
 * will go, naming both teams and which of them the room is still waiting on,
 * with both rosters under the ready button (captains crowned) so the wait shows
 * who is playing and whom to ping.
 */
export function PregameReadiness({
  encounter,
  readiness,
  viewerTeamId,
  pending,
  onReady
}: Readonly<PregameReadinessProps>) {
  const t = useTranslations("pickBan.room");
  const viewerReady = viewerTeamId != null && readiness[String(viewerTeamId)] === true;

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-[color:var(--aqt-border)] p-4">
      <div className="flex flex-col gap-1">
        <h2 className="inline-flex items-center gap-2 font-onest text-lg font-semibold">
          <Hourglass className="h-4 w-4 shrink-0 text-[color:var(--aqt-teal)]" aria-hidden />
          {t("notReadyTitle")}
        </h2>
        <p className="text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">
          {t("notReadyHint")}
        </p>
      </div>

      <ul className="grid gap-2 sm:grid-cols-2">
        {seatsBySlot(encounter.teams).map((seat) => (
          <ReadyRow
            key={seat.id}
            team={seatTeam(seat)}
            fallbackName={t("tbd")}
            ready={readiness[String(seat.id)] === true}
            accentVar={seat.slot === 1 ? "--aqt-teal" : "--aqt-rose"}
          />
        ))}
      </ul>

      {viewerTeamId != null ? (
        viewerReady ? (
          <p className="text-sm text-[color:var(--aqt-positive)]">
            {t("ready.confirmed")} · {t("ready.waitingOpponent")}
          </p>
        ) : (
          <div>
            <Button onClick={onReady} disabled={pending}>
              {pending ? <Spinner className="mr-2" /> : null}
              {pending ? t("ready.sending") : t("ready.button")}
            </Button>
          </div>
        )
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <EncounterRosterPanel
          team={seatAt(encounter.teams, 1)?.team ?? null}
          slot={1}
          workspaceId={encounter.workspace_id}
          discipline={encounter.discipline}
          tournamentGrid={encounter.tournament?.division_grid_version ?? null}
        />
        <EncounterRosterPanel
          team={seatAt(encounter.teams, 2)?.team ?? null}
          slot={2}
          workspaceId={encounter.workspace_id}
          discipline={encounter.discipline}
          tournamentGrid={encounter.tournament?.division_grid_version ?? null}
        />
      </div>
    </section>
  );
}

/** One seat's readiness: logo, name, and a check or an hourglass. */
function ReadyRow({
  team,
  fallbackName,
  ready,
  accentVar
}: Readonly<{
  team: TeamNameInput | null;
  fallbackName: string;
  ready: boolean;
  accentVar: "--aqt-teal" | "--aqt-rose";
}>) {
  const t = useTranslations("pickBan.room");
  const StateIcon = ready ? Check : Hourglass;
  const stateLabel = ready ? t("ready.stateReady") : t("ready.statePending");

  return (
    <li
      className={cn(
        "flex min-w-0 items-center gap-2.5 rounded-lg border px-3 py-2.5",
        ready
          ? "border-[color:var(--aqt-positive)]/35 bg-[color:var(--aqt-positive)]/[0.06]"
          : "border-dashed border-[color:var(--aqt-border-2)]"
      )}
    >
      <TeamName
        team={team}
        fallback={fallbackName}
        size="md"
        className="flex-1 gap-2.5"
        nameClassName={cn(
          "text-sm font-semibold",
          accentVar === "--aqt-teal"
            ? "text-[color:var(--aqt-teal)]"
            : "text-[color:var(--aqt-rose)]"
        )}
      />
      <span
        className={cn(
          eyebrowClass(),
          "inline-flex shrink-0 items-center gap-1.5",
          ready && "text-[color:var(--aqt-positive)]"
        )}
      >
        <StateIcon className="h-3.5 w-3.5" aria-hidden />
        {stateLabel}
      </span>
    </li>
  );
}
