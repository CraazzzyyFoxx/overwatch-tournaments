"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@craazzzyyfoxx/admin-kit/ui/card";
import { Progress } from "@/components/ui/progress";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import { VoiceChannelList, VoiceCounts, VoiceIssues, VoiceLastSynced } from "./VoiceChannelList";

const TILE_KINDS = ["hub", "team", "swiss_slot"] as const;
/** While the bot is creating or deleting channels the state moves by the second. */
const BUSY_REFRESH_MS = 15_000;
/** Same cadence as the hub's other polled metrics (`hubQueries`). */
const IDLE_REFRESH_MS = 60_000;

/**
 * Overview's read-only view of the tournament's voice channels: how many of
 * each kind are up, what is wrong, and the full list in a drawer. Settings stay
 * on the Discord settings page. No card for a tournament that does not use voice.
 */
export function TournamentVoiceSummary({
  tournamentId,
  canSync
}: Readonly<{ tournamentId: number; canSync: boolean }>) {
  const t = useTranslations("adminTournament.voiceSettings");
  const queryClient = useQueryClient();
  const queryKey = adminQueryKeys.tournamentVoice(tournamentId);
  const [listOpen, setListOpen] = useState(false);

  const statusQuery = useQuery({
    queryKey,
    queryFn: () => adminService.getVoice(tournamentId),
    refetchInterval: (query) =>
      query.state.data?.channels.some((channel) => channel.status === "pending" || channel.status === "deleting")
        ? BUSY_REFRESH_MS
        : IDLE_REFRESH_MS,
    refetchIntervalInBackground: false
  });
  const syncMutation = useMutation({
    mutationFn: () => adminService.syncVoice(tournamentId),
    onSuccess: (next) => {
      queryClient.setQueryData(queryKey, next);
      notify.success(t("syncRequested"));
    }
  });

  const status = statusQuery.data;
  // Channels still being deleted keep the card until they are gone.
  if (!status || (!status.settings.enabled && status.channels.length === 0)) return null;

  const tiles = TILE_KINDS.map((kind) => {
    const channels = status.channels.filter((channel) => channel.kind === kind);
    return { kind, total: channels.length, active: channels.filter((channel) => channel.status === "active").length };
  }).filter(({ total }) => total > 0);

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle>{t("title")}</CardTitle>
          <div className="flex items-center gap-1">
            <VoiceLastSynced status={status} />
            {canSync ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-8"
                aria-label={t("sync")}
                title={t("sync")}
                disabled={syncMutation.isPending}
                onClick={() => syncMutation.mutate()}
              >
                <RefreshCw aria-hidden className={syncMutation.isPending ? "size-4 animate-spin" : "size-4"} />
              </Button>
            ) : null}
            <Button asChild variant="ghost" size="sm">
              <Link href={`/admin/tournaments/${tournamentId}/settings/discord#voice-channels`}>
                {t("openSettings")}
              </Link>
            </Button>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {tiles.length > 0 ? (
            <ul className="grid gap-3 sm:grid-cols-3">
              {tiles.map(({ kind, total, active }) => (
                <li key={kind} className="flex flex-col gap-1 rounded-lg border border-border p-3">
                  <span className="text-xs text-muted-foreground">{t(`groups.${kind}`)}</span>
                  <span className="text-xl font-semibold tabular-nums">
                    {active} / {total}
                  </span>
                  <Progress
                    size="sm"
                    tone={active === total ? "success" : "warning"}
                    value={(active / total) * 100}
                    aria-label={t("activeOf", { kind: t(`groups.${kind}`), active, total })}
                  />
                </li>
              ))}
            </ul>
          ) : (
            <VoiceCounts status={status} />
          )}
          <VoiceIssues status={status} />
          <Button
            type="button"
            variant="link"
            size="sm"
            className="self-start px-0"
            onClick={() => setListOpen(true)}
          >
            {t("allChannels")} →
          </Button>
        </CardContent>
      </Card>

      <Sheet open={listOpen} onOpenChange={setListOpen}>
        <SheetContent variant="panel" className="w-full sm:max-w-md">
          <SheetHeader variant="panel">
            <SheetTitle>{t("drawerTitle")}</SheetTitle>
            <SheetDescription>
              <VoiceLastSynced status={status} />
            </SheetDescription>
          </SheetHeader>
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-5 py-4">
            <VoiceCounts status={status} />
            <VoiceIssues status={status} />
            <VoiceChannelList status={status} />
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
