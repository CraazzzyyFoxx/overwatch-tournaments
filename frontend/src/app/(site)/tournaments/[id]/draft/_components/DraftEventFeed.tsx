"use client";

import { Bot, CheckCircle2 } from "lucide-react";
import { useTranslations } from "next-intl";

import type { DraftPick, DraftPlayer, DraftTeam } from "@/types/draft.types";

import { buildDraftEventFeed } from "../_lib/draft-workspace-model";

interface DraftEventFeedProps {
  picks: DraftPick[];
  teams: DraftTeam[];
  players: DraftPlayer[];
}

export function DraftEventFeed({ picks, teams, players }: DraftEventFeedProps) {
  const t = useTranslations("draftRedesign");
  const feed = buildDraftEventFeed(
    picks,
    new Map(teams.map((team) => [team.id, team.name])),
    new Map(players.map((player) => [player.id, player.battle_tag ?? `#${player.id}`]))
  );
  return (
    <section aria-labelledby="event-feed-heading">
      <div className="border-b border-[color:var(--aqt-border)] pb-3">
        <h2 id="event-feed-heading" className="text-sm font-medium text-[color:var(--aqt-fg-muted)]">{t("eventFeed")}</h2>
      </div>
      <ol className="mt-2 divide-y divide-[color:var(--aqt-border)]">
        {feed.slice(0, 12).map((item) => (
          <li key={item.pickId} className="flex min-h-12 items-center gap-3 py-2 text-sm">
            {item.autopick ? <Bot className="h-4 w-4 text-[color:var(--aqt-warm)]" /> : <CheckCircle2 className="h-4 w-4 text-[color:var(--aqt-support)]" />}
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{item.playerName}</span>
              <span className="block truncate text-xs text-[color:var(--aqt-fg-muted)]">{item.teamName} · {item.role ? t(`roles.${item.role}`) : t("roleUnknown")}</span>
            </span>
            <span className="font-mono text-xs text-[color:var(--aqt-fg-faint)]">#{item.overallNo}</span>
          </li>
        ))}
        {feed.length === 0 && <li className="py-5 text-sm text-[color:var(--aqt-fg-muted)]">{t("eventFeedEmpty")}</li>}
      </ol>
    </section>
  );
}

