"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { kindOf } from "@/lib/flow/kinds";
import { formulaInWords } from "@/lib/flow/leaderboardTable";
import {
  summarizeFormat,
  summarizeStageWaves,
  type FormatStageRef,
  type FormatStep,
  type FormatTeams,
  type FormatTransition
} from "@/lib/flow/formatSummary";
import { slotCodesOf } from "@/lib/roster/shape";
import { showsRoles } from "@/lib/roster/ontology";
import { groupTournamentStageFlow } from "@/lib/tournament/stages";
import { cn } from "@/lib/utils";
import { primaryFormationMode } from "@/lib/tournament/flow-nodes";
import type { Tournament } from "@/types/tournament.types";

import { flowQueryOptions } from "../../_queries/flow";
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
 * ③ "How it's played": the steps of the tournament in play order, read off its
 * flow (a stage, parallel divisions, or the match days of a league), with what
 * each stage's own regulation says a reader needs to follow it, a short line
 * between steps for who moves on, then the shape of a team.
 *
 * Present in EVERY branch, not only before the start: "how is this played"
 * does not stop being a question once the first match is played. A tournament
 * without flow data, or while it loads/fails, shows its stages grouped by
 * `order` instead.
 */
export function OverviewFormatCard({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations();
  const flowQuery = useQuery(flowQueryOptions(tournament));
  // The tournament's own game names and draws its roster slots.
  const ontology =
    useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;
  const slotLabel = useSlotLabel(ontology);

  const flow = flowQuery.data;
  const summary = useMemo(
    () =>
      flow?.nodes.some((node) => kindOf(node) === "stage")
        ? summarizeFormat(flow, tournament.stages)
        : summarizeStageWaves(groupTournamentStageFlow(tournament.stages)),
    [flow, tournament.stages]
  );
  const hasTable = flow?.nodes.some((node) => kindOf(node) === "leaderboard") ?? false;
  const { intro, steps } = summary;
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
  const showGlyphs = rosterSlots.length > 0 && showsRoles(ontology);

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
      case "grandFinal":
        return t(
          fact.reset
            ? "tournamentDetail.overview.format.grandFinalReset"
            : "tournamentDetail.overview.format.grandFinalNoReset"
        );
    }
  };

  const transitionText = (transition: FormatTransition) => {
    const key = "tournamentDetail.overview.format.transition";
    switch (transition.kind) {
      case "top":
        return t(`${key}.top`, { n: transition.n });
      case "perItemTop":
        if (transition.upper === null)
          return t(`${key}.${transition.grouped ? "perItemTop" : "top"}`, { n: transition.n });
        return t(`${key}.${transition.grouped ? "perItemUpper" : "upper"}`, {
          n: transition.n,
          upper: transition.upper
        });
      case "range":
        return t(`${key}.range`, { from: transition.from, to: transition.to });
      case "swissStatus":
        return t(`${key}.${transition.status}`);
      case "manual":
        return t(`${key}.manual`);
      case "split":
        return t(`${key}.split`, { names: transition.buckets.join(" / ") });
    }
  };

  const introText = intro ? t(`tournamentDetail.overview.format.intro.${intro.intake}`) : null;

  const teamsText = (teams: FormatTeams) => {
    const key = "tournamentDetail.overview.format.teams";
    const mode = t(`${key}.mode.${teams.mode}`);
    const how = teams.renewed ? t(`${key}.${teams.renewed}`, { mode }) : mode;
    return [t(`${key}.line`, { how }), teams.byScore ? t(`${key}.byScore`) : null]
      .filter(Boolean)
      .join(" · ");
  };

  const renderStage = (ref: FormatStageRef) => {
    const stage = tournament.stages.find((item) => item.id === ref.stageId);
    const name = stage?.name ?? ref.name;
    const format = stage ? stageFormatOf(stage.stage_type) : null;
    const typeLabel = format ? t(`tournamentDetail.overview.format.types.${format}.name`) : null;
    // The chip names the format behind an organizer's own stage
    // name and opens its explanation; a stage called "Swiss
    // system" does not need the name twice, so its chip is the
    // icon alone. Case- and space-insensitive, because the name is
    // typed by hand and the label comes from the message catalogue.
    const showType =
      typeLabel !== null && typeLabel.trim().toLowerCase() !== name.trim().toLowerCase();
    const facts = stage ? stageFacts(stage) : [];
    return (
      <div key={ref.stageId ?? ref.name} className="min-w-0">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-ui font-semibold">
          {name}
          {format && typeLabel ? (
            <StageFormatDialog
              format={format}
              name={typeLabel}
              stageName={name}
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
  };

  const renderLeague = (step: FormatStep) => {
    const rule = step.league?.rule;
    if (!rule) return null;
    const line = [
      t(`tournamentDetail.overview.format.league.mode.${rule.mode.key}`, {
        n: rule.mode.n ?? 0,
        total: step.stages.length
      }),
      t(`tournamentDetail.overview.format.league.score.${rule.score.key}`, {
        formula: formulaInWords(rule.score.formula ?? "", (variable) =>
          t(`tournamentDetail.table.formula.variables.${variable}`)
        )
      })
    ].join(" · ");
    return (
      <div className="min-w-0">
        <p className="text-ui font-semibold">
          {t("tournamentDetail.overview.format.days", { count: step.stages.length })}
        </p>
        <p className="text-caption text-[color:var(--aqt-fg-muted)]">
          {line}
          {hasTable ? (
            <>
              {" · "}
              <Link
                href={`/tournaments/${tournament.slug}/table`}
                className="underline-offset-2 hover:text-[color:var(--aqt-teal)] hover:underline"
              >
                {t("common.table")}
              </Link>
            </>
          ) : null}
        </p>
      </div>
    );
  };

  const formation = primaryFormationMode(tournament);
  const showFormationText = formation !== null && !steps.some((step) => step.teams);
  const showTeam = showFormationText || showGlyphs;
  const loading = flowQuery.isPending;

  return (
    <OverviewSection title={t("tournamentDetail.overview.format.title")}>
      {introText ? (
        <p className={cn("text-ui text-[color:var(--aqt-fg-muted)]", steps.length > 0 && "mb-3")}>
          {introText}
        </p>
      ) : null}
      {loading ? (
        <Skeleton className="h-24" />
      ) : steps.length > 0 ? (
        <ol>
          {steps.map((step, index) => {
            const isLast = index === steps.length - 1;
            const next = steps[index + 1]?.transitions ?? [];
            return (
              <li
                key={step.key}
                aria-current={step.state === "current" ? "step" : undefined}
                className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-x-3"
              >
                <div aria-hidden className="flex flex-col items-center">
                  <span
                    className={cn(
                      "aqt-tnum grid size-6 shrink-0 place-items-center rounded-full border text-label",
                      step.state === "current" &&
                        "border-[color:var(--aqt-teal)] text-[color:var(--aqt-teal)]",
                      step.state === "done" &&
                        "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-muted)]",
                      step.state === "upcoming" &&
                        "border-[color:var(--aqt-border)] text-[color:var(--aqt-fg-faint)]"
                    )}
                  >
                    {step.state === "done" ? <Check className="size-3.5" /> : index + 1}
                  </span>
                  {isLast ? null : (
                    <Separator orientation="vertical" className="mt-1 h-auto flex-1" />
                  )}
                </div>
                <div
                  className={cn(
                    "grid min-w-0 content-start gap-2 pt-0.5",
                    isLast ? "pb-0" : "pb-4",
                    step.state === "upcoming"
                      ? "text-[color:var(--aqt-fg-muted)]"
                      : "text-[color:var(--aqt-fg)]"
                  )}
                >
                  {step.state === "done" ? (
                    <span className="sr-only">
                      {t("tournamentDetail.overview.format.stepDone")}
                    </span>
                  ) : null}
                  {step.league ? renderLeague(step) : step.stages.map(renderStage)}
                  {step.teams ? (
                    <p className="text-caption text-[color:var(--aqt-fg-muted)]">
                      {teamsText(step.teams)}
                    </p>
                  ) : null}
                  {next.length > 0 ? (
                    <p className="text-caption text-[color:var(--aqt-fg-dim)]">
                      {next.map(transitionText).join(" · ")}
                    </p>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      ) : null}
      {showTeam ? (
        <dl className={cn("grid gap-1", steps.length > 0 && "mt-4")}>
          <Eyebrow as="dt">{t("tournamentDetail.overview.format.team")}</Eyebrow>
          <dd className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-ui text-[color:var(--aqt-fg)]">
            {showFormationText && formation ? t(`common.formationMode.${formation}`) : null}
            {/* One role: every slot is it, so the glyph row would say nothing. */}
            {showGlyphs ? (
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
      ) : null}
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
