"use client";

import { type ReactNode, useMemo } from "react";
import { CheckCircle2, Crown, XCircle } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

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
import { normalizePlayerRole, playerRoleSlotCode, type PlayerRoleSlotCode } from "@/lib/player-role";
import { cn } from "@/lib/utils";
import type {
  Registration,
  RegistrationForm,
  RegistrationRole,
} from "@/types/registration.types";
import type { Hero } from "@/types/hero.types";
import heroService from "@/services/hero.service";
import { HeroStrip } from "@/components/hero/HeroImage";

import {
  AdmissionStatusBadge,
  BalancerStatusBadge,
  CheckInStatusBadge,
  ProfileStatusBadge,
  SubscriptionStatusBadge,
  RegistrationStatusBadge,
} from "@/components/status/RegistrationBadges";
import TournamentHistoryCell from "./TournamentHistoryCell";
import { renderCustomFieldValue } from "@/components/registration/customFieldValue";
import { useTranslations } from "next-intl";
import { formatSubroleSlug } from "@/lib/roles";
import { resolveDivisionFromRank, DEFAULT_DIVISION_GRID } from "@/lib/division-grid";
import type { DivisionGrid } from "@/types/workspace.types";
import DivisionIcon from "@/components/DivisionIcon";
import { getPlayerSlug } from "@/utils/player";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Translator = ReturnType<typeof useTranslations<never>>;

export interface ColumnDefinition {
  id: string;
  label: string;
  category: "meta" | "built_in" | "custom";
  defaultVisible: boolean;
  render: (reg: Registration, index: number) => ReactNode;
  searchValue?: (reg: Registration) => string | null;
  /** Breakpoint at which column becomes visible. "always" = never hidden. */
  responsive?: "always" | "sm" | "md" | "lg";
  /** Optional fixed width class for the column. */
  widthClass?: string;
  /**
   * Content class driving the desktop grid track minimum. Every row is its own
   * grid, so tracks must be sized from a declared content class instead of
   * `min-content`, which would resolve differently per row and misalign the
   * columns. Omitted = `"data"`.
   */
  width?: "icon" | "badge" | "data";
  /** Optional alignment override for header and cells. */
  align?: "left" | "center";
}

// ---------------------------------------------------------------------------
// Role helpers — icon-only, larger icons
// ---------------------------------------------------------------------------

const ROLE_TO_ICON: Record<string, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support",
  flex: "Flex",
};

export function getRoleLabel(role: string, t: Translator): string {
  switch (role.toLowerCase()) {
    case "tank":
      return t("common.roles.tank");
    case "damage":
      return t("common.roles.damage");
    case "support":
      return t("common.roles.support");
    case "flex":
      return t("common.roles.flex");
    default:
      return role.charAt(0).toUpperCase() + role.slice(1);
  }
}

