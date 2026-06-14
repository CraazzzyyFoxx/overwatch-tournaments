"use client";

import { useMemo } from "react";
import Image from "next/image";

import { CompareScope } from "@/app/(site)/users/compare/types";
import { getDivisionOptions, ROLE_FILTER_OPTIONS } from "@/app/(site)/users/compare/constants";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { parseOptionalInt, getMapIconSrc } from "@/app/(site)/users/compare/utils";
import UserSearchCombobox from "@/app/(site)/users/compare/components/UserSearchCombobox";
import SearchableImageSelect, {
  type SearchableImageOption,
} from "@/app/(site)/users/compare/components/SearchableImageSelect";
import { Hero } from "@/types/hero.types";
import { MapRead } from "@/types/map.types";
import { Tournament } from "@/types/tournament.types";
import { UserRoleType } from "@/types/user.types";
import { CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

interface CompareFiltersPanelProps {
  subjectUserId?: number;
  targetUserId?: number;
  scope: CompareScope;
  role?: UserRoleType;
  divMin?: number;
  divMax?: number;
  tournamentId?: number;
  leftHeroId?: number;
  rightHeroId?: number;
  mapId?: number;
  isTargetBaseline: boolean;
  selectedSubjectName?: string;
  selectedTargetName?: string;
  subjectNameLoading?: boolean;
  targetNameLoading?: boolean;
  heroes: Hero[];
  maps: MapRead[];
  tournaments: Tournament[];
  isHeroesLoading: boolean;
  isHeroesError: boolean;
  isMapsLoading: boolean;
  isMapsError: boolean;
  isTournamentsLoading: boolean;
  isTournamentsError: boolean;
  updateParams: (updates: Record<string, string | number | undefined>) => void;
}

const CompareFiltersPanel = ({
  subjectUserId,
  targetUserId,
  scope,
  role,
  divMin,
  divMax,
  tournamentId,
  leftHeroId,
  rightHeroId,
  mapId,
  isTargetBaseline,
  selectedSubjectName,
  selectedTargetName,
  subjectNameLoading = false,
  targetNameLoading = false,
  heroes,
  maps,
  tournaments,
  isHeroesLoading,
  isHeroesError,
  isMapsLoading,
  isMapsError,
  isTournamentsLoading,
  isTournamentsError,
  updateParams
}: CompareFiltersPanelProps) => {
  const grid = useDivisionGrid();
  const divisionOptions = getDivisionOptions(grid);
  const heroOptions: SearchableImageOption[] = useMemo(
    () =>
      heroes.map((hero) => ({
        value: String(hero.id),
        label: hero.name,
        imageSrc: hero.image_path,
      })),
    [heroes]
  );

  const mapOptions: SearchableImageOption[] = useMemo(
    () =>
      maps.map((map) => ({
        value: String(map.id),
        label: map.name,
        imageSrc: getMapIconSrc(map),
      })),
    [maps]
  );

  const tournamentOptions: SearchableImageOption[] = useMemo(
    () =>
      tournaments.map((t) => ({
        value: String(t.id),
        label: t.name,
        imageSrc: null,
      })),
    [tournaments]
  );

  const isHeroScope = scope === "hero";

  return (
    <CardContent className="relative space-y-0">
      {/* ── Row 1: Players ── */}
      <div className="space-y-2">
        <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Players
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1">
            <div className="text-xs font-semibold text-muted-foreground">Selected user</div>
            <UserSearchCombobox
              value={subjectUserId}
              selectedName={selectedSubjectName}
              isLabelLoading={subjectNameLoading}
              placeholder="Select subject user"
              allowClear={false}
              onSelect={(nextUserId) => {
                if (typeof nextUserId === "number" && nextUserId > 0) {
                  updateParams({ user_id: nextUserId });
                }
              }}
            />
          </div>

          <div className="space-y-1">
            <div className="text-xs font-semibold text-muted-foreground">Compare against</div>
            <UserSearchCombobox
              value={targetUserId}
              selectedName={selectedTargetName}
              isLabelLoading={targetNameLoading}
              placeholder="All players average"
              onSelect={(nextUserId) => {
                if (typeof nextUserId === "number" && nextUserId > 0) {
                  updateParams({
                    target_user_id: nextUserId,
                    div_min: undefined,
                    div_max: undefined
                  });
                  return;
                }

                updateParams({ target_user_id: undefined });
              }}
            />
          </div>
        </div>
      </div>

      {/* ── Separator ── */}
      <div className="border-t border-border/40 my-4" />

      {/* ── Row 2: Filters ── */}
      <div className="space-y-2">
        <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Filters
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <div className="space-y-1">
            <div className="text-xs font-semibold text-muted-foreground">Compare scope</div>
            <Select value={scope} onValueChange={(value) => updateParams({ scope: value as CompareScope })}>
              <SelectTrigger className="liquid-glass-panel">
                <SelectValue placeholder="Scope" />
              </SelectTrigger>
              <SelectContent className="liquid-glass-panel">
                <SelectItem value="overall">Overall performance</SelectItem>
                <SelectItem value="hero">Hero / map performance</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <div className="text-xs font-semibold text-muted-foreground">Role filter</div>
            <Select
              value={role ?? "all"}
              disabled={isTargetBaseline}
              onValueChange={(value) => updateParams({ role: value === "all" ? undefined : value })}
            >
              <SelectTrigger className="liquid-glass-panel">
                <div className="flex items-center gap-2">
                  {role ? (
                    <Image
                      src={`/roles/${role}.png`}
                      alt={`${role} icon`}
                      width={22}
                      height={22}
                      className="h-5.5 w-5.5"
                    />
                  ) : null}
                  <span className="truncate">{role ?? "All roles"}</span>
                </div>
              </SelectTrigger>
              <SelectContent className="liquid-glass-panel">
                {ROLE_FILTER_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    <div className="flex items-center gap-2">
                      {option.value === "all" ? null : (
                        <Image
                          src={`/roles/${option.value}.png`}
                          alt={`${option.label} icon`}
                          width={20}
                          height={20}
                          className="h-5 w-5"
                        />
                      )}
                      <span>{option.label}</span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <div className="text-xs font-semibold text-muted-foreground">Division min</div>
            <Select
              value={divMin ? String(divMin) : "all"}
              disabled={isTargetBaseline}
              onValueChange={(value) =>
                updateParams({ div_min: value === "all" ? undefined : parseOptionalInt(value) })
              }
            >
              <SelectTrigger className="liquid-glass-panel">
                <div className="flex items-center gap-2">
                  {divMin ? (
                    <Image
                      src={`/divisions/${divMin}.png`}
                      alt={`Division ${divMin}`}
                      width={22}
                      height={22}
                      className="h-5.5 w-5.5"
                    />
                  ) : null}
                  <span className="truncate">{divMin ? `Division ${divMin}` : "Any"}</span>
                </div>
              </SelectTrigger>
              <SelectContent className="liquid-glass-panel">
                <SelectItem value="all">Any</SelectItem>
                {divisionOptions.map((division) => (
                  <SelectItem key={`min-${division}`} value={String(division)}>
                    <div className="flex items-center gap-2">
                      <Image
                        src={`/divisions/${division}.png`}
                        alt={`Division ${division}`}
                        width={20}
                        height={20}
                        className="h-5 w-5"
                      />
                      <span>Division {division}</span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <div className="text-xs font-semibold text-muted-foreground">Division max</div>
            <Select
              value={divMax ? String(divMax) : "all"}
              disabled={isTargetBaseline}
              onValueChange={(value) =>
                updateParams({ div_max: value === "all" ? undefined : parseOptionalInt(value) })
              }
            >
              <SelectTrigger className="liquid-glass-panel">
                <div className="flex items-center gap-2">
                  {divMax ? (
                    <Image
                      src={`/divisions/${divMax}.png`}
                      alt={`Division ${divMax}`}
                      width={22}
                      height={22}
                      className="h-5.5 w-5.5"
                    />
                  ) : null}
                  <span className="truncate">{divMax ? `Division ${divMax}` : "Any"}</span>
                </div>
              </SelectTrigger>
              <SelectContent className="liquid-glass-panel">
                <SelectItem value="all">Any</SelectItem>
                {divisionOptions.map((division) => (
                  <SelectItem key={`max-${division}`} value={String(division)}>
                    <div className="flex items-center gap-2">
                      <Image
                        src={`/divisions/${division}.png`}
                        alt={`Division ${division}`}
                        width={20}
                        height={20}
                        className="h-5 w-5"
                      />
                      <span>Division {division}</span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <div className="text-xs font-semibold text-muted-foreground">Tournament</div>
            <SearchableImageSelect
              value={tournamentId ? String(tournamentId) : undefined}
              onValueChange={(val) =>
                updateParams({ tournament_id: val ? parseOptionalInt(val) : undefined })
              }
              options={tournamentOptions}
              placeholder="All tournaments"
              searchPlaceholder="Search tournament..."
              isLoading={isTournamentsLoading}
              disabled={isTournamentsLoading || isTournamentsError}
            />
          </div>
        </div>
      </div>

      {/* ── Row 3: Hero & Map (animated reveal) ── */}
      <div
        className="grid transition-[grid-template-rows] duration-300 ease-in-out"
        style={{ gridTemplateRows: isHeroScope ? "1fr" : "0fr" }}
      >
        <div className="overflow-hidden">
          <div className="border-t border-border/40 mt-4 mb-4" />

          <div className="space-y-2 pb-0.5">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Hero & Map
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="space-y-1">
                <div className="text-xs font-semibold text-muted-foreground">Primary hero</div>
                <SearchableImageSelect
                  value={leftHeroId ? String(leftHeroId) : undefined}
                  onValueChange={(val) => {
                    const nextHeroId = val ? parseOptionalInt(val) : undefined;
                    updateParams({ left_hero_id: nextHeroId, right_hero_id: nextHeroId });
                  }}
                  options={heroOptions}
                  placeholder="All heroes"
                  searchPlaceholder="Search hero..."
                  isLoading={isHeroesLoading}
                  disabled={isHeroesLoading || isHeroesError}
                />
              </div>

              <div className="space-y-1">
                <div className="text-xs font-semibold text-muted-foreground">Compare hero</div>
                <SearchableImageSelect
                  value={rightHeroId ? String(rightHeroId) : undefined}
                  onValueChange={(val) =>
                    updateParams({ right_hero_id: val ? parseOptionalInt(val) : undefined })
                  }
                  options={heroOptions}
                  placeholder="All heroes"
                  searchPlaceholder="Search hero..."
                  isLoading={isHeroesLoading}
                  disabled={isHeroesLoading || isHeroesError}
                />
              </div>

              <div className="space-y-1">
                <div className="text-xs font-semibold text-muted-foreground">Map filter</div>
                <SearchableImageSelect
                  value={mapId ? String(mapId) : undefined}
                  onValueChange={(val) =>
                    updateParams({ map_id: val ? parseOptionalInt(val) : undefined })
                  }
                  options={mapOptions}
                  placeholder="All maps"
                  searchPlaceholder="Search map..."
                  isLoading={isMapsLoading}
                  disabled={isMapsLoading || isMapsError}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </CardContent>
  );
};

export default CompareFiltersPanel;
