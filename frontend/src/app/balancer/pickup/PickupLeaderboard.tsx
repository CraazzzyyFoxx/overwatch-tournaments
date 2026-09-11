"use client";

import { PANEL_CLASS } from "@/app/balancer/components/balancer-page-helpers";
import {
  CAPTION_CLASS,
  CARD_TITLE_CLASS,
  EYEBROW_CLASS,
  METRIC_PILL_CLASS,
  ROLE_ICON_COLOR,
} from "@/app/balancer/pickup/pickup-chrome";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { ROLE_LABELS, getRoleIconName } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { MixMemberStats } from "@/services/custom-game.service";

import { LINEUP_ROLES } from "./pickup-lineup";
import {
  STATS_PERIODS,
  formatRecord,
  formatStreak,
  memberLabel,
  type StatsPeriodKey,
} from "./pickup-stats";

/** As deep as the board goes: past twenty names nobody is reading their own row any more. */
const LEADERBOARD_LIMIT = 20;

/** A run of wins reads in the winning team's teal, a run of losses in the warning amber. */
const STREAK_WIN_CLASS =
  "border-[color:color-mix(in_srgb,var(--aqt-teal)_35%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] text-[color:var(--aqt-teal)]";
const STREAK_LOSS_CLASS =
  "border-[color:color-mix(in_srgb,var(--aqt-amber)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_10%,transparent)] text-[color:var(--aqt-amber)]";

type PickupLeaderboardProps = {
  /** Already filtered and ranked by the caller — rendered in the order given. */
  members: MixMemberStats[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  period: StatsPeriodKey;
  onPeriodChange: (period: StatsPeriodKey) => void;
};

/**
 * Who is actually winning these mixes, across every mix the workspace has run
 * rather than inside the one on screen. It reads the same permanent match log
 * the rotation hint does, so a record here and a match in a mix's history can
 * never disagree.
 *
 * The window is the reader's own choice and nothing else on the page depends
 * on it, so it stays local chrome: the page owns which window is picked only
 * because the query key does.
 */
export function PickupLeaderboard({
  members,
  loading,
  error,
  onRetry,
  period,
  onPeriodChange,
}: Readonly<PickupLeaderboardProps>) {
  return (
    <div className={cn(PANEL_CLASS, "flex flex-col")}>
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2 border-b border-[color:var(--aqt-border)] px-4 py-3">
        <div className="min-w-0">
          <div className={EYEBROW_CLASS}>Leaderboard</div>
          <h2 className={cn(CARD_TITLE_CLASS, "mt-1")}>Mix record</h2>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          {STATS_PERIODS.map((item) => (
            <PeriodChip
              key={item.key}
              label={item.label}
              active={item.key === period}
              onClick={() => onPeriodChange(item.key)}
            />
          ))}
        </div>
      </div>

      {error ? (
        <PageStateCard
          state="error"
          title="Unable to load the leaderboard"
          description="Check your connection and try again."
          actionLabel="Retry"
          onAction={onRetry}
          className="border-0 bg-transparent px-4 py-10"
        />
      ) : loading ? (
        <Skeleton className="m-4 h-64 rounded-lg" />
      ) : members.length === 0 ? (
        <PageStateCard
          state="empty"
          title="No mix results yet"
          description="Players appear after 3 recorded matches."
          className="border-0 bg-transparent px-4 py-10"
        />
      ) : (
        <ol
          aria-label="Mix record"
          className="flex flex-col divide-y divide-[color:var(--aqt-border)]"
        >
          {members.slice(0, LEADERBOARD_LIMIT).map((member, index) => (
            <LeaderboardRow key={member.workspace_member_id} rank={index + 1} member={member} />
          ))}
        </ol>
      )}
    </div>
  );
}

/** One window the record can be read in; the same pressed-pill the map-mode filters use. */
function PeriodChip({
  label,
  active,
  onClick,
}: Readonly<{ label: string; active: boolean; onClick: () => void }>) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 shrink-0 items-center rounded-full border px-2.5 text-label transition-colors",
        active
          ? "border-[color:color-mix(in_srgb,var(--aqt-teal)_38%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] text-[color:var(--aqt-teal)]"
          : "border-[color:var(--aqt-border)] bg-white/[0.02] text-[color:var(--aqt-fg-muted)] hover:bg-white/[0.05] hover:text-[color:var(--aqt-fg)]",
      )}
    >
      {label}
    </button>
  );
}

function LeaderboardRow({ rank, member }: Readonly<{ rank: number; member: MixMemberStats }>) {
  const streak = formatStreak(member.streak);
  return (
    <li className="flex items-center gap-2.5 px-4 py-2">
      <span className={cn(CAPTION_CLASS, "w-7 shrink-0 text-right")}>{`#${rank}`}</span>
      <span className="min-w-0 flex-1 truncate text-sm font-medium text-[color:var(--aqt-fg)]">
        {memberLabel(member)}
      </span>
      <span className="flex shrink-0 items-center gap-1">
        {LINEUP_ROLES.map((role) => {
          const tally = member.by_role[role];
          if (tally == null) return null;
          return (
            <span
              key={role}
              className="inline-flex"
              title={`${role} ${tally.wins}–${tally.losses}`}
            >
              <PlayerRoleIcon
                role={getRoleIconName(role)}
                size={14}
                color={ROLE_ICON_COLOR[role]}
                label={`${ROLE_LABELS[role]} ${tally.wins}–${tally.losses}`}
              />
            </span>
          );
        })}
      </span>
      <span className={cn(CAPTION_CLASS, "shrink-0")}>{formatRecord(member)}</span>
      <span className="w-10 shrink-0 text-right text-sm tabular-nums text-[color:var(--aqt-fg-muted)]">
        {`${Math.round(member.win_rate * 100)}%`}
      </span>
      {streak == null ? null : (
        <span
          className={cn(
            METRIC_PILL_CLASS,
            "h-6 shrink-0 px-2",
            member.streak > 0 ? STREAK_WIN_CLASS : STREAK_LOSS_CLASS,
          )}
        >
          {streak}
        </span>
      )}
    </li>
  );
}
