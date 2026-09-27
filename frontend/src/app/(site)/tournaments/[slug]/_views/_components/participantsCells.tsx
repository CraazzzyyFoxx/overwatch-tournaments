"use client";

import { useMemo } from "react";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { normalizePlayerRole, playerRoleSlotCode, type PlayerRoleSlotCode } from "@/lib/roster/player-role";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { RegistrationRole } from "@/types/registration.types";
import type { Hero } from "@/types/hero.types";
import { HeroStrip } from "@/components/hero/HeroImage";
import { useTranslations } from "next-intl";
import { formatSubroleSlug } from "@/lib/roster/roles";
import { resolveDivisionFromRank, DEFAULT_DIVISION_GRID } from "@/lib/divisions/grid";
import type { DivisionGrid } from "@/types/workspace.types";
import DivisionIcon from "@/components/DivisionIcon";

import { getRoleLabel, ROLE_TO_ICON } from "./participantsColumns.model";

export function RolesCell({
  roles,
  grid,
  showRanks = false,
}: Readonly<{
  roles: RegistrationRole[];
  grid?: DivisionGrid | null;
  showRanks?: boolean;
}>) {
  const t = useTranslations();
  const resolvedGrid = grid || DEFAULT_DIVISION_GRID;
  if (!roles || roles.length === 0)
    return <span className="text-[color:var(--aqt-fg-dim)]">&mdash;</span>;

  return (
    <div className="flex flex-wrap items-start justify-center gap-x-0.5 gap-y-2">
      {roles.map((r) => {
        const roleLabel = getRoleLabel(r.role, t);
        const subroleLabel = r.subrole ? formatSubroleSlug(r.subrole) : null;
        const division = r.rank_value != null ? resolveDivisionFromRank(resolvedGrid, r.rank_value) : null;

        return (
          <div
            key={`${r.role}-${r.subrole ?? "base"}-${r.priority}`}
            className="inline-flex min-w-7 flex-col items-center gap-0.5"
            title={[
              roleLabel,
              subroleLabel,
              showRanks && r.rank_value ? `SR: ${r.rank_value}` : null,
              r.is_primary ? t("registration.roles.primary.title") : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          >
            <span
              className={cn(
                "relative inline-flex h-8 w-8 items-center justify-center p-1",
                r.is_primary
                  ? "after:absolute after:bottom-0 after:left-1/2 after:h-0.5 after:w-4 after:-translate-x-1/2 after:rounded-full after:bg-[color:var(--aqt-emerald)]"
                  : "text-[color:var(--aqt-fg-muted)]",
              )}
            >
              <PlayerRoleIcon
                role={ROLE_TO_ICON[r.role] ?? r.role}
                size={22}
              />
            </span>
            {subroleLabel ? (
              <span className="text-center text-label font-semibold leading-none tracking-label text-[color:var(--aqt-fg-dim)] uppercase">
                {subroleLabel}
              </span>
            ) : null}
            {showRanks && division != null ? (
              <DivisionIcon
                division={division}
                width={18}
                height={18}
                className="shrink-0 mt-0.5"
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function getCanonicalRole(hero: Hero): Exclude<PlayerRoleSlotCode, "flex"> {
  const slotCode = playerRoleSlotCode(normalizePlayerRole(hero.type || hero.role));
  return slotCode === "flex" ? "damage" : slotCode;
}

const ROLE_COLORS: Record<string, string> = {
  tank: "text-[color:var(--aqt-tank)]",
  damage: "text-[color:var(--aqt-damage)]",
  support: "text-[color:var(--aqt-support)]",
};

export function TopHeroesCell({
  roles,
  heroesMap,
}: Readonly<{
  roles: RegistrationRole[];
  /**
   * Hoisted by the caller. The cell must never query heroes itself: it renders
   * once per row, so a per-row query observer and map rebuild is exactly the
   * cost this prop removes.
   */
  heroesMap: Map<string, Hero>;
}>) {
  const sortedRoles = useMemo(() => {
    if (!roles) return [];
    return [...roles].sort((a, b) => {
      if (a.is_primary && !b.is_primary) return -1;
      if (!a.is_primary && b.is_primary) return 1;
      return a.priority - b.priority;
    });
  }, [roles]);

  const topHeroesList = useMemo(() => {
    const uniqueHeroSlugs = new Set<string>();
    const list: Hero[] = [];

    for (const r of sortedRoles) {
      if (r.top_heroes) {
        for (const slug of r.top_heroes) {
          if (!slug) continue;
          if (!uniqueHeroSlugs.has(slug)) {
            uniqueHeroSlugs.add(slug);
            const heroObj = heroesMap.get(slug);
            if (heroObj) {
              list.push(heroObj);
            } else {
              // Fallback
              list.push({
                name: slug,
                slug,
                image_path: "",
                role: r.role,
              } as any);
            }
          }
        }
      }
    }
    return list;
  }, [sortedRoles, heroesMap]);

  const heroesByRole = useMemo(() => {
    const groups: Record<Exclude<PlayerRoleSlotCode, "flex">, Hero[]> = {
      tank: [],
      damage: [],
      support: [],
    };

    for (const hero of topHeroesList) {
      const canonical = getCanonicalRole(hero);
      groups[canonical].push(hero);
    }

    return groups;
  }, [topHeroesList]);

  const activeRoles = useMemo(() => {
    return (["tank", "damage", "support"] as const).filter(
      (role) => heroesByRole[role].length > 0
    );
  }, [heroesByRole]);

  if (topHeroesList.length === 0) {
    return <span className="text-[color:var(--aqt-fg-dim)]">&mdash;</span>;
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 justify-center">
      {activeRoles.map((role) => (
        <div
          key={role}
          className="flex items-center gap-1.5 rounded-full border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] py-0.5 pl-2 pr-1 shadow-sm"
        >
          <span className={cn("inline-flex shrink-0 items-center", ROLE_COLORS[role])}>
            <span className="sr-only">{role.toUpperCase()}</span>
            <PlayerRoleIcon role={ROLE_TO_ICON[role] || role} size={14} aria-hidden />
          </span>
          <HeroStrip
            heroes={heroesByRole[role]}
            size="sm"
          />
        </div>
      ))}
    </div>
  );
}

const MAX_VISIBLE_SMURF_TAGS = 3;

export function SmurfTagsCell({
  tags,
}: Readonly<{
  tags: string[] | null | undefined;
}>) {
  const t = useTranslations();
  const smurfTags = tags?.filter(Boolean) ?? [];

  if (smurfTags.length === 0) {
    return <span className="text-[color:var(--aqt-fg-dim)]">&mdash;</span>;
  }

  const visibleTags = smurfTags.slice(0, MAX_VISIBLE_SMURF_TAGS);
  const hiddenCount = smurfTags.length - visibleTags.length;

  return (
    <div className="flex max-w-[220px] flex-col items-start gap-1">
      {visibleTags.map((tag, index) => (
        <span
          key={`${tag}-${index}`}
          className="block max-w-full truncate text-xs leading-5 text-[color:var(--aqt-fg-muted)]"
          title={tag}
        >
          {tag}
        </span>
      ))}

      {hiddenCount > 0 ? (
        <Dialog>
          <DialogTrigger asChild>
            <button
              type="button"
              className="text-xs font-medium text-[color:var(--aqt-emerald)] outline-none transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
            >
              +{hiddenCount} {t("common.more")}
            </button>
          </DialogTrigger>
          <DialogContent className="border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] sm:max-w-md">
            <DialogHeader>
              <DialogTitle className="text-[color:var(--aqt-fg)]">{t("common.smurfBattleTags")}</DialogTitle>
              <DialogDescription className="text-[color:var(--aqt-fg-muted)]">
                {t("common.smurfDesc")}
              </DialogDescription>
            </DialogHeader>
            <ScrollArea className="max-h-[320px] pr-2">
              <div className="flex flex-col gap-2">
                {smurfTags.map((tag, index) => (
                  <div
                    key={`${tag}-${index}`}
                    className="rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] px-3 py-2 text-sm text-[color:var(--aqt-fg)]"
                  >
                    {tag}
                  </div>
                ))}
              </div>
            </ScrollArea>
          </DialogContent>
        </Dialog>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Date formatter
// ---------------------------------------------------------------------------

export function DateCell({ iso }: Readonly<{ iso: string | null }>) {
  const format = useFormatter();
  if (!iso) return <span className="text-[color:var(--aqt-fg-dim)]">&mdash;</span>;
  return (
    <span className="text-[color:var(--aqt-fg-muted)] tabular-nums text-xs">
      {format.dateTime(new Date(iso), { day: "2-digit", month: "short", year: "numeric" })}
    </span>
  );
}
