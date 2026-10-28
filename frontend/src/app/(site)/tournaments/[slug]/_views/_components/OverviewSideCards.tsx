"use client";

import { useTranslations } from "next-intl";

import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Separator } from "@/components/ui/separator";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { slotCodesOf } from "@/lib/roster/shape";
import { showsRoles } from "@/lib/roster/ontology";
import { groupTournamentStageFlow } from "@/lib/tournament/stages";
import { cn } from "@/lib/utils";
import type { TeamFormation, Tournament } from "@/types/tournament.types";

import { PhaseTimeline } from "../../_components/PhaseTimeline";
import { TournamentLinkChips } from "../../_components/TournamentLinkChips";
import { stageFacts, stageFormatOf, type StageFact } from "../tournamentOverview.model";
import { OverviewSection } from "./OverviewCards";
import { StageFormatDialog } from "./StageFormatDialog";

/** ⑦ The phase timeline once play has started: context in the side column, not content. */
export function OverviewPhasesCard({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations();
  return (
    <OverviewSection title={t("tournamentDetail.overview.phases.title")} id="phases">
      <PhaseTimeline tournament={tournament} />
    </OverviewSection>
  );
}

/**
 * ③ "How it's played": the stages in play order, each with what its own
 * regulation says a reader needs to follow it (how many rounds, how long a
 * series, how a team gets through), then the shape of a team.
 *
 * Present in EVERY branch, not only before the start: "how is this played"
 * does not stop being a question once the first match is played. Stages that
 * share an `order` are one step (parallel brackets, `Low / High`).
 */
export function OverviewFormatCard({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations();
  // The tournament's own game names and draws its roster slots.
  const ontology =
    useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;
  const slotLabel = useSlotLabel(ontology);

  const waves = groupTournamentStageFlow(tournament.stages);
  // Slots as role glyphs, not "2 × Урон": the icon is the site's role
  // vocabulary everywhere else. `RosterSlotGlyph` announces the slot name for
  // screen readers, and the wrapper's `title` names it for a pointer.
  const rosterShape = tournament.roster_shape;
  const rosterSlots = rosterShape
    ? slotCodesOf(rosterShape.slots).map((code) => ({
        code,
        count: rosterShape.slots[code] as number
      }))
    : [];

  const factText = (fact: StageFact) => {
    switch (fact.kind) {
      case "rounds":
        return t("tournamentDetail.overview.format.rounds", { count: fact.count });
      case "bestOf":
        return `Bo${fact.n}`;
      case "finalBestOf":
        return t("tournamentDetail.overview.format.final", { n: fact.n });
      case "qualify":
        return t("tournamentDetail.overview.format.qualify", { count: fact.count });
      case "eliminate":
        return t("tournamentDetail.overview.format.eliminate", { count: fact.count });
      case "advance":
        return t("tournamentDetail.overview.format.advance", { count: fact.count });
      case "grandFinal":
        return t(
          fact.reset
            ? "tournamentDetail.overview.format.grandFinalReset"
            : "tournamentDetail.overview.format.grandFinalNoReset"
        );
    }
  };

  return (
    <OverviewSection title={t("tournamentDetail.overview.format.title")}>
      {waves.length > 0 ? (
        <ol>
          {waves.map((wave, waveIndex) => {
            const isLast = waveIndex === waves.length - 1;
            return (
              <li
                key={wave.map((stage) => stage.id).join("-")}
                className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-x-3"
              >
                <div aria-hidden className="flex flex-col items-center">
                  <span className="aqt-tnum grid size-6 shrink-0 place-items-center rounded-full border border-[color:var(--aqt-border-2)] text-label text-[color:var(--aqt-fg-muted)]">
                    {waveIndex + 1}
                  </span>
                  {isLast ? null : (
                    <Separator orientation="vertical" className="mt-1 h-auto flex-1" />
                  )}
                </div>
                <div
                  className={cn(
                    "grid min-w-0 content-start gap-2 pt-0.5",
                    isLast ? "pb-0" : "pb-4"
                  )}
                >
                  {wave.map((stage) => {
                    const format = stageFormatOf(stage.stage_type);
                    const typeLabel = format
                      ? t(`tournamentDetail.overview.format.types.${format}.name`)
                      : null;
                    // The chip names the format behind an organizer's own stage
                    // name and opens its explanation; a stage called "Swiss
                    // system" does not need the name twice, so its chip is the
                    // icon alone. Case- and space-insensitive, because the name is
                    // typed by hand and the label comes from the message catalogue.
                    const showType =
                      typeLabel !== null &&
                      typeLabel.trim().toLowerCase() !== stage.name.trim().toLowerCase();
                    const facts = stageFacts(stage, !isLast);
                    return (
                      <div key={stage.id} className="min-w-0">
                        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-ui font-semibold text-[color:var(--aqt-fg)]">
                          {stage.name}
                          {format && typeLabel ? (
                            <StageFormatDialog
                              format={format}
                              name={typeLabel}
                              stageName={stage.name}
                              showLabel={showType}
                            />
                          ) : null}
                        </p>
                        {facts.length > 0 ? (
                          <p className="aqt-tnum text-caption text-[color:var(--aqt-fg-muted)]">
                            {facts.map(factText).join(" · ")}
                          </p>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              </li>
            );
          })}
        </ol>
      ) : null}
      <dl className={cn("grid gap-1", waves.length > 0 && "mt-4")}>
        <Eyebrow as="dt">{t("tournamentDetail.overview.format.team")}</Eyebrow>
        <dd className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-ui text-[color:var(--aqt-fg)]">
          {t(`common.${(tournament.team_formation ?? "balancer") as TeamFormation}`)}
          {/* One role: every slot is it, so the glyph row would say nothing. */}
          {rosterSlots.length > 0 && showsRoles(ontology) ? (
            <span className="inline-flex items-center gap-2">
              {rosterSlots.map(({ code, count }) => (
                <span
                  key={code}
                  className="inline-flex items-center gap-1"
                  title={`${slotLabel(code)} ×${count}`}
                >
                  <RosterSlotGlyph code={code} ontology={ontology} size={14} />
                  <span className="aqt-tnum text-caption text-[color:var(--aqt-fg-faint)]">
                    ×{count}
                  </span>
                </span>
              ))}
            </span>
          ) : null}
        </dd>
      </dl>
    </OverviewSection>
  );
}

/**
 * The organizer's own description, at the foot of the WIDE column in every
 * branch: prose in the ~22rem reference column broke into three-word lines.
 */
export function OverviewAboutCard({ description }: Readonly<{ description: string }>) {
  const t = useTranslations();
  return (
    <OverviewSection title={t("tournamentDetail.overview.about.title")}>
      <p className="max-w-[70ch] whitespace-pre-line text-ui leading-relaxed text-[color:var(--aqt-fg-muted)]">
        {description}
      </p>
    </OverviewSection>
  );
}

/**
 * The organizer's Discord, rules and external bracket — always the LAST block
 * of the reference column, in all three branches. One predictable address beats
 * a block that migrates by phase.
 *
 * Rendered only when something is left to show: `visibleTournamentLinks` owns
 * that judgement at the call site, so a tournament whose only link is the
 * official stream does not get a heading over an empty row.
 */
export function OverviewLinksCard({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations();
  return (
    <OverviewSection title={t("tournamentDetail.links.heading")}>
      <TournamentLinkChips links={tournament.links} />
    </OverviewSection>
  );
}
