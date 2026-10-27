"use client";

import { useTranslations } from "next-intl";

import { ThresholdPopover } from "@/app/(site)/users/components/shared/ThresholdPopover";
import { TournamentCombobox } from "@/components/tournaments/TournamentCombobox";
import { SearchableImageSelect, type SearchableImageOption } from "@/components/ui/searchable-image-select";
import { GameFilterHint } from "@/components/workspace/GameFilterHint";

/** The sample floor's choices in the popover. */
const MIN_GAMES_OPTIONS = [1, 3, 5, 10, 20] as const;

/**
 * The floor until the reader picks one. An all-time per-10 average needs a few games to mean anything, but one
 * tournament gives a player only a handful, so a tournament's board keeps everyone.
 */
export const defaultMinGames = (tournamentId: number | undefined): number => (tournamentId === undefined ? 5 : 1);

/** `?min_games=`: one of the offered floors, else the scope's default. */
export const parseMinGames = (value: string | null, tournamentId: number | undefined): number => {
  const parsed = Number(value);
  return value && (MIN_GAMES_OPTIONS as readonly number[]).includes(parsed) ? parsed : defaultMinGames(tournamentId);
};

interface HeroLeaderboardControlsProps {
  /**
   * Under "all games" the page shows one game it picked itself (the last one played): the game's name, worn by a
   * chip that opens the site's game switcher. `null` when the switcher already names the game.
   */
  gameHint: string | null;
  /** The searchable picker: only for a roster too long for the rail, or when the rail's catalog failed to load. */
  showHeroPicker: boolean;
  heroId: number | undefined;
  heroOptions: SearchableImageOption[];
  isLoadingHeroes: boolean;
  isErrorHeroes: boolean;
  onHeroChange: (value: string | undefined) => void;
  tournamentId: number | undefined;
  tournaments: readonly { id: number; name: string }[];
  isLoadingTournaments: boolean;
  isErrorTournaments: boolean;
  onTournamentChange: (id: number | undefined) => void;
  minGames: number;
  onMinGamesChange: (value: number) => void;
}

/** The header's controls: which game (a hint), which hero (long rosters only), which tournament, who is ranked. */
const HeroLeaderboardControls = ({
  gameHint,
  showHeroPicker,
  heroId,
  heroOptions,
  isLoadingHeroes,
  isErrorHeroes,
  onHeroChange,
  tournamentId,
  tournaments,
  isLoadingTournaments,
  isErrorTournaments,
  onTournamentChange,
  minGames,
  onMinGamesChange,
}: HeroLeaderboardControlsProps) => {
  const t = useTranslations();

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center lg:justify-end">
      {gameHint ? (
        <GameFilterHint className="self-start sm:self-auto">
          {t("common.discipline.gameHint", { game: gameHint })}
        </GameFilterHint>
      ) : null}

      {showHeroPicker ? (
        <SearchableImageSelect
          value={heroId !== undefined ? String(heroId) : undefined}
          onValueChange={(v) => onHeroChange(v || undefined)}
          options={heroOptions}
          placeholder={t("users.heroesCompare.filters.selectHero")}
          searchPlaceholder={t("users.heroesCompare.filters.searchHeroes")}
          ariaLabel={t("users.heroesCompare.filters.heroLabel")}
          isLoading={isLoadingHeroes}
          disabled={isLoadingHeroes || isErrorHeroes}
          size="sm"
          triggerClassName="sm:w-56"
        />
      ) : null}

      <TournamentCombobox
        tournaments={tournaments}
        value={tournamentId}
        onValueChange={onTournamentChange}
        ariaLabel={t("users.heroesCompare.filters.tournamentScope")}
        isLoading={isLoadingTournaments}
        disabled={isLoadingTournaments || isErrorTournaments}
        size="sm"
        triggerClassName="sm:w-56"
      />

      <ThresholdPopover
        label={t("users.heroesCompare.filters.minGames")}
        hint={t("users.heroesCompare.filters.minGamesHint")}
        triggerLabel={t("users.heroesCompare.filters.minGamesValue", { value: String(minGames) })}
        value={minGames}
        options={MIN_GAMES_OPTIONS}
        onChange={onMinGamesChange}
        align="end"
      />
    </div>
  );
};

export default HeroLeaderboardControls;
