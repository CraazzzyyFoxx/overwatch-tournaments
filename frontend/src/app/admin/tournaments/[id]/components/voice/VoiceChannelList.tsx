"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronRight } from "lucide-react";

import { CopyButton } from "@craazzzyyfoxx/admin-kit/kit/Clipboard";
import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { FilterChip, FilterChipGroup } from "@craazzzyyfoxx/admin-kit/ui/filter-chip";
import { SearchField } from "@craazzzyyfoxx/admin-kit/ui/search-field";
import { StatusDot } from "@craazzzyyfoxx/admin-kit/ui/status-dot";
import type { Tone } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { VoiceStatus } from "@/types/admin.types";

type VoiceChannel = VoiceStatus["channels"][number];
type VoiceKind = VoiceChannel["kind"];

/** Group order: the hub players gather in first, then where they are moved to. */
export const VOICE_KINDS: VoiceKind[] = ["hub", "team", "swiss_slot", "category"];
const STATUSES: VoiceChannel["status"][] = ["active", "pending", "planned", "deleting"];
const FILTERS = ["all", "team", "swiss_slot", "attention"] as const;
type Filter = (typeof FILTERS)[number];

const STATUS_TONE: Record<VoiceChannel["status"], Tone> = {
  active: "success",
  pending: "warning",
  deleting: "warning",
  planned: "neutral"
};

const ISSUE_KEYS = ["guild_not_found", "category_not_found", "category_overflow"] as const;
const MISSING_PERMISSION_PREFIX = "missing_permission:";

/** Names of players without a linked Discord, by team id (`null`: no team). */
function missingByTeam(status: VoiceStatus, unnamed: string): Map<number | null, string[]> {
  const byTeam = new Map<number | null, string[]>();
  for (const warning of status.warnings) {
    const names = byTeam.get(warning.team_id) ?? [];
    names.push(warning.name ?? unnamed);
    byTeam.set(warning.team_id, names);
  }
  return byTeam;
}

/** "24 channels · 21 active · 2 pending": the whole state in one line. */
export function VoiceCounts({ status }: Readonly<{ status: VoiceStatus }>) {
  const t = useTranslations("adminTournament.voiceSettings");
  const parts = STATUSES.map((state) => ({
    state,
    count: status.channels.filter((channel) => channel.status === state).length
  })).filter(({ count }) => count > 0);

  return (
    <p className="text-sm">
      <span className="font-medium tabular-nums">{t("channelCount", { count: status.channels.length })}</span>
      {parts.map(({ state, count }) => (
        <span key={state} className="text-muted-foreground tabular-nums">
          {" · "}
          {t(`statusCounts.${state}`, { count })}
        </span>
      ))}
    </p>
  );
}

export function VoiceLastSynced({ status }: Readonly<{ status: VoiceStatus }>) {
  const t = useTranslations("adminTournament.voiceSettings");
  const format = useFormatter();
  return (
    <span className="text-xs text-muted-foreground">
      {status.last_synced_at
        ? t("lastSynced", {
            time: format.dateTime(new Date(status.last_synced_at), { dateStyle: "medium", timeStyle: "short" })
          })
        : t("neverSynced")}
    </span>
  );
}

/** Whether `VoiceIssues` has anything to say, for a parent that frames it. */
export function hasVoiceIssues(status: VoiceStatus): boolean {
  return !status.guild_linked || status.sync_issues.length > 0 || status.warnings.length > 0;
}

/** What stops the bot from doing its job: no server, sync issues, players it cannot move. */
export function VoiceIssues({ status }: Readonly<{ status: VoiceStatus }>) {
  const t = useTranslations("adminTournament.voiceSettings");

  const issueLabel = (code: string) => {
    if (code.startsWith(MISSING_PERMISSION_PREFIX)) {
      return t("issues.missing_permission", { permission: code.slice(MISSING_PERMISSION_PREFIX.length) });
    }
    return (ISSUE_KEYS as readonly string[]).includes(code)
      ? t(`issues.${code as (typeof ISSUE_KEYS)[number]}`)
      : code;
  };
  // Teamed players are named on their team's row; only the teamless have no row to sit on.
  const teamless = missingByTeam(status, t("unnamedPlayer")).get(null);

  if (!hasVoiceIssues(status)) return null;

  return (
    <div className="flex flex-col gap-1 text-sm">
      {!status.guild_linked ? (
        <p role="status" className="text-warning">
          {t("guildNotLinked")}
        </p>
      ) : null}
      {status.sync_issues.length > 0 ? (
        <ul className="flex flex-col gap-1 text-warning" aria-label={t("issuesTitle")}>
          {status.sync_issues.map((issue) => (
            <li key={`${issue.code}:${issue.detail ?? ""}`}>
              {issueLabel(issue.code)}
              {issue.detail ? ` (${issue.detail})` : ""}
            </li>
          ))}
        </ul>
      ) : null}
      {status.warnings.length > 0 ? (
        <p>
          <span className="text-warning">{t("withoutDiscord", { count: status.warnings.length })}</span>{" "}
          <span className="text-xs text-muted-foreground">{t("warningsHint")}</span>
        </p>
      ) : null}
      {teamless ? (
        <p className="text-xs text-muted-foreground">
          {t("noTeam")}: {teamless.join(", ")}
        </p>
      ) : null}
    </div>
  );
}

