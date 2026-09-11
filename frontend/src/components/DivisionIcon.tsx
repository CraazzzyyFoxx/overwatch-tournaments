"use client";

import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionIconSrc, getDivisionLabel } from "@/lib/division-grid";
import type { DivisionGrid, DivisionGridVersion } from "@/types/workspace.types";

interface DivisionIconProps {
  division: number;
  tournamentGrid?: DivisionGridVersion | DivisionGrid | null;
  width?: number;
  height?: number;
  className?: string;
}

/**
 * Rank crest for a division number.
 *
 * Plain `<img>` (not `next/image`) for the same reason team logos use one: stored
 * `icon_url`s point at whatever S3 host the deployment configured, and
 * `next/image` rejects a hostname missing from `next.config.mjs` remotePatterns
 * with a hard error instead of degrading.
 */
const DivisionIcon = ({
  division,
  tournamentGrid,
  width = 36,
  height = 36,
  className
}: DivisionIconProps) => {
  const workspaceGrid = useDivisionGrid();
  const preferredGrid = tournamentGrid ?? workspaceGrid;
  const src = getDivisionIconSrc(preferredGrid, division);
  const name = getDivisionLabel(preferredGrid, division);

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src ?? ""}
      alt={name ?? `Division ${division}`}
      width={width}
      height={height}
      className={className}
      loading="lazy"
      decoding="async"
    />
  );
};

export default DivisionIcon;
