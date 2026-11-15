"use client";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { GameMark } from "@/components/workspace/GameMark";
import { cn } from "@/lib/utils";
import type { DisciplineDescriptor } from "@/types/discipline.types";

/**
 * A game's mark that narrows the scope to that game (spec §6.6-6.7). The game's name is the accessible name; the
 * click never reaches a clickable row or card around it.
 */
export function GameMarkButton({
  discipline,
  onSelect,
  size = 18,
  className
}: Readonly<{
  discipline: DisciplineDescriptor;
  onSelect: (code: string) => void;
  size?: number;
  className?: string;
}>) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="inline"
      aria-label={discipline.name}
      title={discipline.name}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(discipline.code);
      }}
      className={cn("shrink-0 rounded-md transition-opacity hover:bg-transparent hover:opacity-80", className)}
    >
      <GameMark discipline={discipline} size={size} decorative />
    </Button>
  );
}
