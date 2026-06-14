"use client";

import React from "react";
import Image from "next/image";

import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionIconSrc, getDivisionLabel } from "@/lib/division-grid";
import type { DivisionGridVersion } from "@/types/workspace.types";

export interface DivisionIconProps {
  division: number;
  tournamentGrid?: DivisionGridVersion | null;
  width?: number;
  height?: number;
  className?: string;
}

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

  return <Image src={src ?? ""} alt={name ?? `Division ${division}`} width={width} height={height} className={className} />;
};

export default DivisionIcon;
