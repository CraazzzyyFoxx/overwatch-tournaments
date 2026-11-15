"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import {
  AccentBadge,
  RoleRankControls,
  accentRowStyle,
  accentTextStyle,
  roleRankAccent,
  type RoleRankAccent
} from "@/app/balancer/components/RoleRankControls";
import { rectSortingStrategy } from "@dnd-kit/sortable";

import { SortableGrip, SortableRows, useSortableRow } from "@/components/kit/SortableRows";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Switch } from "@/components/ui/switch";
import DivisionIcon from "@/components/DivisionIcon";
import { IconTooltip } from "@craazzzyyfoxx/admin-kit/ui/icon-tooltip";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/divisions/grid";
import { cn } from "@/lib/utils";

import type { MixOwner } from "./pickup-lineup";

/**
 * One role's rank, as this editor should render it.
 *
 * `onChange === null` is the read-only case. A mix's ranks are the HOST's book
 * (`author_user_id = game.host_user_id`), so the host's sheet edits them from
 * here and a player's own panel only reads them -- the player owns `roles` and
 * `is_flex` and nothing else on their row.
 */
type PickupRoleRank = {
  rankValue: number | null;
  /** Which layer the shown rank came from, badged beside it. */
  sourceLabel: string | null;
  onChange: ((next: number | null) => void) | null;
  /** Only offered when there is an own entry to drop. */
  onClear: (() => void) | null;
};

type PickupRoleOrderEditorProps = {
  /** The mix owner's game: the roles on offer, their names/tints and the grid the ranks are on. */
  owner: MixOwner;
  /** The roles that are ON, in priority order -- position is what the balancer reads. */
  order: readonly string[];
  isFlex: boolean;
  disabled: boolean;
  /** Whose roles these are; every control's accessible name ends in it. */
  label: string;
  onReorder: (next: string[]) => void;
  onToggle: (role: string) => void;
  onFlexChange: (next: boolean) => void;
  rankFor: (role: string) => PickupRoleRank;
  /** `list`: one column of full cards (the host's sheet, where the rank fields need the room).
   * `row`: compact two-line cards side by side in priority order, Full flex a switch on the `heading` line (the
   * player's seat panel). */
  layout?: "list" | "row";
  /** `row` only: what starts the line above the cards -- the caller's label and hint. */
  heading?: ReactNode;
};

/**
 * Role priority and the flex flag, in one place for both callers.
 *
 * Priority is a drag list because the stored role order *is* the balancer's
 * priority (see `CustomGamePlayer.roles`): deriving it from a rank moved a
 * role's seat the moment any layer's number changed, with no click anyone
 * could point at. Dragging makes it what it always was on the wire.
 *
 * Off roles trail the on ones in the game's declared order: an unselected role has no
 * priority, so ranking them would imply one.
 *
 * A one-role game (`owner.showsRoles` false) has nothing to order or switch: only its rank is shown. A game without
 * Full flex (`owner.flex` false) gets no flex switch.
 */
