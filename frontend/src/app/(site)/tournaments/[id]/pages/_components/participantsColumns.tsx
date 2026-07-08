"use client";

import { type ReactNode, useMemo } from "react";
import { CheckCircle2, ExternalLink, XCircle } from "lucide-react";
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
import { cn } from "@/lib/utils";
import type {
  CustomFieldDefinition,
  Registration,
  RegistrationForm,
  RegistrationRole,
} from "@/types/registration.types";
import type { Hero } from "@/types/hero.types";
import heroService from "@/services/hero.service";
import HeroImage, { HeroStrip } from "@/components/hero/HeroImage";

import {
  AdmissionStatusBadge,
  BalancerStatusBadge,
  CheckInStatusBadge,
  ProfileStatusBadge,
  RegistrationStatusBadge,
} from "@/components/status/RegistrationBadges";
import TournamentHistoryCell from "./TournamentHistoryCell";
import { useTranslations } from "next-intl";
import { formatSubroleSlug } from "@/lib/roles";
import { resolveDivisionFromRank, DEFAULT_DIVISION_GRID } from "@/lib/division-grid";
import type { DivisionGrid } from "@/types/workspace.types";
import DivisionIcon from "@/components/DivisionIcon";
import { getPlayerSlug } from "@/utils/player";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Translator = ReturnType<typeof useTranslations>;

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
  /** Optional alignment override for header and cells. */
  align?: "left" | "center";
}

// ---------------------------------------------------------------------------
// Role helpers — icon-only, larger icons
// ---------------------------------------------------------------------------

const ROLE_TO_ICON: Record<string, string> = {
  tank: "Tank",
  dps: "Damage",
  support: "Support",
};

function getRoleLabel(role: string, t: Translator): string {
  switch (role.toLowerCase()) {
    case "tank":
      return t("common.roles.tank");
    case "dps":
      return t("common.roles.dps");
    case "support":
      return t("common.roles.support");
    case "flex":
      return t("common.roles.flex");
    default:
      return role.charAt(0).toUpperCase() + role.slice(1);
  }
}

function getSubroleShortLabel(subrole: string, t: Translator): string {
  switch (subrole.toLowerCase()) {
    case "hitscan":
      return t("common.subrolesShort.hitscan");
    case "projectile":
      return t("common.subrolesShort.projectile");
    case "main_heal":
      return t("common.subrolesShort.main_heal");
    case "light_heal":
      return t("common.subrolesShort.light_heal");
    case "main_tank":
      return t("common.subrolesShort.main_tank");
    case "off_tank":
      return t("common.subrolesShort.off_tank");
    case "flanker":
      return t("common.subrolesShort.flanker");
    case "flex_dps":
      return t("common.subrolesShort.flex_dps");
    case "flex_support":
      return t("common.subrolesShort.flex_support");
    default:
      return subrole.toUpperCase();
  }
}

