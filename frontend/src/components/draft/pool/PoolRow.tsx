"use client";

import type { CSSProperties, MouseEvent, ReactNode } from "react";
import { Check, ChevronDown, ChevronUp, Crown, Heart } from "lucide-react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/divisions/grid";
import {
  bestSeatRole,
  canSeat,
  demandCount,
  seatableRoles,
  type PlayerFit,
  type QueueControls,
  type TeamView
} from "@/lib/draft/room-model";
import {
  optionForSelection,
  playerRoles,
  roleTopHeroes,
  type DraftPoolRoleFilter,
  type DraftPoolTab
} from "@/lib/draft/workspace-model";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type { DraftPickOptionsResponse, DraftPlayer, DraftRole } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { formatSubRoleLabel, getHeroIconUrl } from "@/utils/player";

/**
 * Shared by the column header and every row. Phones stack the role cells under
 * the name; from `sm` up the roles get one track, `--pool-roles` fr wide (one fr
 * per role column), set on the scroll container.
 */
export const POOL_GRID =
  "grid grid-cols-[minmax(0,1fr)_56px_32px] gap-x-2 sm:grid-cols-[minmax(128px,0.7fr)_minmax(0,var(--pool-roles))_56px_32px]";

export const tint = (role: DraftRole, pct: number) =>
  `color-mix(in srgb, ${ROLE_ACCENT[role]} ${pct}%, transparent)`;
export const teal = (pct: number) => `color-mix(in srgb, var(--aqt-teal) ${pct}%, transparent)`;

const PRIORITY_KEYS = ["primary", "second", "third"] as const;

const stop = (event: MouseEvent) => event.stopPropagation();

interface PoolRowProps {
  player: DraftPlayer;
  columns: readonly DraftRole[];
  tab: DraftPoolTab;
  roleFilter: DraftPoolRoleFilter;
  teamViews: ReadonlyMap<number, TeamView>;
  actingTeam: TeamView | null;
  /** The selected role when THIS player is the selection. */
  selectedRole: DraftRole | null;
  isProfile: boolean;
  /** `undefined`: no score for this player (loading, or nothing seatable). */
  fit: PlayerFit | undefined;
  queue: QueueControls | null;
  /** Hearts and reordering: a captain's queue on a draft that is still running. */
  queueEditable: boolean;
  options: DraftPickOptionsResponse | null;
  safetyRequired: boolean;
  divisionGrid: DivisionGrid;
  /** Unique per mounted pool: prefixes the reason ids role buttons point at. */
  idPrefix: string;
  onSelect: (playerId: number, role: DraftRole) => void;
  onOpenProfile: (playerId: number) => void;
}

