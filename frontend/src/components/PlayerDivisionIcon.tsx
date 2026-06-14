import React from "react";

import DivisionIcon, { DivisionIconProps } from "@/components/DivisionIcon";

export type PlayerDivisionIconProps = DivisionIconProps;

const PlayerDivisionIcon = ({ division, width, height, className, tournamentGrid }: PlayerDivisionIconProps) => {
  return (
    <div className="flex justify-center">
      <DivisionIcon division={division} width={width} height={height} className={className} tournamentGrid={tournamentGrid} />
    </div>
  );
};

export default PlayerDivisionIcon;