function RolesCell({
  roles,
  grid,
  showRanks = false,
}: {
  roles: RegistrationRole[];
  grid?: DivisionGrid | null;
  showRanks?: boolean;
}) {
  const t = useTranslations();
  const resolvedGrid = grid || DEFAULT_DIVISION_GRID;
  if (!roles || roles.length === 0)
    return <span className="text-white/30">&mdash;</span>;

  return (
    <div className="flex flex-wrap items-start justify-center gap-x-0.5 gap-y-2">
      {roles.map((r) => {
        const roleLabel = getRoleLabel(r.role, t);
        const subroleLabel = r.subrole ? formatSubroleSlug(r.subrole) : null;
        const subroleShortLabel = r.subrole ? getSubroleShortLabel(r.subrole, t) : null;
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
                  ? "after:absolute after:bottom-0 after:left-1/2 after:h-0.5 after:w-4 after:-translate-x-1/2 after:rounded-full after:bg-emerald-300/90"
                  : "text-white/70",
              )}
            >
              <PlayerRoleIcon
                role={ROLE_TO_ICON[r.role] ?? r.role}
                size={22}
              />
            </span>
            {subroleShortLabel ? (
              <span className="text-center text-[8px] font-semibold leading-none tracking-[0.12em] text-white/45 uppercase">
                {subroleShortLabel}
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

function getCanonicalRole(hero: Hero): "tank" | "dps" | "support" {
  const r = (hero.type || hero.role || "").toLowerCase();
  if (r === "tank") return "tank";
  if (r === "damage" || r === "dps") return "dps";
  if (r === "support") return "support";
  return "support"; // fallback
}

const ROLE_COLORS: Record<string, string> = {
  tank: "text-sky-400",
  dps: "text-orange-400",
  support: "text-emerald-400",
};

function TopHeroesCell({ roles }: { roles: RegistrationRole[] }) {
  const { data: heroesData } = useQuery({
    queryKey: ["heroes-all"],
    queryFn: () => heroService.getAll({ perPage: -1 }),
    staleTime: 5 * 60_000,
  });

  const sortedRoles = useMemo(() => {
    if (!roles) return [];
    return [...roles].sort((a, b) => {
      if (a.is_primary && !b.is_primary) return -1;
      if (!a.is_primary && b.is_primary) return 1;
      return a.priority - b.priority;
    });
  }, [roles]);

  const heroesMap = useMemo(() => {
    const map = new Map<string, Hero>();
    if (heroesData?.results) {
      for (const h of heroesData.results) {
        map.set(h.slug, h);
      }
    }
    return map;
  }, [heroesData]);

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
    const groups: Record<"tank" | "dps" | "support", Hero[]> = {
      tank: [],
      dps: [],
      support: [],
    };

    for (const hero of topHeroesList) {
      const canonical = getCanonicalRole(hero);
      groups[canonical].push(hero);
    }

    return groups;
  }, [topHeroesList]);

  const activeRoles = useMemo(() => {
    return (["tank", "dps", "support"] as const).filter(
      (role) => heroesByRole[role].length > 0
    );
  }, [heroesByRole]);

  if (topHeroesList.length === 0) {
    return <span className="text-white/30">&mdash;</span>;
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 justify-center">
      {activeRoles.map((role) => (
        <div
          key={role}
          className="flex items-center gap-1.5 bg-white/[0.02] border border-white/[0.04] rounded-full pl-2 pr-1 py-0.5 shadow-sm"
        >
          <span
            className={cn("inline-flex items-center shrink-0", ROLE_COLORS[role])}
            title={role.toUpperCase()}
          >
            <PlayerRoleIcon role={ROLE_TO_ICON[role] || role} size={14} />
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
}: {
  tags: string[] | null | undefined;
}) {
  const t = useTranslations();
  const smurfTags = tags?.filter(Boolean) ?? [];

  if (smurfTags.length === 0) {
    return <span className="text-white/30">&mdash;</span>;
  }

  const visibleTags = smurfTags.slice(0, MAX_VISIBLE_SMURF_TAGS);
  const hiddenCount = smurfTags.length - visibleTags.length;

  return (
    <div className="flex max-w-[220px] flex-col items-start gap-1">
      {visibleTags.map((tag, index) => (
        <span
          key={`${tag}-${index}`}
          className="block max-w-full truncate text-xs leading-5 text-white/50"
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
              className="text-xs font-medium text-emerald-300/80 transition hover:text-emerald-200"
            >
              +{hiddenCount} {t("common.more")}
            </button>
          </DialogTrigger>
          <DialogContent className="border-white/[0.08] bg-[#111113] sm:max-w-md">
            <DialogHeader>
              <DialogTitle className="text-white">{t("common.smurfBattleTags")}</DialogTitle>
              <DialogDescription className="text-white/50">
                {t("common.smurfDesc")}
              </DialogDescription>
            </DialogHeader>
            <ScrollArea className="max-h-[320px] pr-2">
              <div className="flex flex-col gap-2">
                {smurfTags.map((tag, index) => (
                  <div
                    key={`${tag}-${index}`}
                    className="rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/80"
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

function StreamPovCell({ value }: { value: boolean | null | undefined }) {
  const t = useTranslations();
  const label = value ? t("common.yes") : t("common.no");
  return (
    <span
      title={label}
      aria-label={label}
      className={cn(
        "inline-flex size-5 items-center justify-center",
        value ? "text-emerald-400" : "text-red-400",
      )}
    >
      {value ? (
        <CheckCircle2 className="size-4" />
      ) : (
        <XCircle className="size-4" />
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Custom field value renderer
// ---------------------------------------------------------------------------

function renderCustomFieldValue(
  field: CustomFieldDefinition,
  value: unknown,
  t: Translator,
): ReactNode {
  if (value === null || value === undefined)
    return <span className="text-white/30">&mdash;</span>;

  switch (field.type) {
    case "checkbox":
      return (
        <span className="text-white/60">{value ? t("common.yes") : t("common.no")}</span>
      );
    case "url":
      return (
        <a
          href={String(value)}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-white/60 underline decoration-white/20 hover:text-white/80"
        >
          <span className="max-w-[120px] truncate">{String(value)}</span>
          <ExternalLink className="size-3 shrink-0" />
        </a>
      );
    case "select":
      return (
        <span className="inline-flex items-center rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-xs font-medium text-white/60">
          {String(value)}
        </span>
      );
    default:
      return <span className="text-white/60">{String(value)}</span>;
  }
}

// ---------------------------------------------------------------------------
// Date formatter
// ---------------------------------------------------------------------------

function formatDate(iso: string | null, locale: string = "ru"): ReactNode {
  if (!iso) return <span className="text-white/30">&mdash;</span>;
  const d = new Date(iso);
  const formatLocale = locale.startsWith("ru") ? "ru-RU" : "en-GB";
  return (
    <span className="text-white/50 tabular-nums text-xs">
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

interface BuiltInFieldDef {
  id: string;
  label: string;
  defaultVisible: boolean;
  responsive?: ColumnDefinition["responsive"];
  widthClass?: string;
  align?: ColumnDefinition["align"];
  render: (reg: Registration) => ReactNode;
  searchValue?: (reg: Registration) => string | null;
}

const BUILT_IN_FIELD_DEFS: Record<string, BuiltInFieldDef> = {
  battle_tag: {
    id: "battle_tag",
    label: "BattleTag",
    defaultVisible: true,
    responsive: "always",
    render: (reg) => (
      <span className="font-medium text-white/80">
        {reg.battle_tag ? (
          <a
            href={`/users/${getPlayerSlug(reg.battle_tag)}`}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:underline hover:text-emerald-400 transition"
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
      <span className="text-white/50">{reg.discord_nick ?? "\u2014"}</span>
    ),
    searchValue: (reg) => reg.discord_nick,
  },
  twitch_nick: {
    id: "twitch_nick",
    label: "Twitch",
    defaultVisible: false,
    responsive: "md",
    render: (reg) => (
      <span className="text-white/50">{reg.twitch_nick ?? "\u2014"}</span>
    ),
    searchValue: (reg) => reg.twitch_nick,
  },
  primary_role: {
    id: "roles",
    label: "Roles",
    defaultVisible: true,
    responsive: "always",
    align: "center",
    render: (reg) => <RolesCell roles={reg.roles} />,
    searchValue: (reg) =>
      reg.roles?.map((r) => r.role).join(" ") ?? null,
  },
  top_heroes: {
    id: "top_heroes",
    label: "Top Heroes",
    defaultVisible: true,
    responsive: "sm",
    align: "center",
    render: (reg) => <TopHeroesCell roles={reg.roles} />,
    searchValue: (reg) =>
      reg.roles?.flatMap((r) => r.top_heroes).join(" ") ?? null,
  },
  additional_roles: {
    // Merged into primary_role column — skip as standalone
    id: "_skip_additional_roles",
    label: "Additional Roles",
    defaultVisible: false,
    render: () => null,
  },
  stream_pov: {
    id: "stream_pov",
    label: "Stream POV",
    defaultVisible: false,
    responsive: "lg",
    align: "center",
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
        <span className="block max-w-50 whitespace-pre-wrap wrap-break-word text-xs text-white/50">
          {reg.notes}
        </span>
      ) : (
        <span className="text-white/30">&mdash;</span>
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
): ColumnDefinition[] {
  const columns: ColumnDefinition[] = [];

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
    render: (_reg, index) => (
      <span className="text-white/30 tabular-nums">{index + 1}</span>
    ),
  });

  // Built-in fields from form config
  if (form?.built_in_fields) {
    for (const [key, config] of Object.entries(form.built_in_fields)) {
      if (!config.enabled) continue;
      const def = BUILT_IN_FIELD_DEFS[key];
      if (!def || def.id === "_skip_additional_roles") continue;
      if (key === "additional_roles") continue;

      columns.push({
        id: def.id,
        label: getLocalizedLabel(key, def.label),
        category: "built_in",
        defaultVisible: def.defaultVisible,
        responsive: def.responsive ?? "sm",
        widthClass: def.widthClass,
        align: def.align,
        render: def.id === "roles"
          ? (reg) => <RolesCell roles={reg.roles} grid={grid} showRanks={form?.show_ranks} />
          : (reg) => def.render(reg),
        searchValue: def.searchValue,
      });
    }
  } else {
    // Fallback when no form config
    for (const key of ["battle_tag", "smurf_tags", "primary_role", "top_heroes", "notes"]) {
      const def = BUILT_IN_FIELD_DEFS[key];
      if (!def) continue;
      columns.push({
        id: def.id,
        label: getLocalizedLabel(key, def.label),
        category: "built_in",
        defaultVisible: true,
        responsive: def.responsive ?? "sm",
        widthClass: def.widthClass,
        align: def.align,
        render: def.id === "roles"
          ? (reg) => <RolesCell roles={reg.roles} grid={grid} showRanks={form?.show_ranks} />
          : (reg) => def.render(reg),
        searchValue: def.searchValue,
      });
    }
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
          renderCustomFieldValue(
            field,
            reg.custom_fields_json?.[field.key] ?? null,
            t,
          ),
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
      render: (reg) => <ProfileStatusBadge profilesOpen={reg.profiles_open} />,
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
    render: (reg) => (
      <AdmissionStatusBadge
        registrationStatus={reg.status}
        balancerStatus={reg.balancer_status}
        checkedIn={reg.checked_in}
        requireOpenProfile={form?.require_open_profile ?? false}
        profilesOpen={reg.profiles_open}
      />
    ),
  });

  return columns;
}

