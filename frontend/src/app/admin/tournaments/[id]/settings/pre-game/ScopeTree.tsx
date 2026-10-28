"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { stageRoundShape } from "@/lib/bracket/view";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { cn } from "@/lib/utils";
import type { PickBanConfig, PickBanKind, Stage } from "@/types/tournament.types";
import type { PickBanScopeEncounter } from "@/lib/tournament/pick-ban-config";
import { Skeleton } from "@/components/ui/skeleton";
import { useStageRounds } from "./useStageRounds";
import {
  encodePreGameScope,
  scopeConfigState,
  type PreGameScope,
  type ScopeConfigState
} from "./pre-game-scope";

/**
 * The states worth a word on the row. Inherited and no-rules are the default
 * of every scope that nobody touched; a list where most rows say "inherited"
 * says nothing.
 */
const MARKED_STATES: ReadonlySet<ScopeConfigState> = new Set(["own", "template", "redundant"]);

export interface ScopeTreeProps {
  kind: PickBanKind;
  stages: Stage[];
  encounters?: PickBanScopeEncounter[];
  configs: PickBanConfig[];
  /** Scope in the URL, or null while nothing is selected. */
  selected: PreGameScope | null;
  hrefFor: (scope: PreGameScope) => string;
}

/**
 * Tournament › Stage › Round, with a marker per node saying whether its rules
 * are its own or inherited.
 *
 * Replaces a scope `<Select>` pair (stage, then round) that could say what a
 * config applied to but never where the cascade was actually overridden — the
 * question an organizer opens this page with. Rounds are listed for the
 * selected stage only: they cost a bracket prediction per stage, and a tree
 * that expands every stage is a wall of rounds nobody is editing.
 *
 * Deliberately links rather than buttons: a scope is a URL (`?scope=`), so it
 * is shareable and the browser's Back works — which is also what
 * `MasterDetail`'s narrow-viewport Back button relies on.
 */
export function ScopeTree({
  kind,
  stages,
  encounters,
  configs,
  selected,
  hrefFor
}: Readonly<ScopeTreeProps>) {
  const t = useTranslations("pickBan.admin");
  const roundLabel = useBracketRoundLabel();

  const sortedStages = useMemo(
    () => [...stages].sort((left, right) => left.order - right.order),
    [stages]
  );

  const expandedStageId = selected?.stageId ?? null;
  const expandedStage = sortedStages.find((stage) => stage.id === expandedStageId);
  const { rounds, loading: roundsLoading } = useStageRounds(expandedStage, encounters);
  const roundShape = stageRoundShape(
    expandedStageId,
    expandedStage?.stage_type,
    rounds,
    encounters
  );

  const node = (scope: PreGameScope, label: string, depth: 0 | 1 | 2) => {
    const state = scopeConfigState(kind, scope, configs);
    const isSelected =
      selected != null && selected.stageId === scope.stageId && selected.round === scope.round;

    return (
      <li key={encodePreGameScope(scope)}>
        <Link
          href={hrefFor(scope)}
          aria-current={isSelected ? "true" : undefined}
          className={cn(
            "flex items-center gap-2 rounded-md py-1.5 pe-2 text-sm transition-colors",
            depth === 0 && "ps-2",
            depth === 1 && "ps-5",
            depth === 2 && "ps-8",
            isSelected
              ? "bg-accent/40 font-medium text-foreground"
              : "text-muted-foreground hover:text-foreground",
            "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-hidden"
          )}
        >
          <span className="min-w-0 flex-1 truncate">{label}</span>
          {MARKED_STATES.has(state) ? (
            <span className="shrink-0 text-xs text-muted-foreground">
              {t(`scopeState.${state}`)}
            </span>
          ) : null}
        </Link>
      </li>
    );
  };

  return (
    <nav aria-label={t("scopeTreeLabel")}>
      <ul className="flex flex-col gap-0.5">
        {node({ stageId: null, round: null }, t("tournamentLevel"), 0)}

        {sortedStages.map((stage) => (
          <li key={stage.id}>
            <ul className="flex flex-col gap-0.5">
              {node({ stageId: stage.id, round: null }, stage.name, 1)}

              {stage.id === expandedStageId ? (
                <li>
                  <ul className="flex flex-col gap-0.5">
                    {roundsLoading ? (
                      <li className="py-1.5 ps-8">
                        <Skeleton className="h-4 w-32" />
                        <span className="sr-only">{t("roundHintLoading")}</span>
                      </li>
                    ) : rounds.length === 0 ? (
                      <li className="py-1.5 ps-8 text-xs text-muted-foreground">
                        {t("roundHintUnknown")}
                      </li>
                    ) : (
                      rounds.map((round) =>
                        node(
                          { stageId: stage.id, round },
                          roundLabel(round, roundShape),
                          2
                        )
                      )
                    )}
                  </ul>
                </li>
              ) : null}
            </ul>
          </li>
        ))}
      </ul>
    </nav>
  );
}
