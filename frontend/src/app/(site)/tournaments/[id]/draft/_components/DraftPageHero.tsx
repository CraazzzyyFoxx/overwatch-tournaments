"use client";

import type { ReactNode } from "react";

import { Eye, Pause, Radio, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { HeroFrame } from "@/components/site/PageHero";
import { cn, formatDateRange } from "@/lib/utils";
import type { DraftBoard, DraftPresenceState, DraftTeam } from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";
import type { Tournament } from "@/types/tournament.types";

import { teamCrest } from "../_lib/draft-crest";

const MAX_CAPTAIN_TILES = 6;

interface DraftPageHeroProps {
  tournament: Tournament;
  board: DraftBoard;
  /** Kept for API parity with the workspace switch; the compact hero renders identically for both. */
  mode: "captain" | "spectator";
  presence: DraftPresenceState;
  connectionState: RealtimeConnectionState;
  currentUserId: number | null;
}

export function DraftPageHero({
  tournament,
  board,
  presence,
  connectionState,
  currentUserId
}: DraftPageHeroProps) {
  const t = useTranslations("draftRedesign");
  const tc = useTranslations("common");
  const locale = useLocale();
  const session = board.session;
  const current = board.current_pick;
  const onClockTeam = current
    ? board.teams.find((candidate) => candidate.id === current.draft_team_id) ?? null
    : null;
  const completed = board.picks.filter((pick) =>
    ["completed", "autopicked", "skipped"].includes(pick.status)
  ).length;
  const available = board.players.filter((player) => player.status === "available").length;

  const captainTeams = board.teams.filter((team) => team.captain_auth_user_id != null);
  const onlineCaptains = captainTeams.filter(
    (team) => presence.users[team.captain_auth_user_id as number] != null
  ).length;

  const isLive = session.status === "live";
  const StateIcon = session.blocked_reason
    ? ShieldAlert
    : session.status === "paused"
      ? Pause
      : Radio;
  const connected = connectionState === "connected";

  return (
    <HeroFrame>
      <div className="flex flex-col gap-2.5 px-7 py-3.5">
        {/* Top row: breadcrumb + presence */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] tracking-[0.05em] text-[color:var(--aqt-fg-faint)]">
            <Link href="/tournaments" className="transition-colors hover:text-[color:var(--aqt-teal)]">
              {tc("tournaments")}
            </Link>
            <span aria-hidden className="opacity-45">
              /
            </span>
            <span>#{tournament.number}</span>
            <span aria-hidden className="opacity-45">
              ·
            </span>
            <span>{formatDateRange(tournament.start_date, tournament.end_date, locale)}</span>
          </div>

          <div
            className="ml-auto flex flex-wrap items-center gap-3"
            role="status"
            aria-live="polite"
          >
            <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
              {t("captain")}
            </span>
            <div className="flex">
              {captainTeams.slice(0, MAX_CAPTAIN_TILES).map((team, index) => (
                <CaptainTile
                  key={team.id}
                  team={team}
                  index={index}
                  online={presence.users[team.captain_auth_user_id as number] != null}
                  isYou={currentUserId != null && team.captain_auth_user_id === currentUserId}
                  onlineLabel={t("captainOnline")}
                  offlineLabel={t("captainOffline")}
                  youLabel={t("you")}
                />
              ))}
              {captainTeams.length > MAX_CAPTAIN_TILES ? (
                <span className="-ml-1.5 grid h-[22px] w-[22px] place-items-center rounded-lg bg-[color:var(--aqt-card-2)] font-mono text-[10px] text-[color:var(--aqt-fg-muted)] ring-2 ring-[color:var(--aqt-bg)]">
                  +{captainTeams.length - MAX_CAPTAIN_TILES}
                </span>
              ) : null}
            </div>
            <span className="text-xs text-[color:var(--aqt-fg-muted)]">
              {t("onlineCount", { n: onlineCaptains, total: captainTeams.length })}
            </span>

            <span aria-hidden className="h-4 w-px bg-[color:var(--aqt-border-2)]" />

            <span className="inline-flex items-center gap-1.5 text-xs text-[color:var(--aqt-fg-muted)]">
              <Eye className="h-3.5 w-3.5 text-[color:var(--aqt-teal)]" aria-hidden />
              {t("anonymousViewers", { count: presence.anonymous_viewer_count })}
            </span>

            <span aria-hidden className="h-4 w-px bg-[color:var(--aqt-border-2)]" />

            <span
              className={cn(
                "inline-flex items-center gap-1.5 text-[11px]",
                connected ? "text-[color:var(--aqt-support)]" : "text-[color:var(--aqt-warm)]"
              )}
            >
              <span
                aria-hidden
                className="h-1.5 w-1.5 rounded-full"
                style={
                  connected
                    ? { background: "var(--aqt-support)", boxShadow: "0 0 6px var(--aqt-support)" }
                    : { background: "var(--aqt-warm)" }
                }
              />
              {t(`connection.${connectionState}`)}
            </span>
          </div>
        </div>

        {/* Main row: title + meta on the left, compact stats on the right */}
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex min-w-0 flex-wrap items-center gap-x-3.5 gap-y-2">
            <h1 className="aqt-hero-title min-w-0 font-onest text-[clamp(1.3rem,2.1vw,1.75rem)] font-semibold leading-[1.05] tracking-[-0.02em]">
              {tournament.name}
            </h1>
            <div className="flex flex-wrap gap-1.5">
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] font-semibold",
                  isLive
                    ? "border-[color:var(--aqt-teal)]/35 bg-[color:var(--aqt-teal)]/12 text-[color:var(--aqt-teal)]"
                    : "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-amber)]"
                )}
              >
                {isLive ? (
                  <span
                    aria-hidden
                    className="h-1.5 w-1.5 rounded-full bg-[color:var(--aqt-teal)] animate-pulse motion-reduce:animate-none"
                    style={{ boxShadow: "0 0 8px var(--aqt-teal)" }}
                  />
                ) : (
                  <StateIcon className="h-3.5 w-3.5" aria-hidden />
                )}
                {t(`status.${session.status}`)}
              </span>
              <MetaPill label={t("format")} value={session.format} />
              <MetaPill label={t("teams")} value={board.teams.length} />
              <MetaPill label={t("rosterSize")} value={session.team_size} />
            </div>
          </div>

          <div className="ml-auto flex items-center gap-6">
            <HStat label={t("teams")} value={board.teams.length} />
            <HStat label={t("availablePool")} value={available} />
            <HStat label={t("progress")} value={`${completed}/${board.picks.length}`} />
            <HStat
              label={t("onClock")}
              value={onClockTeam?.name ?? "—"}
              valueClassName="inline-block max-w-[9rem] truncate align-bottom text-[17px] text-[color:var(--aqt-teal)]"
            />
          </div>
        </div>
      </div>
    </HeroFrame>
  );
}

