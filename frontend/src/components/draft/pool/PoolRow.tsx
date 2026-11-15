"use client";

import type { CSSProperties, ReactNode } from "react";
import { Check, ChevronDown, ChevronUp, Crown, Heart } from "lucide-react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { PersonLabel } from "@/components/PlayerName";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { RankCrest } from "@/components/RankCrest";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { RowButton } from "@craazzzyyfoxx/admin-kit/ui/row-button";
import { getImpactColor, tint } from "@/lib/colors";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/divisions/grid";
import {
  bestSeatRole,
  canSeat,
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
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { roleTint, showsRoles, type RoleOntology } from "@/lib/roster/ontology";
import { cn } from "@/lib/utils";
import type { DraftPickOptionsResponse, DraftPlayer, DraftRole } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { formatSubRoleLabel, getHeroIconUrl } from "@/lib/player";

/**
 * Shared by the column header and every row. Phones stack the role cells under
 * the name; from `sm` up the roles get one track, `--pool-roles` fr wide (one fr
 * per role column), set on the scroll container.
 */
export const POOL_GRID =
  "grid grid-cols-[minmax(0,1fr)_56px_32px] gap-x-2 sm:grid-cols-[minmax(128px,0.7fr)_minmax(0,var(--pool-roles))_56px_32px]";

const PRIORITY_KEYS = ["primary", "second", "third"] as const;

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
  /** The session owner's role dictionary: names, glyphs and colours of every role cell. */
  ontology: RoleOntology | null;
  /** Unique per mounted pool: prefixes the reason ids role buttons point at. */
  idPrefix: string;
  onSelect: (playerId: number, role: DraftRole) => void;
  onOpenProfile: (playerId: number) => void;
  /** Warms the player's card before a click opens it; `null` cancels. */
  onPrefetchCard: (userId: number | null) => void;
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
  ontology,
  idPrefix,
  onSelect,
  onOpenProfile,
  onPrefetchCard
}: Readonly<PoolRowProps>) {
  const t = useTranslations("draftRedesign");
  const slotLabel = useSlotLabel(ontology);
  const name = player.display.name;
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
      : t("pool.note.noSlot", { roles: roles.map((role) => slotLabel(role)).join(", ") })
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
      onPointerEnter={() => onPrefetchCard(player.user_id)}
      onPointerLeave={() => onPrefetchCard(null)}
      onFocus={() => onPrefetchCard(player.user_id)}
      title={clickRole != null ? t("pool.row.select") : t("pool.row.open")}
      style={
        {
          "--row-bg": selected ? tint("var(--aqt-teal)", 9) : isProfile ? "var(--aqt-overlay-3)" : "transparent",
          boxShadow: selected
            ? "inset 3px 0 0 var(--aqt-teal)"
            : isProfile
              ? "inset 3px 0 0 var(--aqt-border-3)"
              : undefined
        } as CSSProperties
      }
      className={cn(
        POOL_GRID,
        "min-h-16 cursor-pointer items-center gap-y-2 border-b border-[color:var(--aqt-border)] bg-[color:var(--row-bg)] px-4 pb-1.5 pt-2.5",
        // Hover must not wipe the selected / open-profile tint it would replace.
        !selected && !isProfile && "hover:bg-[color:var(--aqt-overlay-2)]"
      )}
    >
      <div className={cn("min-w-0", dimmed && "opacity-55")}>
        <div className="flex min-w-0 items-center gap-2 text-body">
          {tab === "shortlist" && queued && (
            <span className="shrink-0 text-caption font-semibold tabular-nums text-[color:var(--aqt-teal)]">
              #{queueIndex + 1}
            </span>
          )}
          {/* The name always opens the card; the row and role cells are what pick. */}
          <Button
            variant="link"
            size="inline"
            onClick={(event) => {
              event.stopPropagation();
              onOpenProfile(player.id);
            }}
            aria-label={t("openProfile", { player: name })}
            // Focus target when the pick card closes and its opener is gone.
            data-player-name={player.id}
            title={name}
            className="min-w-0 font-semibold text-[color:var(--aqt-fg)] hover:text-[color:var(--aqt-teal)]"
          >
            <PersonLabel display={player.display} tag="hidden" />
          </Button>
          {player.is_captain && (
            <Crown className="h-[15px] w-[15px] shrink-0 text-[color:var(--aqt-warm)]" role="img" aria-label={t("captain")} />
          )}
          {player.is_flex && (
            <span className="shrink-0 rounded border border-[color:var(--aqt-border-2)] px-[5px] text-label font-medium text-[color:var(--aqt-fg-muted)]">
              {t("flex")}
            </span>
          )}
        </div>
        {note != null ? (
          <div
            className={cn(
              "mt-0.5 truncate text-caption",
              blocked ? "text-[color:var(--aqt-rose-text)]" : "text-[color:var(--aqt-fg-muted)]"
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
              ontology={ontology}
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
          ontology={ontology}
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
        <Button
          variant="ghost"
          size="icon"
          aria-label={queued ? t("pool.queueRemove") : t("pool.queueAdd")}
          aria-pressed={queued}
          onClick={(event) => {
            event.stopPropagation();
            queue.toggle(player.id);
          }}
          className={cn(
            "size-11 justify-self-end rounded-lg sm:size-8",
            queued ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-faint)]"
          )}
        >
          <Heart className={cn(queued && "fill-current")} aria-hidden="true" />
        </Button>
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
    <Button
      variant="ghost"
      size="icon"
      aria-label={label}
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      className="size-11 text-[color:var(--aqt-fg-muted)] sm:h-6 sm:w-7"
    >
      {children}
    </Button>
  );
}

function RightCell({
  player,
  available,
  blocked,
  actingTeam,
  takenTeam,
  fit,
  ontology
}: Readonly<{
  player: DraftPlayer;
  available: boolean;
  blocked: boolean;
  actingTeam: TeamView | null;
  takenTeam: TeamView | null;
  fit: PlayerFit | undefined;
  ontology: RoleOntology | null;
}>) {
  const t = useTranslations("draftRedesign");
  const slotLabel = useSlotLabel(ontology);
  const named = showsRoles(ontology);
  const main = "truncate text-body font-semibold";

  if (!available) {
    const cell = takenTeam?.cells.find((entry) => entry.player?.id === player.id);
    // The team is already under the name ("Already on {team}"); this narrow
    // column only has room for what that line lacks — the seat they took.
    if (!player.is_captain && cell?.role && named) {
      const label = `${slotLabel(cell.role)}${cell.offRole ? ` · ${t("pool.right.offRole")}` : ""}`;
      return (
        <div className={cn("flex justify-end", cell.offRole && "opacity-60 grayscale")} title={label}>
          <PlayerRoleIcon role={cell.role} ontology={ontology} size={22} label={label} />
        </div>
      );
    }
    return (
      <div className={cn(main, "text-[color:var(--aqt-fg)]")} title={takenTeam?.team.name}>
        {player.is_captain ? t("pool.right.captain") : "—"}
      </div>
    );
  }

  // A spectator has no team to fit an available player to: the cell stays empty.
  if (actingTeam == null) return null;
  if (blocked || fit == null) return <div className={cn(main, "text-[color:var(--aqt-fg-faint)]")}>—</div>;
  // The analytics impact ramp: fit is the same kind of 1..99 spread, and its
  // up-green is kept apart from the support role's green.
  const color = getImpactColor(fit.score);
  const title =
    fit.role == null || !named
      ? t("pool.fitTitleAny", { team: actingTeam.team.name })
      : t("pool.fitTitle", { team: actingTeam.team.name, role: slotLabel(fit.role) });
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
  ontology,
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
  ontology: RoleOntology | null;
  reasonId: string;
  onSelect: (playerId: number, role: DraftRole) => void;
}>) {
  const t = useTranslations("draftRedesign");
  const slotLabel = useSlotLabel(ontology);
  const primary = index === 0;
  const roleLabel = slotLabel(role);
  // One role: the cell is the player's rank and pick -- no priority, no glyph, no role in its name.
  const named = showsRoles(ontology);
  // The role's OWN rank: spending a support main on tank is a different number.
  const rank = player.role_ranks[role] ?? null;
  const division = resolveDivisionFromRank(divisionGrid, rank);
  const divisionLabel = division == null ? null : getDivisionLabel(divisionGrid, division);
  const subRole = formatSubRoleLabel(player.role_sub_roles?.[role]);
  const heroes = roleTopHeroes(player, role).slice(0, 3);
  const prioTitle = t("pool.cell.priority", { n: index + 1, total });
  const summary = [
    named ? `${roleLabel}${primary ? ` (${t("pool.cell.primaryMark")})` : ""}` : null,
    rank ?? "—",
    divisionLabel
  ]
    .filter(Boolean)
    .join(" · ");

  const body = (
    <>
      {named && (
        <span
          title={prioTitle}
          className={cn(
            "pointer-events-none absolute -top-[7px] left-[7px] whitespace-nowrap bg-[color:var(--aqt-card)] px-1 text-label font-semibold leading-none",
            primary ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-muted)]"
          )}
        >
          {t(`pool.cell.${PRIORITY_KEYS[index] ?? "third"}`)}
        </span>
      )}
      {named && (
        <span className={cn("inline-flex h-[22px] w-[22px] shrink-0", !primary && "opacity-60 grayscale")}>
          <PlayerRoleIcon
            role={role}
            ontology={ontology}
            size={22}
            decorative={actor != null}
            label={roleLabel}
          />
        </span>
      )}
      <span className="ml-0.5 mr-1 inline-flex h-[22px] w-[22px] shrink-0">
        <RankCrest division={division} grid={divisionGrid} tooltip={false} />
      </span>
      <span className="flex min-w-0 flex-auto flex-col gap-0.5 text-left" title={subRole ?? undefined}>
        <span className="whitespace-nowrap text-body font-semibold leading-tight tabular-nums">{rank ?? "—"}</span>
        {subRole && <span className="truncate text-label leading-tight text-[color:var(--aqt-fg-muted)]">{subRole}</span>}
      </span>
      {/* Hero faces are the first thing to give way: a cell narrower than the
          crest + rank + three faces keeps the rank whole instead (container
          query on the cell, so it tracks the panel width, not the viewport). */}
      {heroes.length > 0 && (
        <span className="hidden shrink-0 @[176px]/cell:flex">
          {heroes.map((hero, heroIndex) => (
            <CatalogEntityImage
              key={hero.slug}
              entity={{ name: hero.slug.replace(/-/g, " "), image_path: getHeroIconUrl(hero.slug, hero.imagePath) }}
              size={26}
              className={cn("border-2 border-[color:var(--aqt-card)]", heroIndex > 0 && "-ml-[15px]")}
            />
          ))}
        </span>
      )}
    </>
  );
  const shell =
    "@container/cell relative flex h-[52px] w-full min-w-0 items-center gap-[3px] overflow-visible rounded-lg border pl-[5px] pr-[3px] text-caption font-medium";

  if (actor == null) {
    // Spectators and taken players: the same facts, nothing to press.
    return (
      <span
        title={summary}
        className={cn(
          shell,
          "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-muted)]",
          // Dim by colour, not opacity: opacity stacks onto an already muted
          // foreground and drops the cell under 3:1.
          dimmed && "text-[color:var(--aqt-fg-dim)] [&_img]:grayscale [&_svg]:grayscale"
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
    <RowButton
      aria-label={named ? t("pickAs", { player: name, role: roleLabel }) : t("island.tile.selectPlayer", { player: name })}
      aria-pressed={on}
      // aria-disabled, not `disabled`: the reason stays reachable and announced.
      aria-disabled={!usable || undefined}
      aria-describedby={reason ? reasonId : undefined}
      title={reason ? `${summary} — ${reason}` : summary}
      onClick={(event) => {
        event.stopPropagation();
        if (usable) onSelect(player.id, role);
      }}
      style={
        {
          "--cell-border": on
            ? "var(--aqt-teal)"
            : usable && primary
              ? tint(roleTint(ontology, role), 55)
              : "var(--aqt-border-2)",
          background: on
            ? tint("var(--aqt-teal)", 18)
            : usable
              ? primary
                ? tint(roleTint(ontology, role), 9)
                : "var(--aqt-overlay-2)"
              : "transparent"
        } as CSSProperties
      }
      className={cn(
        shell,
        "border-[color:var(--cell-border)]",
        // A cell that cannot be taken must not invite the click, and must stay
        // legible: dim foreground, not opacity over the whole cell.
        usable ? "cursor-pointer" : "cursor-default border-dashed [&_img]:grayscale [&_svg]:grayscale",
        usable && !on && "hover:border-[color:var(--aqt-teal)]",
        on || usable ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-dim)]"
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
    </RowButton>
  );
}