export function PickupRoleOrderEditor({
  owner,
  order,
  isFlex,
  disabled,
  label,
  onReorder,
  onToggle,
  onFlexChange,
  rankFor,
  layout = "list",
  heading
}: Readonly<PickupRoleOrderEditorProps>) {
  const t = useTranslations("mixes.roleOrder");
  const row = layout === "row";
  // The row layout's first line: the caller's heading, then Full flex as a plain switch -- it is one flag, not a card.
  const headLine =
    row && (heading != null || (owner.flex && owner.showsRoles)) ? (
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        {heading}
        {owner.flex && owner.showsRoles ? (
          <label className="ml-auto flex items-center gap-2 text-caption text-[color:var(--aqt-fg-muted)]">
            {t("fullFlex")}
            <Switch
              size="sm"
              checked={isFlex}
              disabled={disabled}
              aria-label={t("flexFor", { name: label })}
              onCheckedChange={onFlexChange}
            />
          </label>
        ) : null}
      </div>
    ) : null;
  if (!owner.showsRoles) {
    const [role] = owner.roles;
    if (role == null) return null;
    const only = <OnlyRoleRank role={role} owner={owner} disabled={disabled} rank={rankFor(role)} />;
    return headLine == null ? only : <div className="space-y-2">{headLine}{only}</div>;
  }
  const offRoles = owner.roles.filter((role) => !order.includes(role));

  return (
    // `contents` on the lists lets their cards sit in this grid directly.
    <div className="@container space-y-2">
      {headLine}
      <div className={cn("grid gap-2", row && "@md:grid-cols-2 @2xl:grid-cols-3")}>
        {owner.flex && !row ? (
          <div
            className={cn(
              "flex items-center justify-between gap-3 rounded-lg border px-3 py-2",
              isFlex
                ? "border-emerald-400/20 bg-emerald-500/[0.08]"
                : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)]"
            )}
          >
            <div className="min-w-0">
              <span className="text-xs font-medium text-[color:var(--aqt-fg)]">{t("fullFlex")}</span>
              <p className="mt-0.5 text-label text-[color:var(--aqt-fg-dim)]">
                {isFlex ? t("flexOn") : t("flexOff")}
              </p>
            </div>
            <Switch
              checked={isFlex}
              disabled={disabled}
              aria-label={t("flexFor", { name: label })}
              onCheckedChange={onFlexChange}
            />
          </div>
        ) : null}

        <SortableRows
          items={order}
          getId={(role) => role}
          onReorder={onReorder}
          strategy={row ? rectSortingStrategy : undefined}
          className="contents"
        >
          {(role, index) => (
            <SortableRoleCard
              key={role}
              id={role}
              role={role}
              owner={owner}
              label={label}
              priority={index + 1}
              isPrimary={index === 0}
              disabled={disabled}
              onToggle={() => onToggle(role)}
              rank={rankFor(role)}
              compact={row}
            />
          )}
        </SortableRows>

        {offRoles.length === 0 ? null : (
          <ul className="contents">
            {offRoles.map((role) => (
              <li
                key={role}
                className="flex items-start gap-2.5 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-2.5 opacity-80"
              >
                <RoleCardBody
                  role={role}
                  owner={owner}
                  label={label}
                  isOn={false}
                  isPrimary={false}
                  disabled={disabled}
                  onToggle={() => onToggle(role)}
                  rank={rankFor(role)}
                  compact={row}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** One role's card, wired to the drag list: grip and priority, then the row's own content. */
function SortableRoleCard({
  id,
  role,
  owner,
  label,
  priority,
  isPrimary,
  disabled,
  onToggle,
  rank,
  compact
}: Readonly<{
  id: string;
  role: string;
  owner: MixOwner;
  label: string;
  /** The row's position in the drag list, 1-based — what the balancer reads as priority. */
  priority: number;
  isPrimary: boolean;
  disabled: boolean;
  onToggle: () => void;
  rank: PickupRoleRank;
  compact: boolean;
}>) {
  const t = useTranslations("mixes.roleOrder");
  const { ref, style, handleProps } = useSortableRow(id, disabled);
  const slotLabel = useSlotLabel(owner.ontology);
  const lead = (
    <div className={cn("flex shrink-0 items-center gap-1", !compact && "flex-col")}>
      <SortableGrip
        handleProps={handleProps}
        label={t("reorder", { role: slotLabel(role), name: label })}
        disabled={disabled}
      />
      <span className="text-label font-semibold text-[color:var(--aqt-fg-dim)]">{`#${priority}`}</span>
    </div>
  );

  return (
    <li
      ref={ref}
      style={{ ...style, ...accentRowStyle(roleRankAccent(owner.ontology, role)) }}
      className="flex items-start gap-2.5 rounded-xl border p-2.5 transition-colors"
    >
      {compact ? null : lead}
      <RoleCardBody
        role={role}
        owner={owner}
        label={label}
        isOn
        isPrimary={isPrimary}
        disabled={disabled}
        onToggle={onToggle}
        rank={rank}
        compact={compact}
        lead={compact ? lead : null}
      />
    </li>
  );
}

/**
 * One role's card: name, first-choice mark, on/off, and the rank.
 *
 * Where the rank is editable (`rank.onChange`), the field edits the *effective*
 * rank — what balance will actually use — rather than only this host's own
 * entry, because a host reads the number they see and expects to be able to
 * correct it. Where it is not, the same number is printed as a crest beside
 * the role name: a player must see why the balancer seats them where it does,
 * and a boxed number under it read as a field they were expected to fill in.
 *
 * `compact` (the seat panel's row of cards) stacks it in two lines -- grip, priority and name over rank and switch --
 * and drops the Active/Off word, which a card a third of the panel wide has no room for: the switch says it, and its
 * accessible name stays.
 */
function RoleCardBody({
  role,
  owner,
  label,
  isOn,
  isPrimary,
  disabled,
  onToggle,
  rank,
  compact,
  lead = null
}: Readonly<{
  role: string;
  owner: MixOwner;
  label: string;
  isOn: boolean;
  /** The top of the drag list — where the balancer will try to seat them first. */
  isPrimary: boolean;
  disabled: boolean;
  onToggle: () => void;
  rank: PickupRoleRank;
  compact: boolean;
  /** `compact` only: the grip and priority, at the start of the name line. */
  lead?: ReactNode;
}>) {
  const t = useTranslations("mixes.roleOrder");
  const slotLabel = useSlotLabel(owner.ontology);
  const accent = roleRankAccent(owner.ontology, role);
  const name = slotLabel(role);
  const offText = { color: "var(--aqt-fg-muted)" };

  const readOnly = rank.onChange == null;
  const title = (
    <div className="flex min-w-0 items-center gap-1.5">
      {lead}
      <PlayerRoleIcon role={role} ontology={owner.ontology} size={15} decorative />
      <span className="truncate text-label font-semibold" style={isOn ? accentTextStyle(accent) : offText}>
        {name}
      </span>
      {isPrimary ? (
        <AccentBadge accent={accent} className="shrink-0 font-bold uppercase tracking-label">
          {t("first")}
        </AccentBadge>
      ) : null}
    </div>
  );
  const rankChip = readOnly ? <RankChip rank={rank} grid={owner.grid} active={isOn} accent={accent} /> : null;
  const toggle = (
    <Switch
      checked={isOn}
      disabled={disabled}
      aria-label={t("roleFor", { role: name, name: label })}
      onCheckedChange={onToggle}
      size="sm"
    />
  );
  const rankControls = rank.onChange == null ? null : (
    <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_130px]">
      <RoleRankControls
        rankValue={rank.rankValue}
        sourceLabel={rank.sourceLabel}
        accent={accent}
        active={isOn}
        disabled={disabled}
        onClear={rank.onClear}
        onChange={rank.onChange}
        // The owner game's global ladder: the scale the value is on, so the
        // crest and the slider name the same tiers.
        grid={owner.grid}
      />
    </div>
  );

  if (compact) {
    return (
      <div className="min-w-0 flex-1 space-y-2">
        {title}
        <div className="flex min-h-5 items-center justify-between gap-2">
          {rankChip ?? <span />}
          {toggle}
        </div>
        {rankControls}
      </div>
    );
  }

  return (
    <div className={cn("min-w-0 flex-1", !readOnly && "space-y-2")}>
      <div className="flex items-center justify-between gap-2">
        {title}

        <div className="flex items-center gap-2">
          {rankChip}
          <label className="flex items-center gap-1.5">
            {toggle}
            <span
              className="text-label font-semibold uppercase tracking-label"
              style={isOn ? accentTextStyle(accent) : { color: "var(--aqt-fg-dim)" }}
            >
              {isOn ? t("active") : t("off")}
            </span>
          </label>
        </div>
      </div>

      {rankControls}
    </div>
  );
}

/** A one-role game's rank: the crest and number, or the host's field, with nothing to choose around it. */
function OnlyRoleRank({
  role,
  owner,
  disabled,
  rank
}: Readonly<{ role: string; owner: MixOwner; disabled: boolean; rank: PickupRoleRank }>) {
  const accent = roleRankAccent(owner.ontology, role);
  return rank.onChange == null ? (
    <RankChip rank={rank} grid={owner.grid} active accent={accent} />
  ) : (
    <RoleRankControls
      rankValue={rank.rankValue}
      sourceLabel={rank.sourceLabel}
      accent={accent}
      active
      disabled={disabled}
      onClear={rank.onClear}
      onChange={rank.onChange}
      grid={owner.grid}
    />
  );
}

/** A rank nobody here may change: the crest and the number, no field around them. */
function RankChip({
  rank,
  grid,
  active,
  accent
}: Readonly<{
  rank: PickupRoleRank;
  grid: MixOwner["grid"];
  active: boolean;
  accent: RoleRankAccent;
}>) {
  const t = useTranslations("mixes.roleOrder");
  const division = resolveDivisionFromRank(grid, rank.rankValue);
  const divisionLabel = getDivisionLabel(grid, division);

  return (
    <span className="flex items-center gap-1.5">
      {division != null ? (
        <IconTooltip
          label={divisionLabel ?? String(division)}
          hint={rank.sourceLabel ?? t("rankHint")}
        >
          <DivisionIcon
            division={division}
            tournamentGrid={grid}
            width={20}
            height={20}
            className={cn("size-5 object-contain", !active && "opacity-50")}
          />
        </IconTooltip>
      ) : null}
      <span
        className="text-xs font-semibold tabular-nums"
        style={active ? accentTextStyle(accent) : { color: "var(--aqt-fg-dim)" }}
      >
        {rank.rankValue ?? "—"}
      </span>
    </span>
  );
}