function CaptainTile({
  team,
  index,
  online,
  isYou,
  onlineLabel,
  offlineLabel,
  youLabel
}: {
  team: DraftTeam;
  index: number;
  online: boolean;
  isYou: boolean;
  onlineLabel: string;
  offlineLabel: string;
  youLabel: string;
}) {
  const { initial, hue } = teamCrest(team);
  const label = `${team.name}${isYou ? ` (${youLabel})` : ""} — ${online ? onlineLabel : offlineLabel}`;
  return (
    <span
      title={label}
      aria-label={label}
      className={cn(
        "relative grid h-[22px] w-[22px] place-items-center rounded-lg text-[10px] font-bold ring-2 ring-[color:var(--aqt-bg)]",
        index > 0 && "-ml-1.5",
        !online && "opacity-45"
      )}
      style={{ background: `hsl(${hue} 55% 22%)`, color: `hsl(${hue} 70% 72%)` }}
    >
      {initial}
      <span
        aria-hidden
        className="absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full border border-[color:var(--aqt-bg)]"
        style={
          online
            ? { background: "var(--aqt-support)", boxShadow: "0 0 5px var(--aqt-support)" }
            : { background: "var(--aqt-fg-faint)" }
        }
      />
    </span>
  );
}

function MetaPill({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5 py-1 text-[11.5px]">
      <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">
        {label}
      </span>
      <span className="font-semibold text-[color:var(--aqt-fg)]">{value}</span>
    </span>
  );
}

function HStat({
  label,
  value,
  valueClassName
}: {
  label: ReactNode;
  value: ReactNode;
  valueClassName?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[9px] font-bold uppercase tracking-[0.13em] text-[color:var(--aqt-fg-faint)]">
        {label}
      </span>
      <span
        className={cn(
          "text-[19px] font-semibold leading-none tabular-nums text-[color:var(--aqt-fg)]",
          valueClassName
        )}
      >
        {value}
      </span>
    </div>
  );
}
