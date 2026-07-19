import React from "react";
import { MatchWithUserStats } from "@/types/user.types";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import Image from "next/image";

// English ordinal suffix: 1→1st, 2→2nd, 3→3rd, 11–13→th, etc. Placements can
// exceed 10 (full match roster), so the 11–13 exception matters. Was `{n}th`,
// which rendered "1th"/"2th"/"3th".
function ordinalPlacement(n: number | undefined | null): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const v = Math.abs(n) % 100;
  const suffix = v >= 11 && v <= 13 ? "th" : (["th", "st", "nd", "rd"][n % 10] ?? "th");
  return `${n}${suffix}`;
}

export const PerformanceBadgeWithTooltip = ({ match }: { match: MatchWithUserStats }) => {
  const mapImagePath: string = match.map ? match.map?.image_path : "";
  let bgColor = "bg-placeBg";
  let color = "text-placeText";
  if (match.performance == 1) {
    bgColor = "bg-firstPlaceBg";
    color = "text-TopPlaceText";
  }
  if (match.performance == 2) {
    bgColor = "bg-secondPlaceBg";
    color = "text-TopPlaceText";
  }
  if (match.performance == 3) {
    bgColor = "bg-thirdPlaceBg";
  }

  return (
    <Tooltip>
      <TooltipTrigger>
        <div
          className={`inline-flex items-center rounded-xl border px-2.5 py-0.5 text-xs font-semibold cursor-pointer ${bgColor} ${color}`}
        >
          <span>{ordinalPlacement(match.performance)}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent className="flex flex-col px-0 py-0 bg-background">
        <Image src={mapImagePath} alt="Map" height={100} width={200} />
        <div className="flex flex-col items-center gap-1 my-2">
          <h3 className="scroll-m-20 text-xl font-semibold tracking-tight text-white max-w-44 break-words text-center">
            {match.map?.name}
          </h3>
          <h3 className="scroll-m-20 text-xl font-semibold tracking-tight text-white">
            Score: {match.score.home} - {match.score.away}
          </h3>
        </div>
      </TooltipContent>
    </Tooltip>
  );
};

export const PerformanceBadge = ({ performance }: { performance: number | undefined }) => {
  let bgColor = "bg-placeBg";
  let color = "text-placeText";
  if (performance == 1) {
    bgColor = "bg-firstPlaceBg";
    color = "text-TopPlaceText";
  }
  if (performance == 2) {
    bgColor = "bg-secondPlaceBg";
    color = "text-TopPlaceText";
  }
  if (performance == 3) {
    bgColor = "bg-thirdPlaceBg";
  }

  return (
    <div
      className={`inline-flex items-center rounded-xl border px-2.5 py-0.5 text-xs font-semibold ${bgColor} ${color}`}
    >
      <span>{ordinalPlacement(performance)}</span>
    </div>
  );
};
