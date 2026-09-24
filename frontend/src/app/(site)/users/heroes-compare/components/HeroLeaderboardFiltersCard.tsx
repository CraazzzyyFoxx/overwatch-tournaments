"use client";

import { RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";

import SearchableImageSelect, {
  type SearchableImageOption,
} from "@/components/ui/searchable-image-select";

interface HeroLeaderboardFiltersCardProps {
  heroId: number | undefined;
  tournamentId: number | undefined;
  heroOptions: SearchableImageOption[];
  tournamentOptions: SearchableImageOption[];
  isLoadingHeroes: boolean;
  isErrorHeroes: boolean;
  isLoadingTournaments: boolean;
  isErrorTournaments: boolean;
  onHeroChange: (value: string | undefined) => void;
  onTournamentChange: (value: string | undefined) => void;
  onResetColumns: () => void;
  resetDisabled: boolean;
}

const TRIGGER =
  "border-[color:var(--aqt-border-2)] bg-[hsl(0_0%_100%/0.025)] text-[color:var(--aqt-fg)] hover:bg-[hsl(0_0%_100%/0.04)]";
const LABEL = "text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]";

const HeroLeaderboardFiltersCard = ({
  heroId,
  tournamentId,
  heroOptions,
  tournamentOptions,
  isLoadingHeroes,
  isErrorHeroes,
  isLoadingTournaments,
  isErrorTournaments,
  onHeroChange,
  onTournamentChange,
  onResetColumns,
  resetDisabled,
}: HeroLeaderboardFiltersCardProps) => {
  const t = useTranslations();

  return (
    <section className="grid items-end gap-3.5 rounded-[var(--aqt-radius)] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-5 py-[18px] sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto]">
      <div className="flex min-w-0 flex-col gap-2">
        <span className={LABEL}>{t("users.heroesCompare.filters.heroLabel")}</span>
        <SearchableImageSelect
          value={heroId !== undefined ? String(heroId) : undefined}
          onValueChange={(v) => onHeroChange(v || undefined)}
          options={heroOptions}
          placeholder={t("users.heroesCompare.filters.selectHero")}
          searchPlaceholder={t("users.heroesCompare.filters.searchHeroes")}
          isLoading={isLoadingHeroes}
          disabled={isLoadingHeroes || isErrorHeroes}
          triggerClassName={TRIGGER}
        />
      </div>

      <div className="flex min-w-0 flex-col gap-2">
        <span className={LABEL}>{t("users.heroesCompare.filters.tournamentScope")}</span>
        <SearchableImageSelect
          value={tournamentId !== undefined ? String(tournamentId) : undefined}
          onValueChange={(v) => onTournamentChange(v || undefined)}
          options={tournamentOptions}
          placeholder={t("users.heroesCompare.allTournaments")}
          searchPlaceholder={t("users.heroesCompare.filters.searchTournaments")}
          isLoading={isLoadingTournaments}
          disabled={isLoadingTournaments || isErrorTournaments}
          triggerClassName={TRIGGER}
        />
      </div>

      <button
        type="button"
        onClick={onResetColumns}
        disabled={resetDisabled}
        title={t("users.heroesCompare.filters.resetColumnsTitle")}
        className="inline-flex h-8 cursor-pointer items-center justify-center gap-2 rounded-[8px] border border-[color:var(--aqt-border-2)] bg-[hsl(0_0%_100%/0.025)] px-3 text-xs font-semibold text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:bg-[hsl(0_0%_100%/0.05)] hover:text-[color:var(--aqt-fg)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] disabled:pointer-events-none disabled:opacity-40"
      >
        <RotateCcw aria-hidden className="h-3.5 w-3.5" />
        {t("users.heroesCompare.filters.resetColumns")}
      </button>
    </section>
  );
};

export default HeroLeaderboardFiltersCard;