/**
 * The tournament's voice channels, grouped by kind. A tournament can hold 20+
 * team channels, so teams sit two to a row in a wide card, the list filters and
 * searches, and `previewCount` caps the teams shown until asked for the rest
 * (round lobbies then start collapsed too). Without it every group is open: the
 * drawer scrolls on its own.
 */
export function VoiceChannelList({
  status,
  previewCount
}: Readonly<{ status: VoiceStatus; previewCount?: number }>) {
  const t = useTranslations("adminTournament.voiceSettings");
  const tc = useTranslations("common");
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false);

  if (status.channels.length === 0) {
    return <EmptyNote size="sm">{t("noChannels")}</EmptyNote>;
  }

  const missing = missingByTeam(status, t("unnamedPlayer"));
  // A team channel's slot is `team:<id>`; the warnings only carry that id.
  const missingOf = (channel: VoiceChannel) =>
    channel.kind === "team" ? missing.get(Number(channel.slot_key.slice("team:".length))) : undefined;
  const matches = (channel: VoiceChannel, by: Filter) =>
    by === "all" ||
    (by === "attention" ? channel.status !== "active" || missingOf(channel) !== undefined : channel.kind === by);
  const countOf = (by: Filter) => status.channels.filter((channel) => matches(channel, by)).length;

  const needle = query.trim().toLocaleLowerCase();
  const visible = status.channels.filter(
    (channel) =>
      matches(channel, filter) &&
      (needle === "" || (channel.name ?? channel.slot_key).toLocaleLowerCase().includes(needle))
  );
  const capping = previewCount !== undefined && filter === "all" && needle === "";

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <FilterChipGroup label={t("filtersLabel")}>
          {FILTERS.filter((by) => by === "all" || countOf(by) > 0).map((by) => (
            <FilterChip key={by} active={filter === by} count={countOf(by)} onClick={() => setFilter(by)}>
              {t(`filters.${by}`)}
            </FilterChip>
          ))}
        </FilterChipGroup>
        <SearchField
          label={t("search")}
          placeholder={t("search")}
          value={query}
          onValueChange={setQuery}
          containerClassName="w-full @lg:ms-auto @lg:w-48"
        />
      </div>

      {visible.length === 0 ? <EmptyNote size="sm">{tc("noResults")}</EmptyNote> : null}

      {VOICE_KINDS.map((kind) => {
        const rows = visible.filter((channel) => channel.kind === kind);
        if (rows.length === 0) return null;
        const capped = capping && kind === "team" && !expanded ? rows.slice(0, previewCount) : rows;
        return (
          <details key={kind} open={!(capping && kind === "swiss_slot")} className="group/voice flex flex-col">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 py-1 text-xs font-medium text-muted-foreground [&::-webkit-details-marker]:hidden">
              <ChevronRight aria-hidden className="size-3.5 transition-transform group-open/voice:rotate-90" />
              {t(`groups.${kind}`)}
              <span className="tabular-nums">· {rows.length}</span>
            </summary>
            <ul className={cn("mt-1 grid gap-1.5", kind === "team" && "@xl:grid-cols-2")}>
              {capped.map((channel) => (
                <ChannelRow key={channel.slot_key} channel={channel} missing={missingOf(channel)} />
              ))}
            </ul>
            {capping && kind === "team" && previewCount !== undefined && rows.length > previewCount ? (
              <Button
                type="button"
                variant="link"
                size="sm"
                className="self-start px-0"
                onClick={() => setExpanded((open) => !open)}
              >
                {expanded ? t("showLess") : t("showMore", { count: rows.length - previewCount })}
              </Button>
            ) : null}
          </details>
        );
      })}
    </div>
  );
}

function ChannelRow({ channel, missing }: Readonly<{ channel: VoiceChannel; missing: string[] | undefined }>) {
  const t = useTranslations("adminTournament.voiceSettings");
  const transient = channel.status === "pending" || channel.status === "deleting";
  return (
    <li className="flex min-w-0 flex-col justify-center gap-0.5 rounded-md border border-border/60 px-3 py-1">
      <div className="flex min-h-7 items-center gap-2 text-sm">
        <StatusDot tone={STATUS_TONE[channel.status]} pulse={transient} />
        <span className="min-w-0 flex-1 truncate font-medium">{channel.name ?? channel.slot_key}</span>
        {/* An active channel is the norm: its state is for screen readers, the dot says it to the eye. */}
        <span className={cn("shrink-0 text-xs text-muted-foreground", channel.status === "active" && "sr-only")}>
          {t(`statuses.${channel.status}`)}
        </span>
        {channel.discord_channel_id ? <CopyButton value={channel.discord_channel_id} /> : null}
      </div>
      {missing ? (
        <p className="text-xs text-warning">{t("teamWithoutDiscord", { names: missing.join(", ") })}</p>
      ) : null}
    </li>
  );
}
