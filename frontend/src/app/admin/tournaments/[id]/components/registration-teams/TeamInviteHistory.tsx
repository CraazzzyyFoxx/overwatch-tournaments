"use client";

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, LifeBuoy } from "lucide-react";
import { useTranslations } from "next-intl";

import { StatusPill } from "@/components/kit/StatusPill";
import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { useFormatter } from "@/lib/datetime/client";
import { translateRegistrationTeamError } from "@/lib/registration/team-errors";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { cn } from "@/lib/utils";
import registrationTeamService from "@/services/registration-team.service";

import { EXPIRY_STAMP, HISTORY_STATES, inviteTone } from "./model";
import { RosterMark } from "./TeamRosterStrip";

/**
 * One team's whole invite ledger, organizer side.
 *
 * Collapsed and unfetched until asked for: the chips above already answer the
 * usual question, and this read exists for the rarer one — was that slot
 * refused, or did the link merely lapse. The chips cannot answer it because the
 * team read returns only LIVE invites (a terminal row there would hold a roster
 * slot open).
 *
 * Its own component because a hook cannot run inside the team loop, and
 * deliberately local to this feature: the captain's side has a separate one, and
 * sharing would couple two surfaces that ship independently.
 */
export function TeamInviteHistory({
  tournamentId,
  workspaceId,
  teamId,
  meta
}: Readonly<{
  tournamentId: number;
  workspaceId: number;
  teamId: number;
  /** Rendered on the trigger's own line — a second full-width row for one
   *  short counter is the kind of thing that made this panel three screens. */
  meta?: ReactNode;
}>) {
  const t = useTranslations("registrationTeams");
  const tErr = useTranslations("registrationTeams.errors");
  const format = useFormatter();
  const [open, setOpen] = useState(false);

  const historyQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationInviteHistory(workspaceId, teamId),
    queryFn: () => registrationTeamService.listInviteHistoryAdmin(tournamentId, teamId),
    // Nothing pays for the ledger until someone opens it.
    enabled: open
  });

  const history = historyQuery.data;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="flex items-center justify-between gap-2">
        {meta}
        <CollapsibleTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="ml-auto h-6 gap-1 px-1.5 text-caption font-normal text-muted-foreground"
          >
            {t("history.toggle")}
            <ChevronDown
              aria-hidden
              className={cn("size-3.5 transition-transform", open && "rotate-180")}
            />
          </Button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent className="space-y-1 pt-2">
        {historyQuery.isError ? (
          <Alert variant="destructive" role="alert">
            <AlertDescription>
              {translateRegistrationTeamError(tErr, historyQuery.error, t("admin.loadFailed"))}
              <Button type="button" variant="outline" size="sm" className="ml-2" disabled={historyQuery.isFetching} onClick={() => void historyQuery.refetch()}>{t("admin.retry")}</Button>
            </AlertDescription>
          </Alert>
        ) : historyQuery.isLoading ? (
          <Skeleton className="h-12 w-full rounded-md" />
        ) : (
          <>
            {history && (
              <p className="text-xs text-muted-foreground">
                {t("history.cap", { used: history.cap_used, limit: history.cap_limit })}
                {/* Without the reset date "12 of 60" reads as the team's whole
                    lifetime, which is exactly what it stops being once an
                    organizer forgives the count. */}
                {history.cap_reset_at && (
                  <span className="ml-2">
                    {t("history.capReset", {
                      date: format.dateTime(new Date(history.cap_reset_at), EXPIRY_STAMP)
                    })}
                  </span>
                )}
              </p>
            )}
            {history?.items.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t("history.empty")}</p>
            ) : (
              <ul className="space-y-1">
                {history?.items.map((entry) => {
                  const known = HISTORY_STATES.find((candidate) => candidate === entry.state);
                  return (
                    <li key={entry.id} className="flex flex-wrap items-center gap-2 text-xs">
                      <StatusPill tone={inviteTone(entry.state)}>
                        {known ? t(`history.state.${known}`) : entry.state}
                      </StatusPill>
                      {/* The slot is a role, and a role is a glyph here as
                          everywhere else in this feature: spelled out, "Damage"
                          and "Support" doubled the width of every ledger row.
                          `RosterSlotGlyph` still announces the role name. */}
                      <RosterSlotGlyph code={entry.slot_code} size={14} />
                      <span className="text-muted-foreground">
                        {entry.target_battle_tag
                          ? t("invite.targetLabel", { name: entry.target_battle_tag })
                          : t("invite.linkLabel")}
                      </span>
                      {entry.is_substitute && (
                        <RosterMark
                          icon={LifeBuoy}
                          label={t("member.substitute")}
                          className="text-muted-foreground"
                        />
                      )}
                      {entry.invited_at && (
                        <span className="text-muted-foreground">
                          {t("history.issued", {
                            date: format.dateTime(new Date(entry.invited_at), EXPIRY_STAMP)
                          })}
                        </span>
                      )}
                      {entry.answered_at && (
                        <span className="text-muted-foreground">
                          {t("history.answered", {
                            date: format.dateTime(new Date(entry.answered_at), EXPIRY_STAMP)
                          })}
                        </span>
                      )}
                      {/* Same `revoked` state, materially different event: staff
                          pulled the offer, the captain did not. */}
                      {entry.revoked_by_organizer && (
                        <span className="text-muted-foreground">{t("history.byOrganizer")}</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}
