"use client";

import type { ReactNode } from "react";

import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import type { GameScopeState } from "@/hooks/useGameScope";

/**
 * The body of a multi admin page once its game is known (spec §4.1, §4.3): the invalid or empty notice, the error
 * card, a placeholder while the area's games load, else `children(game)` — `null` is every game, a code that game.
 */
export function GameScopeGate({
  scope,
  children
}: Readonly<{ scope: GameScopeState; children: (game: string | null) => ReactNode }>) {
  if (scope.resolution === null) {
    return scope.isError ? (
      <PageStateCard state="error" onAction={scope.refetch} />
    ) : (
      <Skeleton className="h-64 w-full rounded-xl" />
    );
  }
  const { kind } = scope.resolution.game;
  if (kind === "invalid" || kind === "empty") return <GameScopeControl scope={scope} variant="multi" />;
  return <>{children(scope.game)}</>;
}
