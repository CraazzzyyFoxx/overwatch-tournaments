"use client";

import React from "react";
import Image from "next/image";
import { useTranslations } from "next-intl";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { MvpPill, mvpRank, ordinal, resolveMvpPlacement } from "@/components/match/cells";
import type { MatchWithUserStats } from "@/types/user.types";

/**
 * MVP-placement pill for a single map, with a hover tooltip showing the map
 * (image + name) and the map score. Requires a <TooltipProvider> ancestor —
 * wrap the row/list of pills in one. Renders nothing if the match has no
 * recorded placement (impact rank, falling back to legacy performance).
 * When the match is flagged as an overperformance, an additional badge
 * pill is rendered alongside the placement pill.
 */
export const MvpMatchPill = ({ match }: { match: MatchWithUserStats }) => {
  const t = useTranslations();
  const placement = resolveMvpPlacement(match);
  if (placement == null) return null;
  const map = match.map;

  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="cursor-default">
            <MvpPill rank={mvpRank(placement)} label={ordinal(placement)} />
          </span>
        </TooltipTrigger>
        <TooltipContent className="w-52 overflow-hidden p-0">
          {map?.image_path ? (
            <div className="relative h-24 w-full">
              <Image src={map.image_path} alt={map.name} fill sizes="208px" className="object-cover" />
            </div>
          ) : null}
          <div className="flex flex-col gap-0.5 px-3 py-2">
            {map?.name ? <span className="text-[13px] font-semibold">{map.name}</span> : null}
            <span className="aqt-mono text-[12px] opacity-90">
              Score: {match.score.home} – {match.score.away}
            </span>
          </div>
        </TooltipContent>
      </Tooltip>
      {match.overperformance_badge ? (
        <MvpPill rank="default" label={t("users.matches.overperformanceBadge")} />
      ) : null}
    </>
  );
};

export default MvpMatchPill;
