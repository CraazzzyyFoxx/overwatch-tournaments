"use client";

import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { DisciplineUnavailable } from "@/components/workspace/DisciplineUnavailable";
import { GameTabs } from "@/components/workspace/GameTabs";
import type { GameScopeState } from "@/hooks/useGameScope";
import { ALL_DISCIPLINES } from "@/lib/site/discipline-scope";

/**
 * What a game-scoped surface shows besides its data (spec §4.1, §4.3): the invalid or empty state with its way out —
 * "Показать все игры" on a multi page, the game tabs on a single or platform one — or the local game tabs when the
 * resolution asks for them. Nothing while the games are unknown, nor when the page's game needs no control.
 * `headingLevel={1}` when the page returns this control instead of its own hero.
 */
export function GameScopeControl({
  scope,
  variant,
  dropParams,
  className,
  headingLevel
}: Readonly<{
  scope: GameScopeState;
  variant: "multi" | "single";
  dropParams?: string[];
  className?: string;
  headingLevel?: 1 | 2;
}>) {
  const t = useTranslations("common.discipline");
  const { resolution, games } = scope;
  if (!resolution || !games) return null;
  const tabs = (value: string) => (
    <GameTabs
      games={games}
      value={value}
      onSelect={(code) => scope.selectTab(code, { dropParams })}
      label={t("select")}
      className={className}
    />
  );
  const { game } = resolution;
  if (game.kind === "empty") return <DisciplineUnavailable game={game} headingLevel={headingLevel} />;
  if (game.kind === "invalid") {
    return (
      <DisciplineUnavailable
        game={game}
        headingLevel={headingLevel}
        action={
          variant === "multi" ? (
            <Button variant="outline" onClick={() => scope.selectScope(ALL_DISCIPLINES, { dropParams })}>
              {t("showAll")}
            </Button>
          ) : (
            tabs("")
          )
        }
      />
    );
  }
  return resolution.tabs && game.kind === "game" ? tabs(game.code) : null;
}