export function PoolRow({
  player,
  columns,
  tab,
  roleFilter,
  teamViews,
  actingTeam,
  selectedRole,
  isProfile,
  fit,
  queue,
  queueEditable,
  options,
  safetyRequired,
  divisionGrid,
  idPrefix,
  onSelect,
  onOpenProfile
}: Readonly<PoolRowProps>) {
  const t = useTranslations("draftRedesign");
  const name = player.battle_tag ?? `#${player.id}`;
  const roles = playerRoles(player);
  const available = player.status === "available";
  // The team this row selects for; `null` → every role is a read-only chip.
  const actor = available ? actingTeam : null;
  const blocked = actor != null && seatableRoles(player, actor).length === 0;
  const clickRole = actor == null ? null : bestSeatRole(player, actor, roleFilter);
  const takenTeam =
    available || player.drafted_by_team_id == null ? null : teamViews.get(player.drafted_by_team_id) ?? null;
  const selected = selectedRole != null;
  const dimmed = blocked || (!available && tab !== "all");
  const queueIndex = queue?.ids.indexOf(player.id) ?? -1;
  const queued = queueIndex >= 0;

  const note = blocked
    ? actor.full
      ? t("pool.note.full", { team: actor.team.name })
      : t("pool.note.noSlot", { roles: roles.map((role) => t(`roles.${role}`)).join(", ") })
    : !available && tab !== "available"
      ? t("pool.note.taken", { team: takenTeam?.team.name ?? t("unknownTeam") })
      : null;

  const onRow = () => {
    if (clickRole != null) onSelect(player.id, clickRole);
    else onOpenProfile(player.id);
  };

  return (
    <div
      role="listitem"
      onClick={onRow}
      title={clickRole != null ? t("pool.row.select") : t("pool.row.open")}
      style={
        {
          "--row-bg": selected ? teal(9) : isProfile ? "var(--aqt-overlay-3)" : "transparent",
          boxShadow: selected
            ? "inset 3px 0 0 var(--aqt-teal)"
            : isProfile
              ? "inset 3px 0 0 var(--aqt-border-3)"
              : undefined
        } as CSSProperties
      }
      className={cn(
        POOL_GRID,
        "min-h-16 cursor-pointer items-center gap-y-2 border-b border-[color:var(--aqt-border)] bg-[color:var(--row-bg)] px-4 pb-1.5 pt-2.5 hover:bg-[color:var(--aqt-overlay-2)]"
      )}
    >
      <div className={cn("min-w-0", dimmed && "opacity-55")}>
        <div className="flex min-w-0 items-center gap-2">
          {tab === "shortlist" && queued && (
            <span className="shrink-0 text-caption font-semibold tabular-nums text-[color:var(--aqt-teal)]">
              #{queueIndex + 1}
            </span>
          )}
          {/* The name always opens the card; the row and role cells are what pick. */}
          <button
            type="button"
            onClick={(event) => {
              stop(event);
              onOpenProfile(player.id);
            }}
            aria-label={t("openProfile", { player: name })}
            className="min-w-0 truncate rounded text-left text-body font-semibold text-[color:var(--aqt-fg)] outline-none hover:text-[color:var(--aqt-teal)] hover:underline focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
          >
            {name}
          </button>
          {player.is_captain && (
            <Crown className="h-[15px] w-[15px] shrink-0 text-[color:var(--aqt-warm)]" role="img" aria-label={t("captain")} />
          )}
          {player.is_flex && (
            <span className="shrink-0 rounded border border-[color:var(--aqt-border-2)] px-[5px] text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
              {t("flex")}
            </span>
          )}
        </div>
        {note != null ? (
          <div
            className={cn(
              "mt-0.5 truncate text-caption",
              blocked ? "text-[color:var(--aqt-rose)]" : "text-[color:var(--aqt-fg-muted)]"
            )}
          >
            {note}
          </div>
        ) : roles.length === 0 ? (
          <div className="mt-0.5 truncate text-caption text-[color:var(--aqt-fg-faint)]">{t("noRole")}</div>
        ) : null}
      </div>

      <div
        className="col-span-3 row-start-2 grid min-w-0 gap-[5px] pt-1 sm:col-span-1 sm:row-start-auto sm:pt-0"
        style={{ gridTemplateColumns: `repeat(${Math.max(columns.length, 1)}, minmax(0, 1fr))` }}
      >
        {columns.map((role) => {
          const index = roles.indexOf(role);
          if (index < 0) return <span key={role} aria-hidden="true" />;
          return (
            <RoleCell
              key={role}
              player={player}
              name={name}
              role={role}
              index={index}
              total={roles.length}
              actor={actor}
              on={selectedRole === role}
              dimmed={dimmed}
              options={options}
              safetyRequired={safetyRequired}
              divisionGrid={divisionGrid}
              reasonId={`${idPrefix}-${player.id}-${role}-reason`}
              onSelect={onSelect}
            />
          );
        })}
      </div>

      <div className="min-w-0 text-right">
        <RightCell
          player={player}
          available={available}
          blocked={blocked}
          actingTeam={actingTeam}
          takenTeam={takenTeam}
          fit={fit}
          teamViews={teamViews}
        />
        {tab === "shortlist" && queueEditable && queued && queue && (
          <div className="mt-[3px] flex justify-end gap-0.5">
            <MoveButton
              label={t("pool.moveUp")}
              disabled={queueIndex === 0}
              onClick={() => queue.move(player.id, -1)}
            >
              <ChevronUp className="h-4 w-4" aria-hidden="true" />
            </MoveButton>
            <MoveButton
              label={t("pool.moveDown")}
              disabled={queueIndex === queue.ids.length - 1}
              onClick={() => queue.move(player.id, 1)}
            >
              <ChevronDown className="h-4 w-4" aria-hidden="true" />
            </MoveButton>
          </div>
        )}
      </div>

      {queueEditable && queue && available ? (
        <button
          type="button"
          aria-label={queued ? t("pool.queueRemove") : t("pool.queueAdd")}
          aria-pressed={queued}
          onClick={(event) => {
            stop(event);
            queue.toggle(player.id);
          }}
          className={cn(
            "flex h-11 w-11 items-center justify-center justify-self-end rounded-lg outline-none hover:bg-[color:var(--aqt-overlay-3)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] sm:h-8 sm:w-8",
            queued ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-faint)]"
          )}
        >
          <Heart className={cn("h-[18px] w-[18px]", queued && "fill-current")} aria-hidden="true" />
        </button>
      ) : (
        <span />
      )}
    </div>
  );
}

