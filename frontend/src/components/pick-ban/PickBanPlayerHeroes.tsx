"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { DisciplineWidget } from "@/disciplines/DisciplineWidget";
import { loadMatchUI } from "@/disciplines/registry/match";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import encounterService from "@/services/encounter.service";

export function PickBanPlayerHeroes({
  playerId,
  matchId
}: Readonly<{ playerId: number; matchId: number | null }>) {
  const t = useTranslations("pickBan.room.playerHeroes");
  const history = useQuery({
    queryKey: encounterQueryKeys.matchDetail(matchId),
    queryFn: () => encounterService.getMatch(matchId!),
    enabled: matchId != null
  });
  const match = history.data;
  const metadata = useDisciplineMetadata(match?.workspace_id ?? "all", match?.discipline ?? null);
  // The target id is a tournament registration, not an observed member: it names the global player through the
  // roster of the source team its participation drew from.
  const userId =
    match?.encounter?.teams
      ?.flatMap((seat) => seat.team?.players ?? [])
      .find((candidate) => candidate.id === playerId)?.user_id ?? null;

  const status = (text: string) => (
    <p role="status" className="text-xs text-[color:var(--aqt-fg-muted)]">
      {text}
    </p>
  );
  const retry = (refetch: () => unknown, busy: boolean) => (
    <div className="flex flex-wrap items-center gap-2">
      {status(t("error"))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={busy}
        onClick={() => void refetch()}
      >
        {t("retry")}
      </Button>
    </div>
  );

  let body;
  if (matchId == null) {
    body = <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("noLog")}</p>;
  } else if (history.isPending || (match && metadata.isPending)) {
    body = (
      <div role="status" className="flex flex-wrap gap-2">
        <span className="sr-only">{t("loading")}</span>
        {[0, 1, 2].map((chip) => (
          <Skeleton key={chip} aria-hidden className="h-9 w-24 rounded-lg" />
        ))}
      </div>
    );
  } else if (history.isError) {
    body = retry(history.refetch, history.isFetching);
  } else if (metadata.isError) {
    body = retry(metadata.refetch, metadata.isFetching);
  } else if (match && metadata.data) {
    body = (
      <DisciplineWidget
        discipline={match.discipline}
        load={loadMatchUI}
        slot="matchCharacters"
        capabilities={metadata.data.discipline.capabilities}
        props={{ match, userId, metadata: metadata.data }}
        fallback={<p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("empty")}</p>}
      />
    );
  }

  return <div className="min-w-0 px-3 pb-2.5">{body}</div>;
}
