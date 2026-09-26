"use client";

import { useEffect, useState } from "react";
import { notFound, useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Eye, Swords } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { getApiErrorMessage } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import { RETURN_TO_PARAM, withReturnTo } from "@/lib/auth/return-to";
import scrimService from "@/services/scrim.service";
import type { ScrimRoom } from "@/types/scrim.types";

import { PregameRoom } from "@/app/(site)/tournaments/[slug]/pregame/[encounterId]/_components/PregameRoom";
import { Spinner } from "@/components/ui/spinner";
import { scrimQueryKeys } from "@/lib/scrims/query-keys";

/** Where a scrim room hands the viewer back when it is done with them. */
const SCRIM_RETURN_TO = "/scrims";

/** The gate a workspace member sees before the room lets them act. */
function ClaimGate({
  room,
  onClaim,
  onWatch,
  isClaiming
}: Readonly<{
  room: ScrimRoom;
  onClaim: () => void;
  onWatch: () => void;
  isClaiming: boolean;
}>) {
  const t = useTranslations("scrims.claim");
  const openSide = room.home_team.captain_claimed ? room.away_team : room.home_team;

  return (
    <Card className="mx-auto max-w-xl">
      <CardContent className="flex flex-col items-center gap-4 p-6 text-center">
        <Swords aria-hidden className="size-8 text-[color:var(--aqt-teal)]" />
        <div>
          <h1 className="font-onest text-lg font-semibold">{room.label}</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            {t("sides", { home: room.home_team.name, away: room.away_team.name })}
          </p>
        </div>
        <p className="text-sm">{t("prompt", { team: openSide.name })}</p>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button onClick={onClaim} disabled={isClaiming}>
            {isClaiming ? <Spinner /> : null}
            {t("claim", { team: openSide.name })}
          </Button>
          <Button variant="outline" onClick={onWatch} disabled={isClaiming}>
            <Eye aria-hidden className="size-4" />
            {t("watch")}
          </Button>
        </div>
        <p className="text-muted-foreground text-xs">{t("hint")}</p>
      </CardContent>
    </Card>
  );
}

/**
 * One scrim room, addressed by its share token.
 *
 * Three outcomes: a token that names nothing this viewer may see is a 404 (the
 * hidden container answers unknown and not-yours identically, so the client
 * cannot tell them apart either); an unclaimed side offers itself to a
 * workspace member; anything else is the ordinary pre-game room, reused as-is —
 * `PregameRoom` needs only an `encounter_id` and derives the rest.
 */
export default function ScrimRoomPage() {
  const t = useTranslations("scrims.room");
  const params = useParams<{ token: string }>();
  const token = params.token;
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [watching, setWatching] = useState(false);

  const roomQueryKey = scrimQueryKeys.room(token);
  const roomQuery = useQuery({
    queryKey: roomQueryKey,
    queryFn: () => scrimService.getRoom(token),
    enabled: Boolean(token)
  });

  // `PregameRoom` reads its exit target off the URL and has no prop for it, so
  // the param is planted here rather than passed. Without it the room would fall
  // back to `/encounters/<id>` — a page that means nothing for a scrim and 404s
  // for everyone outside the room.
  const hasReturnTo = searchParams?.get(RETURN_TO_PARAM) != null;
  useEffect(() => {
    if (!hasReturnTo && pathname) {
      router.replace(withReturnTo(pathname, SCRIM_RETURN_TO));
    }
  }, [hasReturnTo, pathname, router]);

  const claimMutation = useMutation({
    mutationFn: () => scrimService.claimSide(token),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: roomQueryKey });
      notify.success(t("claimed"));
    },
    onError: (error) => notify.error(getApiErrorMessage(error, t("claimFailed")))
  });

  if (roomQuery.isPending) {
    return <Skeleton className="h-96 w-full rounded-xl" />;
  }

  // A thrown error is a transport failure, never a rejected read: `getRoom`
  // swallows non-ok responses into `null`. Retrying beats 404-ing a captain out
  // of a live room over one dropped request.
  if (roomQuery.isError) {
    return (
      <PageStateCard
        state="error"
        actionLabel={t("retry")}
        onAction={() => void roomQuery.refetch()}
      />
    );
  }

  const room = roomQuery.data;
  if (room == null) {
    notFound();
  }

  if (room.can_claim && !watching) {
    return (
      <ClaimGate
        room={room}
        isClaiming={claimMutation.isPending}
        onClaim={() => claimMutation.mutate()}
        onWatch={() => setWatching(true)}
      />
    );
  }

  // No series report: a scrim publishes no result, and the report form is built
  // from a per-tournament config the scrims container does not have.
  return <PregameRoom encounterId={room.encounter_id} seriesReport={false} />;
}
