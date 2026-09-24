"use client";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { AlertTriangle, ArrowRight, CheckCircle2, Circle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/kit/StatusPill";
import { EYEBROW_CLASS, TONE_TEXT, type Tone } from "@/components/kit/tone";
import {
  buildChecklist,
  hasChallongeSource,
  type ChecklistItem
} from "@/components/admin/tournament-checklist";
import { cn } from "@/lib/utils";
import { PermissionHiddenNotice } from "./PermissionHiddenNotice";
import type { TournamentReadiness } from "@/types/admin.types";
import type { Tournament } from "@/types/tournament.types";

/** Open items shown here before the reader is sent to the hub's full checklist. */
const MAX_ACTIONS = 4;

/** Draft lifecycle read as a tone. Anything unmapped stays neutral. */
const DRAFT_TONE: Record<string, Tone> = {
  completed: "success",
  live: "info",
  paused: "warning",
  cancelled: "danger"
};

function ActionRow({ item }: Readonly<{ item: ChecklistItem }>) {
  const tone: Tone = item.state === "warn" ? "warning" : "neutral";
  const Icon = item.state === "warn" ? AlertTriangle : Circle;
  const body = (
    <>
      <Icon className={cn("size-3.5 shrink-0", TONE_TEXT[tone])} aria-hidden />
      <span className="min-w-0 flex-1 truncate text-sm text-foreground">{item.label}</span>
      {item.detail ? (
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{item.detail}</span>
      ) : null}
    </>
  );

  // Rows bleed to the card edge (`-mx-6`) so the hover fill spans the card
  // instead of a framed box inside it.
  const shared = "flex items-center gap-2 -mx-6 px-6 py-2.5 transition-colors";

  if (!item.href) {
    return <div className={shared}>{body}</div>;
  }
  return (
    <HoverPrefetchLink
      href={item.href}
      className={cn(
        shared,
        "hover:bg-accent/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
      )}
    >
      {body}
    </HoverPrefetchLink>
  );
}

interface ActiveTournamentReadinessProps {
  /** ANY(tournament.read, team.read) on the workspace — the readiness gate. */
  canRead: boolean;
  tournament: Tournament | null;
  readiness: TournamentReadiness | undefined;
  isLoading: boolean;
  failed: boolean;
}

/**
 * What still blocks the active tournament, plus its registration and team
 * formation state.
 *
 * Reads the same `/admin/tournaments/{id}/readiness` aggregate and the same
 * `buildChecklist` model as the hub's Overview tab, so the dashboard can never
 * disagree with the hub about what is done. The backend masks field groups the
 * reader may not see (`null`), which `buildChecklist` turns into `"no-access"`
 * items — those are filtered out here instead of being shown as work.
 */
export function ActiveTournamentReadiness({
  canRead,
  tournament,
  readiness,
  isLoading,
  failed
}: Readonly<ActiveTournamentReadinessProps>) {
  if (!canRead) {
    return (
      <Card>
        <CardContent className="pt-6">
          <PermissionHiddenNotice
            title="Tournament readiness is hidden"
            permission="tournament read or team read"
          />
        </CardContent>
      </Card>
    );
  }

  // No active tournament: the card above already says so and offers the way out.
  if (!tournament) return null;

  const basePath = `/admin/tournaments/${tournament.id}`;
  const items =
    readiness && !failed
      ? buildChecklist(readiness, {
          basePath,
          schedule: tournament.phase_schedule.map((entry) => entry.status),
          hasChallongeSource: hasChallongeSource(tournament, tournament.stages ?? [])
        })
      : [];

  // "skipped" (not applicable) and "no-access" (masked) items are neither work
  // nor progress, so they stay out of both the list and the denominator.
  const open = items.filter((item) => item.state === "todo" || item.state === "warn");
  const actions = open.slice(0, MAX_ACTIONS);
  const doneCount = items.filter((item) => item.state === "done").length;
  const trackedCount = doneCount + open.length;

  // `registrations_approved` is the team-permission sentinel (D16): null means
  // the whole registration/formation group was masked, not that it is zero.
  const teamAccess = readiness?.registrations_approved != null;
  const draftFormation = readiness?.team_formation === "draft";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle asChild>
            <h2>Next actions</h2>
          </CardTitle>
          <Button
            asChild
            variant="ghost"
            size="sm"
            className="-mt-1.5 shrink-0 text-muted-foreground"
          >
            <HoverPrefetchLink href={`${basePath}/overview`}>
              Full checklist
              <ArrowRight className="size-3.5" aria-hidden />
            </HoverPrefetchLink>
          </Button>
        </div>
        {trackedCount > 0 && (
          <CardDescription className="tabular-nums">
            {doneCount} of {trackedCount} steps done
          </CardDescription>
        )}
      </CardHeader>

      <CardContent className="space-y-4">
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-10 rounded-xl" />
            <Skeleton className="h-10 rounded-xl" />
            <Skeleton className="h-10 rounded-xl" />
          </div>
        ) : failed ? (
          <p className="text-sm text-muted-foreground">
            Readiness could not be loaded. Open the tournament to see its checklist.
          </p>
        ) : actions.length > 0 ? (
          <div className="divide-y divide-border/50">
            {actions.map((item) => (
              <ActionRow key={item.key} item={item} />
            ))}
            {open.length > actions.length && (
              <p className="pt-2.5 text-xs text-muted-foreground">
                <span className="tabular-nums">{open.length - actions.length}</span> more in the
                full checklist
              </p>
            )}
          </div>
        ) : (
          <p className={cn("flex items-center gap-2 text-sm", TONE_TEXT.success)}>
            <CheckCircle2 className="size-4 shrink-0" aria-hidden />
            Every applicable step is done.
          </p>
        )}

        {/* Registration counts as one plain row of figures, not four framed
            tiles inside a framed card; the formation state sits in the same row. */}
        {teamAccess && readiness && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-border/50 pt-4 sm:grid-cols-5">
            <Figure label="Pending" value={readiness.registrations_pending ?? 0} warn />
            <Figure label="Approved" value={readiness.registrations_approved ?? 0} />
            <Figure label="Checked in" value={readiness.registrations_checked_in ?? 0} />
            <Figure label="Ranked" value={readiness.registrations_ranked ?? 0} />
            <div>
              <dt className={EYEBROW_CLASS}>{draftFormation ? "Draft" : "Balancer"}</dt>
              <dd className="mt-1 flex flex-wrap gap-1.5">
                {draftFormation ? (
                  <StatusPill
                    tone={
                      readiness.draft_session_status
                        ? (DRAFT_TONE[readiness.draft_session_status] ?? "neutral")
                        : "neutral"
                    }
                  >
                    {readiness.draft_session_status ?? "No session"}
                  </StatusPill>
                ) : (
                  <>
                    <StatusPill
                      tone={(readiness.pool_need_fix ?? 0) > 0 ? "warning" : "success"}
                      className="tabular-nums"
                    >
                      Pool {readiness.pool_ready ?? 0} ready
                      {(readiness.pool_need_fix ?? 0) > 0
                        ? ` · ${readiness.pool_need_fix} need fixing`
                        : ""}
                    </StatusPill>
                    <StatusPill tone={readiness.balance_saved ? "success" : "neutral"}>
                      {readiness.balance_saved ? "Balance saved" : "Balance not saved"}
                    </StatusPill>
                    {readiness.balance_exported_at && (
                      <StatusPill tone="success">Exported</StatusPill>
                    )}
                  </>
                )}
              </dd>
            </div>
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

/** One figure of the registration row: eyebrow above a tabular number. */
function Figure({
  label,
  value,
  warn = false
}: Readonly<{ label: string; value: number; warn?: boolean }>) {
  return (
    <div>
      <dt className={EYEBROW_CLASS}>{label}</dt>
      <dd
        className={cn(
          "mt-1 text-xl font-semibold tabular-nums",
          warn && value > 0 && TONE_TEXT.warning
        )}
      >
        {value}
      </dd>
    </div>
  );
}
