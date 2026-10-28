"use client";

import { roleOf, subRoleSlugOf } from "@/lib/roster/role-ref";
import { useMemo } from "react";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Eyebrow } from "@/components/ui/eyebrow";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { useFormatter } from "@/lib/datetime/client";
import { findRole, rolePresentation, type RoleOntology } from "@/lib/roster/ontology";
import { cn } from "@/lib/utils";
import type { RegistrationRole } from "@/types/registration.types";
import type { CatalogEntityChip } from "@/types/catalog.types";
import { CatalogEntityStrip } from "@/components/catalog/CatalogEntityImage";
import { useTranslations } from "next-intl";
import { formatSubroleSlug } from "@/lib/roster/roles";
import { resolveDivisionFromRank } from "@/lib/divisions/grid";
import type { DivisionGrid } from "@/types/workspace.types";
import DivisionIcon from "@/components/DivisionIcon";

export function RolesCell({
  roles,
  ontology,
  grid,
  discipline,
  showRanks = false,
}: Readonly<{
  roles: RegistrationRole[];
  /** The owner game's scoped ontology; `null` while it loads (roles then render neutral, never another game's). */
  ontology: RoleOntology | null;
  /** The owner game's grid. No grid, no crest: another game's artwork is never borrowed. */
  grid?: DivisionGrid | null;
  discipline?: string;
  showRanks?: boolean;
}>) {
  const t = useTranslations();
  const roleLabel = useSlotLabel(ontology);
  if (!roles || roles.length === 0)
    return <span className="text-[color:var(--aqt-fg-dim)]">&mdash;</span>;

  return (
    <div className="flex flex-wrap items-start justify-center gap-x-0.5 gap-y-2">
      {roles.map((r) => {
        const label = roleLabel(roleOf(r.role));
        const subrole = ontology ? findRole(ontology, r.role) : null;
        const subroleLabel = subRoleSlugOf(r.role)
          ? (subrole?.parent_id != null ? subrole.name : formatSubroleSlug(subRoleSlugOf(r.role)!))
          : null;
        const division =
          grid && r.rank_value != null ? resolveDivisionFromRank(grid, r.rank_value) : null;

        return (
          <div
            key={`${roleOf(r.role)}-${subRoleSlugOf(r.role) ?? "base"}-${r.priority}`}
            className="inline-flex min-w-7 flex-col items-center gap-0.5"
            title={[
              label,
              subroleLabel,
              showRanks && r.rank_value ? String(r.rank_value) : null,
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
              <PlayerRoleIcon role={r.role} ontology={ontology} size={22} />
            </span>
            {subroleLabel ? (
              <Eyebrow tone="dim" className="text-center leading-none">
                {subroleLabel}
              </Eyebrow>
            ) : null}
            {showRanks && division != null ? (
              <DivisionIcon
                division={division}
                tournamentGrid={grid}
                discipline={discipline}
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

/**
 * A registrant's top characters, grouped by the role each pick was DECLARED under. The group's glyph is
 * that declared role's own presentation: a character's class is never read as a role, so a support-class
 * pick under a damage role stays in the damage group.
 */
export function TopHeroesCell({
  roles,
  heroesMap,
  ontology,
}: Readonly<{
  roles: RegistrationRole[];
  /**
   * Hoisted by the caller. The cell must never query heroes itself: it renders
   * once per row, so a per-row query observer and map rebuild is exactly the
   * cost this prop removes.
   */
  heroesMap: Map<string, CatalogEntityChip>;
  ontology: RoleOntology | null;
}>) {
  const roleLabel = useSlotLabel(ontology);
  const groups = useMemo(() => {
    if (!roles) return [];
    return [...roles]
      .sort((a, b) => {
        if (a.is_primary && !b.is_primary) return -1;
        if (!a.is_primary && b.is_primary) return 1;
        return a.priority - b.priority;
      })
      .map((role) => ({
        role,
        heroes: (role.top_characters ?? [])
          .filter(Boolean)
          .map(
            (slug): CatalogEntityChip =>
              heroesMap.get(slug) ?? { name: slug, slug, image_path: null, attrs: {} },
          ),
      }))
      .filter((group) => group.heroes.length > 0);
  }, [roles, heroesMap]);

  if (groups.length === 0) {
    return <span className="text-[color:var(--aqt-fg-dim)]">&mdash;</span>;
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 justify-center">
      {groups.map(({ role, heroes }) => {
        const node = ontology ? findRole(ontology, role.role) : null;
        const color = ontology && node ? rolePresentation(ontology.roles, node.id).color : null;
        return (
          <div
            key={`${roleOf(role.role)}-${subRoleSlugOf(role.role) ?? "base"}-${role.priority}`}
            className="flex items-center gap-1.5 rounded-full border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] py-0.5 pl-2 pr-1 shadow-sm"
          >
            <span
              className="inline-flex shrink-0 items-center"
              style={color ? { color } : undefined}
            >
              <span className="sr-only">{roleLabel(roleOf(role.role))}</span>
              <PlayerRoleIcon role={role.role} ontology={ontology} size={14} aria-hidden />
            </span>
            <CatalogEntityStrip entities={heroes} size="sm" />
          </div>
        );
      })}
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
            <Button type="button" variant="link" size="inline">
              +{hiddenCount} {t("common.more")}
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>{t("common.smurfBattleTags")}</DialogTitle>
              <DialogDescription>{t("common.smurfDesc")}</DialogDescription>
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
