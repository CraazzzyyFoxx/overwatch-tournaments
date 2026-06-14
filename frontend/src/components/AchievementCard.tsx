import React from "react";

import Image from "next/image";
import Link from "next/link";
import { Ellipsis } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import { Achievement, AchievementRarity } from "@/types/achievement.types";
import {
  AchievementDescriptionLocale,
  getAchievementDescription,
  hasAchievementDetails
} from "@/components/AchievementCard.utils";

type AchievementCardProps = {
  achievement: Achievement | AchievementRarity;
  href?: string;
  descriptionLocale: AchievementDescriptionLocale;
  showDetails?: boolean;
};

const AchievementCard = ({
  achievement,
  href,
  descriptionLocale,
  showDetails = false
}: AchievementCardProps) => {
  const hasDetails =
    showDetails &&
    hasAchievementDetails(achievement) &&
    (achievement.tournaments_ids.length > 0 || achievement.matches.length > 0);
  const description = getAchievementDescription(achievement, descriptionLocale);

  return (
    <div className="relative aspect-square overflow-hidden rounded-xl border border-white/[0.07] transition-colors duration-200 group hover:border-white/[0.15]">
      <Image
        src={achievement.image_url ?? `/achievements/${achievement.slug}.webp`}
        alt={achievement.slug}
        fill={true}
        quality={100}
        sizes="(min-width: 1536px) 20vw, (min-width: 1280px) 25vw, (min-width: 1024px) 33vw, (min-width: 640px) 50vw, 100vw"
      />

      <div className="absolute inset-0 bg-gradient-to-b from-black/65 via-transparent to-black/60" />

      <div className="pointer-events-none absolute inset-0 z-[5] flex items-center justify-center bg-black/65 p-5 opacity-0 transition-opacity duration-200 group-hover:opacity-100">
        <p className="line-clamp-5 text-center text-sm leading-snug text-white/90">
          {description}
        </p>
      </div>

      <div className="absolute right-2 top-2 z-[10] rounded-full border border-white/[0.12] bg-black/55 px-2 py-0.5 text-[10px] tabular-nums text-white/80 backdrop-blur-sm">
        {(achievement.rarity * 100).toFixed(2)}%
      </div>

      <div className="absolute left-0 right-0 top-0 z-[10] px-3 pt-3">
        <div className="line-clamp-2 text-sm font-semibold leading-snug text-white drop-shadow-md">
          {achievement.name}
        </div>
      </div>

      <div className="absolute bottom-2 right-2 z-[10] rounded-full border border-white/[0.12] bg-black/55 px-2 py-0.5 text-[10px] tabular-nums text-white/80 backdrop-blur-sm">
        x{achievement.count ?? 0}
      </div>

      {href && <Link href={href} aria-label={achievement.name} className="absolute inset-0 z-[12]" />}

      {hasDetails && (
        <Dialog>
          <DialogTrigger asChild>
            <button
              type="button"
              aria-label={`Open details for ${achievement.name}`}
              className="absolute bottom-2 left-2 z-[15] inline-flex cursor-pointer items-center justify-center rounded-full border border-white/[0.12] bg-black/55 p-1.5 text-white/60 backdrop-blur-sm transition-colors hover:bg-black/75 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
            >
              <Ellipsis className="h-3.5 w-3.5 rotate-90" aria-hidden />
            </button>
          </DialogTrigger>
          <DialogContent className="gap-0 border-white/[0.07] p-5 sm:max-w-md">
            <DialogHeader className="mb-4">
              <DialogTitle className="mb-1.5 text-base font-semibold leading-snug text-white">
                {achievement.name}
              </DialogTitle>
              <DialogDescription className="text-sm leading-relaxed text-white/55">
                {description}
              </DialogDescription>
            </DialogHeader>

            <div className="flex flex-col gap-4">
              {achievement.tournaments_ids.length > 0 && (
                <div className="flex flex-col gap-2">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-white/35">
                    Received at
                  </div>
                  <ul className="flex flex-col gap-1.5">
                    {achievement.tournaments.map((tournament) => (
                      <li key={`${achievement.slug}-${tournament.id}`}>
                        <Link
                          href={`/tournaments/${tournament.id}`}
                          className="text-sm text-white/65 transition-colors hover:text-white"
                        >
                          {tournament.name}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {achievement.matches.length > 0 && (
                <div className="flex flex-col gap-2">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-white/35">
                    Matches
                  </div>
                  <ul className="flex flex-col gap-1.5">
                    {achievement.matches.map((match) => (
                      <li key={`${achievement.slug}-${match.id}`}>
                        <Link
                          href={`/matches/${match.id}`}
                          className="text-sm text-white/65 transition-colors hover:text-white"
                        >
                          {`${match.home_team?.name} - ${match.away_team?.name}`}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
};

export default AchievementCard;