function MoveButton({
  label,
  disabled,
  onClick,
  children
}: Readonly<{ label: string; disabled: boolean; onClick: () => void; children: ReactNode }>) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={(event) => {
        stop(event);
        onClick();
      }}
      className="flex h-11 w-11 items-center justify-center rounded-md text-[color:var(--aqt-fg-muted)] outline-none hover:bg-[color:var(--aqt-overlay-3)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] disabled:opacity-40 sm:h-6 sm:w-7"
    >
      {children}
    </button>
  );
}

function RightCell({
  player,
  available,
  blocked,
  actingTeam,
  takenTeam,
  fit,
  teamViews
}: Readonly<{
  player: DraftPlayer;
  available: boolean;
  blocked: boolean;
  actingTeam: TeamView | null;
  takenTeam: TeamView | null;
  fit: PlayerFit | undefined;
  teamViews: ReadonlyMap<number, TeamView>;
}>) {
  const t = useTranslations("draftRedesign");
  const main = "truncate text-body font-semibold";

  if (!available) {
    const cell = takenTeam?.cells.find((entry) => entry.player?.id === player.id);
    const sub = player.is_captain
      ? t("pool.right.captain")
      : cell?.role
        ? `${t(`roles.${cell.role}`)}${cell.offRole ? ` · ${t("pool.right.offRole")}` : ""}`
        : null;
    return (
      <>
        <div className={cn(main, "text-[color:var(--aqt-fg)]")}>{takenTeam?.team.name ?? "—"}</div>
        {sub && <div className="truncate text-caption text-[color:var(--aqt-fg-muted)]">{sub}</div>}
      </>
    );
  }

  if (actingTeam != null) {
    if (blocked || fit == null) return <div className={cn(main, "text-[color:var(--aqt-fg-faint)]")}>—</div>;
    const color =
      fit.score >= 75 ? "var(--aqt-support)" : fit.score >= 55 ? "var(--aqt-fg)" : "var(--aqt-fg-muted)";
    const title =
      fit.role == null
        ? t("pool.fitTitleAny", { team: actingTeam.team.name })
        : t("pool.fitTitle", { team: actingTeam.team.name, role: t(`roles.${fit.role}`) });
    return (
      <div title={title}>
        <div className={cn(main, "tabular-nums")} style={{ color }}>
          <span className="sr-only">{title}: </span>
          {fit.score}
        </div>
        <div className="ml-auto mt-[5px] h-1 w-full max-w-11 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-3)]">
          <div className="h-full" style={{ width: `${fit.score}%`, background: color }} />
        </div>
      </div>
    );
  }

  const demand = demandCount(player, teamViews);
  return (
    <div className={cn(main, "text-[color:var(--aqt-fg-muted)]")} title={t("pool.demandTitle")}>
      {demand > 0 ? t("pool.demand", { count: demand }) : "—"}
    </div>
  );
}

