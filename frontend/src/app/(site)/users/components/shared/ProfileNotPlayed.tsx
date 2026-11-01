"use client";

import { useTranslations } from "next-intl";

import { HeroFrame } from "@/components/site/PageHero";
import { Button } from "@/components/ui/button";
import { useGameScope } from "@/hooks/useGameScope";
import { ALL_DISCIPLINES } from "@/lib/site/discipline-scope";
import { canonicalDisplay } from "@/lib/player";

/** The scope names a game the player never played (spec §6.6): say so and offer every game instead. */
export default function ProfileNotPlayed({ player, game }: Readonly<{ player: string; game: string }>) {
  const t = useTranslations("common.discipline");
  const scope = useGameScope({ pageClass: "multi" });
  return (
    <HeroFrame variant="profile">
      <div role="status" className="flex flex-col items-center gap-4 px-6 py-14 text-center">
        <p className="text-body text-[color:var(--aqt-fg-muted)]">
          {t("notPlayed", { player: canonicalDisplay(player).name, game })}
        </p>
        <Button type="button" variant="outline" onClick={() => scope.selectScope(ALL_DISCIPLINES)}>
          {t("showAll")}
        </Button>
      </div>
    </HeroFrame>
  );
}