function RolesCell({
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

export function useHeroesMap({ enabled = true }: { enabled?: boolean } = {}): Map<string, Hero> {
  const { data: heroesData } = useQuery({
    queryKey: ["heroes-all"],
    queryFn: () => heroService.getAll({ perPage: -1 }),
    staleTime: 5 * 60_000,
    enabled,
  });

  return useMemo(() => {
    const map = new Map<string, Hero>();
    if (heroesData?.results) {
      for (const h of heroesData.results) {
        map.set(h.slug, h);
      }
    }
    return map;
  }, [heroesData]);
}

function TopHeroesCell({
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

function SmurfTagsCell({
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
// Stream POV cell
// ---------------------------------------------------------------------------

function StreamPovCell({ value }: Readonly<{ value: boolean | null | undefined }>) {
  const t = useTranslations();
  const label = value ? t("common.yes") : t("common.no");
  return (
    <span
      aria-label={label}
      className={cn(
        "inline-flex size-5 items-center justify-center",
        value ? "text-[color:var(--aqt-emerald)]" : "text-[color:var(--aqt-rose)]",
      )}
    >
      {value ? (
        <CheckCircle2 className="size-4" aria-hidden />
      ) : (
        <XCircle className="size-4" aria-hidden />
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Date formatter
// ---------------------------------------------------------------------------

function formatDate(iso: string | null, locale: string = "ru"): ReactNode {
  if (!iso) return <span className="text-[color:var(--aqt-fg-dim)]">&mdash;</span>;
  const d = new Date(iso);
  const formatLocale = locale.startsWith("ru") ? "ru-RU" : "en-GB";
  return (
    <span className="text-[color:var(--aqt-fg-muted)] tabular-nums text-xs">
      {d.toLocaleDateString(formatLocale, {
        day: "2-digit",
        month: "short",
        year: "numeric",
      })}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Built-in field mapping
// ---------------------------------------------------------------------------

const EMPTY_HEROES_MAP: Map<string, Hero> = new Map();

/** Per-table values the built-in cells need, hoisted out of the row render. */
interface BuiltInRenderContext {
  heroesMap: Map<string, Hero>;
  grid?: DivisionGrid | null;
  showRanks?: boolean;
}

interface BuiltInFieldDef {
  id: string;
  label: string;
  defaultVisible: boolean;
  responsive?: ColumnDefinition["responsive"];
  widthClass?: string;
  width?: ColumnDefinition["width"];
  align?: ColumnDefinition["align"];
  render: (reg: Registration, ctx: BuiltInRenderContext) => ReactNode;
  searchValue?: (reg: Registration) => string | null;
}

const BUILT_IN_FIELD_DEFS: Record<string, BuiltInFieldDef> = {
  battle_tag: {
    id: "battle_tag",
    label: "BattleTag",
    defaultVisible: true,
    responsive: "always",
    render: (reg) => (
      <span className="font-medium text-[color:var(--aqt-fg)]">
        {reg.battle_tag ? (
          <a
            href={`/users/${getPlayerSlug(reg.battle_tag)}`}
            target="_blank"
            rel="noopener noreferrer"
            className="transition hover:text-[color:var(--aqt-teal)] hover:underline"
          >
            {reg.battle_tag}
          </a>
        ) : (
          "\u2014"
        )}
      </span>
    ),
    searchValue: (reg) => reg.battle_tag,
  },
  smurf_tags: {
    id: "smurf_tags",
    label: "Smurfs",
    defaultVisible: true,
    responsive: "md",
    render: (reg) => <SmurfTagsCell tags={reg.smurf_tags_json} />,
    searchValue: (reg) => reg.smurf_tags_json?.join(" ") ?? null,
  },
  discord_nick: {
    id: "discord_nick",
    label: "Discord",
    defaultVisible: false,
    responsive: "sm",
    render: (reg) => (
      <span className="text-[color:var(--aqt-fg-muted)]">{reg.discord_nick ?? "\u2014"}</span>
    ),
    searchValue: (reg) => reg.discord_nick,
  },
  twitch_nick: {
    id: "twitch_nick",
    label: "Twitch",
    defaultVisible: false,
    responsive: "md",
    render: (reg) => (
      <span className="text-[color:var(--aqt-fg-muted)]">{reg.twitch_nick ?? "\u2014"}</span>
    ),
    searchValue: (reg) => reg.twitch_nick,
  },
  boosty_nick: {
    id: "boosty_nick",
    label: "Boosty",
    defaultVisible: false,
    responsive: "md",
    render: (reg) => (
      <span className="text-[color:var(--aqt-fg-muted)]">{reg.boosty_nick ?? "\u2014"}</span>
    ),
    searchValue: (reg) => reg.boosty_nick ?? null,
  },
  primary_role: {
    id: "roles",
    label: "Roles",
    defaultVisible: true,
    responsive: "always",
    align: "center",
    width: "badge",
    render: (reg, ctx) => <RolesCell roles={reg.roles} grid={ctx.grid} showRanks={ctx.showRanks} />,
    searchValue: (reg) =>
      reg.roles?.map((r) => r.role).join(" ") ?? null,
  },
  top_heroes: {
    id: "top_heroes",
    label: "Top Heroes",
    defaultVisible: true,
    responsive: "sm",
    align: "center",
    render: (reg, ctx) => <TopHeroesCell roles={reg.roles} heroesMap={ctx.heroesMap} />,
    searchValue: (reg) =>
      reg.roles?.flatMap((r) => r.top_heroes).join(" ") ?? null,
  },
  stream_pov: {
    id: "stream_pov",
    label: "Stream POV",
    defaultVisible: false,
    responsive: "lg",
    align: "center",
    width: "badge",
    render: (reg) => <StreamPovCell value={reg.stream_pov} />,
  },
  notes: {
    id: "notes",
    label: "Notes",
    defaultVisible: true,
    responsive: "md",
    widthClass: "max-w-50",
    render: (reg) =>
      reg.notes ? (
        <span
          className="line-clamp-3 max-w-50 wrap-break-word text-xs text-[color:var(--aqt-fg-muted)]"
          title={reg.notes}
        >
          {reg.notes}
        </span>
      ) : (
        <span className="text-[color:var(--aqt-fg-dim)]">&mdash;</span>
      ),
    searchValue: (reg) => reg.notes,
  },
};

// ---------------------------------------------------------------------------
// Main builder
// ---------------------------------------------------------------------------

export function buildParticipantColumns(
  form: RegistrationForm | null,
  t: Translator,
  locale: string = "ru",
  grid?: DivisionGrid | null,
  heroesMap?: Map<string, Hero>,
  /** Whether the loaded roster actually carries teams. Drives the team column's
   *  `defaultVisible`; there is no team flag on `RegistrationForm`, so the data
   *  itself is the only per-tournament signal available. */
  hasTeams: boolean = false,
): ColumnDefinition[] {
  const columns: ColumnDefinition[] = [];

  const renderContext: BuiltInRenderContext = {
    heroesMap: heroesMap ?? EMPTY_HEROES_MAP,
    grid,
    showRanks: form?.show_ranks,
  };

  const getLocalizedLabel = (key: string, fallback: string): string => {
    switch (key) {
      case "battle_tag":
        return t("registration.accounts.battleTag");
      case "smurf_tags":
        return t("registration.accounts.smurfs");
      case "discord_nick":
        return t("registration.accounts.discord");
      case "twitch_nick":
        return t("registration.accounts.twitch");
      case "boosty_nick":
        return t("registration.accounts.boosty");
      case "primary_role":
      case "roles":
        return t("common.rolesList");
      case "top_heroes":
        return t("tournamentDetail.topHeroes");
      case "stream_pov":
        return t("registration.details.streamPov");
      case "notes":
        return t("registration.details.notes");
      default:
        return fallback;
    }
  };

  // Meta: row number
  columns.push({
    id: "_index",
    label: "#",
    category: "meta",
    defaultVisible: false,
    responsive: "always",
    width: "icon",
    render: (_reg, index) => (
      <span className="text-[color:var(--aqt-fg-dim)] tabular-nums">{index + 1}</span>
    ),
  });

  // Meta: registered team. On by default ONLY when the roster actually carries
  // teams: on a solo tournament every cell is empty, and a permanently blank
  // column must not eat a grid track nor sit in the "Reset to defaults" set.
  // A hardcoded `false` is equally wrong — search walks VISIBLE columns only,
  // so it would kill find-players-by-team, which is the point of the column.
  const teamCaptainLabel = t("registrationTeams.member.captain");
  const teamSubstituteLabel = t("registrationTeams.member.substitute");
  columns.push({
    id: "team",
    label: t("registrationTeams.myCard.teamLabel"),
    category: "meta",
    defaultVisible: hasTeams,
    responsive: "sm",
    width: "badge",
    render: (reg) =>
      reg.team ? (
        <span className="inline-flex max-w-[200px] items-center gap-1.5">
          <span className="truncate font-medium text-[color:var(--aqt-fg)]" title={reg.team.name}>
            {reg.team.name}
          </span>
          {reg.team.is_captain ? (
            <span
              className="inline-flex shrink-0 items-center text-[color:var(--aqt-amber)]"
              title={teamCaptainLabel}
            >
              <Crown className="size-3.5" aria-hidden />
              <span className="sr-only">{teamCaptainLabel}</span>
            </span>
          ) : null}
          {reg.team.is_substitute ? (
            <span className="shrink-0 rounded border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] px-1 py-px text-label font-semibold leading-4 text-[color:var(--aqt-fg-dim)]">
              {teamSubstituteLabel}
            </span>
          ) : null}
        </span>
      ) : null,
    searchValue: (reg) => reg.team?.name ?? null,
  });

  // Built-in fields in a fixed canonical order: identity first, then gameplay
  // (roles, heroes), then accounts and extras. The form's JSON key order is
  // organizer input and must never drive the table layout.
  const BUILT_IN_KEY_ORDER = [
    "battle_tag",
    "primary_role",
    "top_heroes",
    "smurf_tags",
    "discord_nick",
    "twitch_nick",
    "boosty_nick",
    "stream_pov",
    "notes",
  ] as const;
  const enabledBuiltInKeys = form?.built_in_fields
    ? BUILT_IN_KEY_ORDER.filter((key) => form.built_in_fields[key]?.enabled)
    : // Fallback when no form config
      (["battle_tag", "primary_role", "top_heroes", "smurf_tags", "notes"] as const);

  for (const key of enabledBuiltInKeys) {
    const def = BUILT_IN_FIELD_DEFS[key];
    if (!def) continue;
    columns.push({
      id: def.id,
      label: getLocalizedLabel(key, def.label),
      category: "built_in",
      defaultVisible: form?.built_in_fields ? def.defaultVisible : true,
      responsive: def.responsive ?? "sm",
      widthClass: def.widthClass,
      width: def.width,
      align: def.align,
      render: (reg) => def.render(reg, renderContext),
      searchValue: def.searchValue,
    });
  }

  if (!columns.some((column) => column.id === "battle_tag")) {
    const identity = BUILT_IN_FIELD_DEFS.battle_tag;
    columns.splice(1, 0, {
      id: identity.id,
      label: getLocalizedLabel("battle_tag", identity.label),
      category: "built_in",
      defaultVisible: true,
      responsive: "always",
      render: (reg) => identity.render(reg, renderContext),
      searchValue: identity.searchValue,
    });
  }

  // Notes may hold data even when the form field is disabled (e.g. a Google
  // Sheets sync maps a notes column), so the roster always offers it.
  if (!columns.some((column) => column.id === "notes")) {
    const notesDef = BUILT_IN_FIELD_DEFS.notes;
    columns.push({
      id: notesDef.id,
      label: getLocalizedLabel("notes", notesDef.label),
      category: "built_in",
      defaultVisible: notesDef.defaultVisible,
      responsive: notesDef.responsive ?? "sm",
      widthClass: notesDef.widthClass,
      align: notesDef.align,
      render: (reg) => notesDef.render(reg, renderContext),
      searchValue: notesDef.searchValue,
    });
  }

  // Custom fields from form config
  if (form?.custom_fields) {
    for (const field of form.custom_fields) {
      columns.push({
        id: `custom_${field.key}`,
        label: field.label,
        category: "custom",
        defaultVisible: false,
        responsive: "md",
        render: (reg) =>
          renderCustomFieldValue(field, reg.custom_fields_json?.[field.key] ?? null, {
            yes: t("common.yes"),
            no: t("common.no"),
          }),
        searchValue:
          field.type === "text" || field.type === "select"
            ? (reg) => {
                const v = reg.custom_fields_json?.[field.key];
                return v != null ? String(v) : null;
              }
            : undefined,
      });
    }
  }

  // Meta: tournament history
  columns.push({
    id: "_history",
    label: t("common.history"),
    category: "meta",
    defaultVisible: true,
    responsive: "md",
    align: "center",
    width: "icon",
    render: (reg) => (
      <TournamentHistoryCell
        history={reg.tournament_history ?? []}
        count={reg.tournament_history_count}
      />
    ),
  });

  // Meta: registration date
  columns.push({
    id: "_submitted_at",
    label: t("common.registered"),
    category: "meta",
    defaultVisible: false,
    responsive: "md",
    render: (reg) => formatDate(reg.submitted_at, locale),
  });

  // Meta: registration status
  columns.push({
    id: "_status",
    label: t("common.status"),
    category: "meta",
    defaultVisible: true,
    responsive: "always",
    align: "center",
    width: "badge",
    render: (reg) => <RegistrationStatusBadge status={reg.status} meta={reg.status_meta} />,
  });

  // Meta: balancer status
  columns.push({
    id: "_balancer_status",
    label: t("common.balancer"),
    category: "meta",
    defaultVisible: true,
    responsive: "md",
    align: "center",
    width: "badge",
    render: (reg) => <BalancerStatusBadge status={reg.balancer_status} meta={reg.balancer_status_meta} />,
  });

  // Meta: check-in status
  columns.push({
    id: "_check_in",
    label: t("common.checkIn"),
    category: "meta",
    defaultVisible: true,
    responsive: "md",
    align: "center",
    width: "icon",
    render: (reg) => <CheckInStatusBadge checkedIn={reg.checked_in} />,
  });

  // Meta: profile open/closed — only when the tournament requires it.
  if (form?.require_open_profile) {
    columns.push({
      id: "_profile",
      label: t("common.profile"),
      category: "meta",
      defaultVisible: true,
      responsive: "always",
      align: "center",
      width: "icon",
      render: (reg) => <ProfileStatusBadge profilesOpen={reg.profiles_open} />,
    });
  }

  // Meta: subscription — only when the tournament requires it. ONE column with
  // the COMPOSED outcome, not one per provider: under `any` mode a red provider
  // cell beside a green one reads as a failure when it is not.
  if (form?.require_subscription) {
    columns.push({
      id: "_subscription",
      label: t("common.subscriptionColumn"),
      category: "meta",
      defaultVisible: true,
      responsive: "always",
      align: "center",
      width: "icon",
      render: (reg) => <SubscriptionStatusBadge outcome={reg.subscription_outcome} />,
    });
  }

  // Meta: admission composite — always last (rightmost)
  columns.push({
    id: "_admission",
    label: t("common.admission"),
    category: "meta",
    defaultVisible: true,
    responsive: "always",
    align: "center",
    width: "icon",
    render: (reg) => <AdmissionStatusBadge admission={reg.admission} />,
  });

  return columns;
}