function RoleCell({
  player,
  name,
  role,
  index,
  total,
  actor,
  on,
  dimmed,
  options,
  safetyRequired,
  divisionGrid,
  reasonId,
  onSelect
}: Readonly<{
  player: DraftPlayer;
  name: string;
  role: DraftRole;
  index: number;
  total: number;
  /** Acting team when the viewer can pick this (available) player; `null` → chip. */
  actor: TeamView | null;
  on: boolean;
  dimmed: boolean;
  options: DraftPickOptionsResponse | null;
  safetyRequired: boolean;
  divisionGrid: DivisionGrid;
  reasonId: string;
  onSelect: (playerId: number, role: DraftRole) => void;
}>) {
  const t = useTranslations("draftRedesign");
  const primary = index === 0;
  const roleLabel = t(`roles.${role}`);
  // The role's OWN rank: spending a support main on tank is a different number.
  const rank = player.role_ranks[role] ?? null;
  const division = resolveDivisionFromRank(divisionGrid, rank);
  const divisionLabel = division == null ? null : getDivisionLabel(divisionGrid, division);
  const subRole = formatSubRoleLabel(player.role_sub_roles?.[role]);
  const heroes = roleTopHeroes(player, role).slice(0, 3);
  const prioTitle = t("pool.cell.priority", { n: index + 1, total });
  const summary = [
    `${roleLabel}${primary ? ` (${t("pool.cell.primaryMark")})` : ""}`,
    rank ?? "—",
    divisionLabel
  ]
    .filter(Boolean)
    .join(" · ");

  const body = (
    <>
      <span
        title={prioTitle}
        className={cn(
          "pointer-events-none absolute -top-[7px] left-[7px] whitespace-nowrap bg-[color:var(--aqt-card)] px-1 text-[11px] font-semibold uppercase leading-[13px] tracking-[0.06em]",
          primary ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-muted)]"
        )}
      >
        {t(`pool.cell.${PRIORITY_KEYS[index] ?? "third"}`)}
      </span>
      <span className={cn("inline-flex h-[22px] w-[22px] shrink-0", !primary && "opacity-60 grayscale")}>
        <PlayerRoleIcon
          role={getRoleIconName(role)}
          size={22}
          color={ROLE_ACCENT[role]}
          decorative={actor != null}
          label={roleLabel}
        />
      </span>
      <span className="ml-0.5 mr-1 inline-flex h-[22px] w-[22px] shrink-0" title={divisionLabel ?? undefined}>
        {division != null && (
          <DivisionIcon
            division={division}
            tournamentGrid={divisionGrid}
            width={22}
            height={22}
            className="h-[22px] w-[22px] object-contain"
          />
        )}
      </span>
      <span className="flex min-w-0 flex-auto flex-col gap-0.5 text-left" title={subRole ?? t("pool.cell.noSubRole")}>
        <span className="whitespace-nowrap text-body font-semibold leading-tight tabular-nums">{rank ?? "—"}</span>
        <span
          className={cn(
            "truncate text-label leading-tight tracking-[-0.01em]",
            subRole ? "text-[color:var(--aqt-fg-muted)]" : "text-[color:var(--aqt-fg-faint)]"
          )}
        >
          {subRole ?? t("pool.cell.noSubRole")}
        </span>
      </span>
      {heroes.length > 0 && (
        <span className="hidden shrink-0 sm:flex">
          {heroes.map((hero, heroIndex) => {
            const heroName = hero.slug.replace(/-/g, " ");
            return (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                key={hero.slug}
                src={getHeroIconUrl(hero.slug, hero.imagePath)}
                alt={heroName}
                title={heroName}
                width={26}
                height={26}
                loading="lazy"
                className="h-[26px] w-[26px] shrink-0 rounded-full border-2 border-[color:var(--aqt-card)] object-cover capitalize"
                style={{ marginLeft: heroIndex ? -15 : 0 }}
              />
            );
          })}
        </span>
      )}
    </>
  );
  const shell =
    "relative flex h-[52px] w-full min-w-0 items-center gap-[3px] overflow-visible rounded-lg border pl-[5px] pr-[3px] text-caption font-medium";

  if (actor == null) {
    // Spectators and taken players: the same facts, nothing to press.
    return (
      <span
        title={summary}
        className={cn(
          shell,
          "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-muted)]",
          dimmed && "opacity-55"
        )}
      >
        {body}
      </span>
    );
  }

  const seatable = canSeat(actor, role);
  const option = safetyRequired ? optionForSelection(options, player.id, role) : null;
  const unsafe = safetyRequired && !(option?.is_safe ?? false);
  const usable = seatable && !unsafe;
  const reason = !seatable
    ? actor.full
      ? t("pool.note.full", { team: actor.team.name })
      : t("pool.reason.noSlot", { team: actor.team.name, role: roleLabel })
    : unsafe
      ? option?.reason_code === "slot_filled" || option?.reason_code === "role_shortage"
        ? t(`optionReason.${option.reason_code}`)
        : t("unsafeOption")
      : null;

  return (
    <button
      type="button"
      aria-label={t("pickAs", { player: name, role: roleLabel })}
      aria-pressed={on}
      // aria-disabled, not `disabled`: the reason stays reachable and announced.
      aria-disabled={!usable || undefined}
      aria-describedby={reason ? reasonId : undefined}
      title={reason ? `${summary} — ${reason}` : summary}
      onClick={(event) => {
        stop(event);
        if (usable) onSelect(player.id, role);
      }}
      style={
        {
          "--cell-border": on
            ? "var(--aqt-teal)"
            : usable && primary
              ? tint(role, 55)
              : "var(--aqt-border-2)",
          background: on ? teal(18) : usable ? (primary ? tint(role, 9) : "var(--aqt-overlay-2)") : "transparent"
        } as CSSProperties
      }
      className={cn(
        shell,
        "cursor-pointer border-[color:var(--cell-border)] outline-none transition-colors hover:border-[color:var(--aqt-teal)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
        on || usable ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-muted)]",
        !usable && "border-dashed opacity-45"
      )}
    >
      {body}
      {reason && (
        <span id={reasonId} className="sr-only">
          {reason}
        </span>
      )}
      {on && (
        <span className="absolute -right-1.5 -top-2 flex h-4 w-4 items-center justify-center rounded-full bg-[color:var(--aqt-teal)]">
          <Check className="h-[11px] w-[11px] text-[color:var(--aqt-bg)]" strokeWidth={3} aria-hidden="true" />
        </span>
      )}
    </button>
  );
}
