"use client";

import { useTranslations } from "next-intl";

import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { ROSTER_SLOT_CODES } from "@/lib/roster/shape";
import { groupTournamentStageFlow } from "@/lib/tournament/stages";
import type { TeamFormation, Tournament } from "@/types/tournament.types";

import { PhaseTimeline } from "../../_components/PhaseTimeline";
import { TournamentLinkChips } from "../../_components/TournamentLinkChips";
import { STAGE_TYPE_LABEL } from "../tournamentOverview.model";
import { KeyValue, OverviewCard } from "./OverviewCards";

/** ⑦ The same timeline the registration branch opens on, second orientation. */
export function OverviewPhasesCard({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations();
  return (
    <OverviewCard title={t("tournamentDetail.overview.phases.title")} id="phases">
      <PhaseTimeline tournament={tournament} orientation="vertical" />
    </OverviewCard>
  );
}

/**
 * ③ Format and team formation — what the header used to carry as two pills.
 *
 * Present in EVERY branch, not only before the start: "how is this played" does
 * not stop being a question once the first match is played. The description is
 * NOT here — it is a paragraph, and a paragraph in the narrow aside column
 * broke into three-word lines; it has its own card in the wide column.
 */
export function OverviewFormatCard({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations();
  const tSlot = useTranslations("rosterShape.slotCodes");

  // Slots as role glyphs, not "2 × Урон": the icon is the site's role
  // vocabulary everywhere else. `RosterSlotGlyph` announces the slot name for
  // screen readers, and the wrapper's `title` names it for a pointer, which an
  // unlabelled shield-and-×2 pair could not.
  const rosterShape = tournament.roster_shape;
  const rosterSlots = rosterShape
    ? ROSTER_SLOT_CODES.filter((code) => (rosterShape.slots[code] ?? 0) > 0).map((code) => ({
        code,
        count: rosterShape.slots[code] as number
      }))
    : [];

  return (
    <OverviewCard title={t("tournamentDetail.overview.format.title")}>
      <dl className="grid gap-2.5">
        {tournament.stages.length > 0 ? (
          /* Organizer names + type. Same `order` is one phase (`Low / High`);
             the next number is the next wave (`Groups → Playoff`). */
          <KeyValue term={t("common.stages")}>
            {groupTournamentStageFlow(tournament.stages).map((wave, waveIndex) => (
              <span key={wave.map((stage) => stage.id).join("-")}>
                {waveIndex > 0 ? (
                  <span className="text-[color:var(--aqt-fg-faint)]">{" → "}</span>
                ) : null}
                {wave.map((stage, stageIndex) => {
                  const typeKey = STAGE_TYPE_LABEL[stage.stage_type];
                  const typeLabel = typeKey ? t(typeKey) : null;
                  // The suffix names the format behind an organizer's own stage
                  // name; a stage called "Swiss" does not need "(swiss)" after
                  // it. Case- and space-insensitive, because the name is typed
                  // by hand and the label comes from the message catalogue.
                  const showType =
                    typeLabel !== null &&
                    typeLabel.trim().toLowerCase() !== stage.name.trim().toLowerCase();
                  return (
                    <span key={stage.id}>
                      {stageIndex > 0 ? (
                        <span className="text-[color:var(--aqt-fg-faint)]">{" / "}</span>
                      ) : null}
                      {stage.name}
                      {showType ? (
                        <span className="text-[color:var(--aqt-fg-faint)]">
                          {" ("}
                          {typeLabel.toLowerCase()}
                          {")"}
                        </span>
                      ) : null}
                    </span>
                  );
                })}
              </span>
            ))}
          </KeyValue>
        ) : null}
        <KeyValue term={t("common.teamFormation")}>
          {t(
            `common.${(tournament.team_formation ?? "balancer") as TeamFormation}`
          )}
          {rosterSlots.length > 0 ? (
            <span className="ml-2 inline-flex items-center gap-2 align-middle">
              {rosterSlots.map(({ code, count }) => (
                <span
                  key={code}
                  className="inline-flex items-center gap-1"
                  title={`${tSlot(code)} ×${count}`}
                >
                  <RosterSlotGlyph code={code} size={14} />
                  <span className="aqt-tnum text-[color:var(--aqt-fg-faint)]">×{count}</span>
                </span>
              ))}
            </span>
          ) : null}
        </KeyValue>
      </dl>
    </OverviewCard>
  );
}

/**
 * The organizer's own description, in the WIDE column of every branch. It used
 * to be the last row of the format card, which sits in the ~22rem aside — wide
 * enough for "Double Elimination", not for a paragraph, which broke into
 * three-word lines there.
 */
export function OverviewAboutCard({ description }: Readonly<{ description: string }>) {
  const t = useTranslations();
  return (
    <OverviewCard title={t("tournamentDetail.overview.about.title")}>
      <p className="max-w-[70ch] whitespace-pre-line text-ui leading-relaxed text-[color:var(--aqt-fg-muted)]">
        {description}
      </p>
    </OverviewCard>
  );
}

/**
 * The organizer's Discord, rules and external bracket — moved out of the
 * header (see `TournamentLinkChips` for why) and always the LAST card of the
 * right column in all three branches. One predictable address beats a block
 * that migrates by phase.
 *
 * Rendered only when something is left to show: `visibleTournamentLinks` owns
 * that judgement at the call site, so a tournament whose only link is the
 * official stream does not get a heading over an empty row.
 */
export function OverviewLinksCard({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations();
  return (
    <OverviewCard title={t("tournamentDetail.links.heading")}>
      <TournamentLinkChips links={tournament.links} />
    </OverviewCard>
  );
}
