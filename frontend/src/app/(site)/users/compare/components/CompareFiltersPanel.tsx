"use client";

import { useMemo, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import { CompareScope } from "@/app/(site)/users/compare/types";
import { parseOptionalInt, getMapIconSrc } from "@/app/(site)/users/compare/utils";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { useRoleName } from "@/hooks/useRoleName";
import { registrationRoles, showsRoles, type RoleOntology } from "@/lib/roster/ontology";
import type { DivisionGridLike } from "@/lib/divisions/grid";
import { UserSearchCombobox } from "@/components/kit/ServerSearchCombobox";
import { SearchableImageSelect, type SearchableImageOption } from "@/components/ui/searchable-image-select";
import { DivisionRangePicker } from "@/components/DivisionRangePicker";
import { TournamentCombobox } from "@/components/tournaments/TournamentCombobox";
import type { CatalogEntityRead } from "@/types/catalog.types";
import { Tournament } from "@/types/tournament.types";

interface CompareFiltersPanelProps {
  subjectUserId?: number;
  targetUserId?: number;
  scope: CompareScope;
  /** A rated role code of the browsed game. */
  role?: string;
  ontology?: RoleOntology | null;
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
  /** The grid the backend reads div_min/div_max against. */
  divisionGrid: DivisionGridLike;
  heroes: CatalogEntityRead[];
  maps: CatalogEntityRead[];
  tournaments: Tournament[];
  isHeroesLoading: boolean;
  isHeroesError: boolean;
  isMapsLoading: boolean;
  isMapsError: boolean;
  isTournamentsLoading: boolean;
  isTournamentsError: boolean;
  updateParams: (updates: Record<string, string | number | undefined>) => void;
}

const FilterField = ({ label, children }: Readonly<{ label: string; children: ReactNode }>) => (
  <div className="flex min-w-0 flex-col gap-1.5">
    <span className="text-xs font-semibold text-[color:var(--aqt-fg-muted)]">{label}</span>
    {children}
  </div>
);

const CompareFiltersPanel = ({
  subjectUserId,
  targetUserId,
  scope,
  role,
  ontology,
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
  divisionGrid,
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
  const t = useTranslations();
  const nameOf = useRoleName();
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

  // The browsed game's own rated roles; the cohort never filters on the open slot.
  const roleOptions: SearchableImageOption[] = registrationRoles(ontology).map((node) => ({
    value: node.code,
    label: nameOf(node),
    icon: <PlayerRoleIcon role={{ dimension: node.dimension, role: node.code }} ontology={ontology} size={20} decorative />
  }));

  const isHeroScope = scope === "hero";

  return (
    <div className="space-y-4">
      {/* The matchup: who, against whom. */}
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-end">
        <FilterField label={t("users.compare.selectedUser")}>
          <UserSearchCombobox
            value={subjectUserId}
            selectedLabel={selectedSubjectName}
            labelLoading={subjectNameLoading}
            placeholder={t("users.compare.selectSubjectUser")}
            triggerAriaLabel={t("users.compare.selectedUser")}
            clearLabel={null}
            size="sm"
            onSelect={(user) => {
              if (user) updateParams({ user_id: user.id });
            }}
          />
        </FilterField>

        <span
          aria-hidden
          className="hidden h-8 items-center px-1 text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)] md:flex"
        >
          {t("common.vs")}
        </span>

        <FilterField label={t("users.compare.compareAgainst")}>
          <UserSearchCombobox
            value={targetUserId}
            selectedLabel={selectedTargetName}
            labelLoading={targetNameLoading}
            placeholder={t("users.compare.allPlayersAverage")}
            triggerAriaLabel={t("users.compare.compareAgainst")}
            clearLabel={t("users.compare.compareWithAllAvg")}
            size="sm"
            onSelect={(user) =>
              updateParams(
                user
                  ? { target_user_id: user.id, div_min: undefined, div_max: undefined }
                  : { target_user_id: undefined }
              )
            }
          />
        </FilterField>
      </div>

      <div className="border-t border-[color:var(--aqt-border)] pt-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {/* A one-role game has nothing to filter by. */}
          {showsRoles(ontology) ? (
            <FilterField label={t("users.compare.filters.roleFilter")}>
              <SearchableImageSelect
                value={role}
                onValueChange={(value) => updateParams({ role: value })}
                options={roleOptions}
                placeholder={t("users.compare.allRoles")}
                ariaLabel={t("users.compare.filters.roleFilter")}
                disabled={isTargetBaseline}
                size="sm"
              />
            </FilterField>
          ) : null}

          <FilterField label={t("users.compare.filters.divisions")}>
            <DivisionRangePicker
              grid={divisionGrid}
              min={divMin}
              max={divMax}
              onChange={(min, max) => updateParams({ div_min: min, div_max: max })}
              ariaLabel={t("users.compare.filters.divisions")}
              disabled={isTargetBaseline}
            />
          </FilterField>

          <FilterField label={t("common.tournament")}>
            <TournamentCombobox
              tournaments={tournaments}
              value={tournamentId}
              onValueChange={(id) => updateParams({ tournament_id: id })}
              ariaLabel={t("common.tournament")}
              isLoading={isTournamentsLoading}
              disabled={isTournamentsLoading || isTournamentsError}
              size="sm"
            />
          </FilterField>
        </div>

        {isTargetBaseline ? (
          <p className="mt-2 text-xs text-[color:var(--aqt-fg-dim)]">
            {t("users.compare.filters.cohortLockedHint")}
          </p>
        ) : null}

        {/* Hero & map, in the columns above: revealed with the scope; `inert` keeps the collapsed pickers out of
            the tab order. */}
        <div
          className="grid transition-[grid-template-rows] duration-300 ease-in-out motion-reduce:transition-none"
          style={{ gridTemplateRows: isHeroScope ? "1fr" : "0fr" }}
          inert={!isHeroScope}
        >
          <div className="overflow-hidden">
            <div className="grid gap-3 pt-3 pb-0.5 sm:grid-cols-2 lg:grid-cols-3">
              <FilterField label={t("users.compare.filters.primaryHero")}>
                <SearchableImageSelect
                  value={leftHeroId ? String(leftHeroId) : undefined}
                  onValueChange={(val) => {
                    const nextHeroId = val ? parseOptionalInt(val) : undefined;
                    updateParams({ left_hero_id: nextHeroId, right_hero_id: nextHeroId });
                  }}
                  options={heroOptions}
                  placeholder={t("users.compare.allHeroes")}
                  searchPlaceholder={t("users.compare.filters.searchHero")}
                  ariaLabel={t("users.compare.filters.primaryHero")}
                  isLoading={isHeroesLoading}
                  disabled={isHeroesLoading || isHeroesError}
                  size="sm"
                />
              </FilterField>

              <FilterField label={t("users.compare.filters.compareHero")}>
                <SearchableImageSelect
                  value={rightHeroId ? String(rightHeroId) : undefined}
                  onValueChange={(val) =>
                    updateParams({ right_hero_id: val ? parseOptionalInt(val) : undefined })
                  }
                  options={heroOptions}
                  placeholder={t("users.compare.allHeroes")}
                  searchPlaceholder={t("users.compare.filters.searchHero")}
                  ariaLabel={t("users.compare.filters.compareHero")}
                  isLoading={isHeroesLoading}
                  disabled={isHeroesLoading || isHeroesError}
                  size="sm"
                />
              </FilterField>

              <FilterField label={t("users.compare.filters.mapFilter")}>
                <SearchableImageSelect
                  value={mapId ? String(mapId) : undefined}
                  onValueChange={(val) =>
                    updateParams({ map_id: val ? parseOptionalInt(val) : undefined })
                  }
                  options={mapOptions}
                  placeholder={t("users.compare.filters.allMaps")}
                  searchPlaceholder={t("users.compare.filters.searchMap")}
                  ariaLabel={t("users.compare.filters.mapFilter")}
                  isLoading={isMapsLoading}
                  disabled={isMapsLoading || isMapsError}
                  size="sm"
                />
              </FilterField>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CompareFiltersPanel;
