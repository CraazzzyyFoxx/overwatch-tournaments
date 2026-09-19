"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { LoaderCircle } from "lucide-react";

import { stageRoundShape } from "@/lib/bracket-view";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { cn } from "@/lib/utils";
import type { PickBanConfig, PickBanKind, Stage } from "@/types/tournament.types";
import type { PickBanScopeEncounter } from "@/lib/pick-ban-config";
import { useStageRounds } from "./useStageRounds";
import {
  encodePreGameScope,
  scopeConfigState,
  type PreGameScope,
  type ScopeConfigState
} from "./pre-game-scope";

const MARKER_CLASS: Record<ScopeConfigState, string> = {
  own: "bg-primary",
  // Dashed-looking: rules are here, candidates are not.
  template: "border border-primary bg-transparent",
  redundant: "bg-primary/40",
  inherited: "bg-muted-foreground/40",
  none: "border border-border bg-transparent"
};

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
            "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          )}
        >
          <span aria-hidden className={cn("size-2 shrink-0 rounded-full", MARKER_CLASS[state])} />
          <span className="min-w-0 flex-1 truncate">{label}</span>
          <span className="shrink-0 text-xs text-muted-foreground">
            {t(`scopeState.${state}`)}
          </span>
        </Link>
      </li>
    );
  };

  return (
    <nav aria-label={t("scopeTreeLabel")} className="rounded-xl border border-border bg-card p-2">
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
                      <li className="flex items-center gap-2 ps-8 py-1.5 text-xs text-muted-foreground">
                        <LoaderCircle aria-hidden className="size-3.5 animate-spin" />
                        {t("roundHintLoading")}
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
