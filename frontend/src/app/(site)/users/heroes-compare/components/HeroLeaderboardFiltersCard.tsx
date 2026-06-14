import { Sword } from "lucide-react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { TypographyH4 } from "@/components/ui/typography";
import SearchableImageSelect, {
  type SearchableImageOption,
} from "@/app/(site)/users/compare/components/SearchableImageSelect";
import GlassGlow from "@/app/(site)/users/compare/components/GlassGlow";

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
}

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
}: HeroLeaderboardFiltersCardProps) => (
  <Card className="relative overflow-hidden">
    <GlassGlow />
    <CardHeader className="relative pb-3">
      <div className="flex items-center gap-2">
        <Sword className="h-5 w-5" />
        <TypographyH4>Hero Performance Leaderboard</TypographyH4>
      </div>
      <p className="text-sm leading-relaxed text-muted-foreground">
        Compare player performance on a specific hero. Each column is independently ranked.
      </p>
    </CardHeader>
    <CardContent className="relative">
      <div className="grid gap-3 sm:grid-cols-2">
        <SearchableImageSelect
          value={heroId !== undefined ? String(heroId) : undefined}
          onValueChange={(v) => onHeroChange(v || undefined)}
          options={heroOptions}
          placeholder="Select hero"
          searchPlaceholder="Search heroes..."
          isLoading={isLoadingHeroes}
          disabled={isLoadingHeroes || isErrorHeroes}
        />
        <SearchableImageSelect
          value={tournamentId !== undefined ? String(tournamentId) : undefined}
          onValueChange={(v) => onTournamentChange(v || undefined)}
          options={tournamentOptions}
          placeholder="All tournaments"
          searchPlaceholder="Search tournaments..."
          isLoading={isLoadingTournaments}
          disabled={isLoadingTournaments || isErrorTournaments}
        />
      </div>
    </CardContent>
  </Card>
);

export default HeroLeaderboardFiltersCard;
