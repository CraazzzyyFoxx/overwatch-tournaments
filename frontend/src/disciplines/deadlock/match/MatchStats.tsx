"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { DlProvider } from "@deadlock-api/ui-react";
import { fetchItems, Language } from "@deadlock-api/ui-core/dist/components/index.js";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { SlotProps } from "@/disciplines/types";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { cn } from "@/lib/utils";
import encounterService from "@/services/encounter.service";
import Breakdown from "./Breakdown";
import { PRESET_ORDER, type PresetKey } from "./columns";
import Lanes from "./Lanes";
import { minutesOf, readFeed, readTeams, sampleTimeAt } from "./model";
import { FAINT, ItemsContext, formatClock, sideVars, type ItemAssets } from "./parts";
import Ribbon from "./Ribbon";
import Rosters from "./Rosters";
import Scoreboard from "./Scoreboard";
import Timeline from "./Timeline";

type Tab = "rosters" | "tables" | "breakdown" | "lanes" | "timeline";

/** What the views read when the asset list failed: no item is known, so builds and sources draw nothing. */
const NO_ASSETS: ItemAssets = { byId: new Map(), byClass: new Map() };

/**
 * The Deadlock view of a match: the sticky ribbon (the whole match, and the moment the rest shows), then the teams
 * side by side with builds and player panels, the full table, the breakdown, the lanes and the timeline. Items are
 * drawn by deadlock-api's own components from its asset list in the page language, read once.
 */
export default function MatchStats({ match }: Readonly<SlotProps["matchStats"]>) {
  const t_ = useTranslations();
  const language = useLocale() === "ru" ? Language.RU : Language.EN;
  const [tab, setTab] = useState<Tab>("rosters");
  const [preset, setPreset] = useState<PresetKey>("overview");
  const [moment, setMoment] = useState<number | null>(null);

  const teams = useMemo(() => readTeams(match), [match]);
  const events = useQuery({
    queryKey: encounterQueryKeys.matchEvents(match.id),
    queryFn: () => encounterService.getMatchKillFeed(match.id),
    staleTime: 5 * 60_000
  });
  const items = useQuery({
    queryKey: encounterQueryKeys.deadlockItems(language),
    queryFn: async (): Promise<ItemAssets> => {
      const list = await fetchItems(language);
      return {
        byId: new Map(list.map((item) => [item.id, item])),
        byClass: new Map(list.map((item) => [item.class_name, item]))
      };
    },
    staleTime: Infinity
  });
  // A failed read still renders the rest (an empty feed); the alert above the tabs says what is missing.
  const feed = useMemo(
    () => (teams && (events.data || events.isError) ? readFeed(events.data?.events ?? [], teams) : null),
    [teams, events.data, events.isError]
  );

  if (!teams) return null;
  const durationS = match.duration_s ?? 0;
  const minutes = minutesOf(match.duration_s);
  const status = events.isPending ? "pending" : events.isError ? "error" : "success";
  // The moment on screen; `null` is the end of the match, the view's resting state.
  const t = moment === null ? durationS : Math.min(moment, durationS);
  const onTime = (value: number) => setMoment(value >= durationS ? null : Math.max(0, value));
  const sides = sideVars(teams);
  const atEnd = t >= durationS || !feed;
  const sampled = feed && !atEnd ? sampleTimeAt(feed, t) : null;

  return (
    <DlProvider language={language} tooltipTrigger="hover">
      <ItemsContext.Provider value={items.data ?? (items.isError ? NO_ASSETS : undefined)}>
        <div style={sides} className="flex flex-col gap-4">
          {items.isError || events.isError ? (
            <p role="alert" className="text-caption text-[color:var(--aqt-rose)]">
              {t_(items.isError ? "matches.deadlock.itemsError" : "matches.timeline.error")}
            </p>
          ) : null}
          <Ribbon teams={teams} feed={feed} durationS={durationS} t={t} onTime={onTime} />
          <Tabs value={tab} onValueChange={(value) => setTab(value as Tab)} className="flex flex-col gap-4">
            <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2 border-b border-[color:var(--aqt-border)]">
              <TabsList className="max-w-full overflow-x-auto shadow-none sm:w-auto">
                <TabsTrigger value="rosters">{t_("matches.deadlock.tab.rosters")}</TabsTrigger>
                <TabsTrigger value="tables">{t_("matches.deadlock.tab.table")}</TabsTrigger>
                <TabsTrigger value="breakdown">{t_("matches.tab.breakdown")}</TabsTrigger>
                <TabsTrigger value="lanes">{t_("matches.deadlock.tab.lanes")}</TabsTrigger>
                <TabsTrigger value="timeline">{t_("matches.tab.timeline")}</TabsTrigger>
              </TabsList>
              {tab === "tables" ? (
                <ToggleGroup
                  value={preset}
                  onValueChange={(value) => value && setPreset(value as PresetKey)}
                  variant="pill"
                  size="sm"
                  aria-label={t_("matches.scoreboard.columns")}
                  className="mb-1.5 max-w-full overflow-x-auto"
                >
                  {PRESET_ORDER.map((key) => (
                    <ToggleGroupItem key={key} value={key} className="shrink-0">
                      {t_(`matches.deadlock.preset.${key}`)}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              ) : null}
            </div>
            {tab === "rosters" || tab === "tables" ? (
              <p className={cn("m-0 -mt-2 text-caption", FAINT)} aria-live="polite">
                {atEnd
                  ? t_("matches.deadlock.scoreboard.final")
                  : t_("matches.deadlock.scoreboard.at", { time: formatClock(t), sample: formatClock(sampled ?? 0) })}
              </p>
            ) : null}

            <TabsContent value="rosters">
              <Rosters teams={teams} feed={feed} durationS={durationS} t={t} />
            </TabsContent>
            <TabsContent value="tables">
              <Scoreboard teams={teams} feed={feed} minutes={minutes} durationS={durationS} t={t} preset={preset} />
            </TabsContent>
            <TabsContent value="breakdown">
              <Breakdown teams={teams} feed={feed} t={t} durationS={durationS} onTime={onTime} />
            </TabsContent>
            <TabsContent value="lanes">
              <Lanes teams={teams} feed={feed} durationS={durationS} onTime={onTime} />
            </TabsContent>
            <TabsContent value="timeline">
              <Timeline
                teams={teams}
                feed={feed}
                status={status}
                onRetry={() => void events.refetch()}
                durationS={durationS}
                t={t}
                onTime={onTime}
              />
            </TabsContent>
          </Tabs>
        </div>
      </ItemsContext.Provider>
    </DlProvider>
  );
}
