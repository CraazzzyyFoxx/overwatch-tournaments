"use client";

import { useQuery } from "@tanstack/react-query";
import { History, Inbox } from "lucide-react";
import { useTranslations } from "next-intl";

import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { translateRegistrationTeamError } from "@/lib/registration-team-errors";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import registrationTeamService from "@/services/registration-team.service";

interface InviteHistorySectionProps {
  workspaceId: number;
  teamId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * The states the server can send. Listed rather than inferred so an unrecognised
 * one renders as itself: a sixth state must not turn a row into a raw
 * `registrationTeams.history.state.<x>` key path.
 *
 * `RegistrationTeamsBrowser.tsx` keeps its own copy on purpose — the two
 * sections are deliberately uncoupled — and a test pins that the lists agree.
 */
const HISTORY_STATES = ["pending", "accepted", "declined", "revoked", "expired"] as const;

/** How close to the ceiling still counts as a warning worth showing. */
const CAP_WARNING_MARGIN = 5;

/**
 * Every invite the team ever issued, plus the cap standing that explains a
 * refusal at the ceiling — as a right-hand drawer.
 *
 * A drawer rather than an inline collapsible: this is a ledger nobody reads
 * while managing a roster, and expanding it in place pushed the card's own
 * actions down and buried the roster under a second list. The same reasoning
 * `AuditTrailSheet` already applies to the admin change history.
 *
 * The read is still gated on `open`, so a closed drawer costs nothing: the team
 * payload already carries the live invites, and this list only answers a
 * question the captain has to ask — was that offer declined, or did the link
 * merely lapse?
 *
 * The parent owns `open` because it must force the drawer open when an invite is
 * refused with `invite_cap_reached`. The cap block is pinned above the scroll
 * area for exactly that case: it is the thing the refusal came here to explain,
 * so it must not be something a long ledger can scroll out of view.
 */
export default function InviteHistorySection({
  workspaceId,
  teamId,
  open,
  onOpenChange
}: Readonly<InviteHistorySectionProps>) {
  const t = useTranslations("registrationTeams");
  const tErrors = useTranslations("registrationTeams.errors");

  const historyQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationInviteHistory(workspaceId, teamId),
    queryFn: () => registrationTeamService.listInviteHistory(teamId),
    enabled: open
  });

  const history = historyQuery.data;
  const capNearby = history != null && history.cap_used >= history.cap_limit - CAP_WARNING_MARGIN;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      {/* `asChild` so Radix owns the dialog wiring (`aria-haspopup`,
          `aria-expanded`, `aria-controls`) instead of this hand-rolling a
          disclosure's ARIA for something that is now a modal. */}
      <SheetTrigger asChild>
        <Button type="button" variant="ghost" size="sm">
          <History className="size-4" aria-hidden />
          {t("history.toggle")}
        </Button>
      </SheetTrigger>

      <SheetContent className="flex w-full flex-col gap-0 p-0 sm:max-w-lg">
        <SheetHeader className="space-y-1 border-b border-[color:var(--aqt-border)] px-5 py-4 text-left">
          <SheetTitle className="flex items-center gap-2 text-base">
            <History aria-hidden className="size-4 shrink-0 text-[color:var(--aqt-fg-muted)]" />
            {t("history.toggle")}
          </SheetTitle>
          <SheetDescription>{t("history.hint")}</SheetDescription>
        </SheetHeader>

        {history && (
          <div className="grid gap-0.5 border-b border-[color:var(--aqt-border)] px-5 py-3">
            <p className="text-xs text-[color:var(--aqt-fg-muted)]">
              {t("history.cap", { used: history.cap_used, limit: history.cap_limit })}
            </p>
            {/* Without this, "12 of 60" reads as the team's whole lifetime when
                an organizer has already moved the counter's floor. */}
            {history.cap_reset_at && (
              <p className="text-xs text-[color:var(--aqt-fg-muted)]">
                {t("history.capReset", {
                  date: new Date(history.cap_reset_at).toLocaleDateString()
                })}
              </p>
            )}
            {capNearby && (
              <p className="text-xs text-[color:var(--aqt-amber)]">{t("history.capNearby")}</p>
            )}
          </div>
        )}

        {/* `overscroll-contain` keeps a flick at the end of the ledger from
            scrolling the page underneath the drawer. */}
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-4">
          {historyQuery.isLoading && (
            <div className="grid gap-2">
              {Array.from({ length: 4 }, (_, index) => (
                <Skeleton key={index} className="h-12 w-full rounded-lg" />
              ))}
            </div>
          )}

          {historyQuery.isError && (
            <p className="text-sm text-[color:var(--aqt-fg-muted)]">
              {translateRegistrationTeamError(tErrors, historyQuery.error)}
            </p>
          )}

          {/* An opened drawer with nothing in it must say so: a blank panel
              looks like a read that never finished. */}
          {history && history.items.length === 0 && (
            <div className="py-8 text-center">
              <Inbox className="mx-auto size-6 text-[color:var(--aqt-fg-dim)]" aria-hidden />
              <p className="mt-3 text-sm text-[color:var(--aqt-fg-muted)]">{t("history.empty")}</p>
            </div>
          )}

          {history && history.items.length > 0 && (
            <ul className="divide-y divide-[color:var(--aqt-border)]">
              {/* Newest-first already, ordered by the server. */}
              {history.items.map((entry) => {
                // `.find` narrows to the literal union the typed translator
                // accepts; a membership test against a Record would not.
                const known = HISTORY_STATES.find((candidate) => candidate === entry.state);
                return (
                  <li key={entry.id} className="grid gap-1 py-3 first:pt-0 last:pb-0">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <RosterSlotGlyph code={entry.slot_code} />
                      <span className="font-medium">
                        {known ? t(`history.state.${known}`) : entry.state}
                      </span>
                      <span className="text-[color:var(--aqt-fg-muted)]">
                        {entry.target_battle_tag
                          ? t("invite.targetLabel", { name: entry.target_battle_tag })
                          : t("invite.linkLabel")}
                      </span>
                    </div>

                    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-[color:var(--aqt-fg-muted)]">
                      {entry.is_substitute && <span>{t("member.substitute")}</span>}
                      {entry.invited_at && (
                        <span>
                          {t("history.issued", {
                            date: new Date(entry.invited_at).toLocaleDateString()
                          })}
                        </span>
                      )}
                      {entry.answered_at && (
                        <span>
                          {t("history.answered", {
                            date: new Date(entry.answered_at).toLocaleDateString()
                          })}
                        </span>
                      )}
                      {/* Same `revoked` state, materially different event: the
                          captain did not do this one. */}
                      {entry.revoked_by_organizer && <span>{t("history.byOrganizer")}</span>}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
