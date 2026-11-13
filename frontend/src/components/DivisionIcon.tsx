"use client";

import Image from "@/components/ui/image";
import { IconTooltip } from "@craazzzyyfoxx/admin-kit/ui/icon-tooltip";

import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionIconSrc, getDivisionLabel } from "@/lib/divisions/grid";
import { cn } from "@/lib/utils";
import type { DivisionGrid, DivisionGridVersion } from "@/types/workspace.types";

interface DivisionIconProps {
  /** `null` (an unranked player) draws nothing. */
  division: number | null;
  tournamentGrid?: DivisionGridVersion | DivisionGrid | null;
  discipline?: string;
  width?: number;
  height?: number;
  /**
   * Name the crest in a hover tooltip, which also carries its accessible name
   * (DESIGN.md §11: divisions are icon only). `className` then lands on the
   * tooltip's wrapper, not the image.
   */
  tooltip?: boolean;
  className?: string;
}

/**
 * Rank crest for a division number. Nothing is drawn when the grid has no
 * icon for it, or for no division (an unranked player) — a broken image glyph
 * is worse than no crest. With `tooltip` the wrapper stays, so a grid row
 * keeps the crest's cell.
 */
const DivisionIcon = ({
  division,
  tournamentGrid,
  discipline,
  width = 36,
  height = 36,
  tooltip = false,
  className
}: DivisionIconProps) => {
  const workspaceGrid = useDivisionGrid(discipline);
  if (division == null) return tooltip ? <span aria-hidden className={cn("shrink-0", className)} /> : null;
  const preferredGrid = tournamentGrid ?? workspaceGrid;
  const src = getDivisionIconSrc(preferredGrid, division);
  const name = getDivisionLabel(preferredGrid, division) ?? `Division ${division}`;

  const image = src ? (
    <Image
      src={src}
      alt={tooltip ? "" : name}
      width={width}
      height={height}
      className={tooltip ? undefined : className}
      loading="lazy"
      decoding="async"
    />
  ) : null;

  if (!tooltip) return image;
  return (
    <IconTooltip label={name} className={cn("shrink-0", className)}>
      {image}
    </IconTooltip>
  );
};

export default DivisionIcon;
