"use client";

import { useId } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { DivisionGridVersion } from "@/types/workspace.types";

import { bandsFromTiers, type Ladder } from "./editor/draftReducer";
import { LadderBar } from "./LadderBar";
import { VERSION_PILL, versionState } from "./versionStatus";

export interface VersionHistoryProps {
  versions: DivisionGridVersion[];
  activeVersionId: number | null;
  /** The grid's discipline's native ladder; `null` when it has none (no ladder cut is drawn). */
  ladder: Ladder | null;
  /**
   * Tournaments pinned to each version, from the active version's readiness
   * payload. `null` while that is unknown (nothing active, or still loading):
   * a missing entry then means "unknown", not "none".
   */
  tournamentCounts: Record<number, number> | null;
  /**
   * Whether a published version may be activated right now, by id. `undefined`
   * while its readiness is loading; absent for versions that are not
   * candidates (drafts, archived, the active one). A candidate's Activate is
   * shown, and enabled only on `true`.
   */
  activatable: Record<number, boolean | undefined>;
  onActivate?: (version: DivisionGridVersion) => void;
  editorHref: (versionId: number) => string;
}

/**
 * The version history of one grid, newest first (F11 ·3).
 *
 * A list rather than a grid of cards: a workspace usually has one to four
 * versions, and one card in a four-column grid reads as abandoned. Every row
 * carries the version's ladder cut, so the history shows *what changed*
 * between versions instead of asking the reader to compare captions.
 */
export function VersionHistory({
  versions,
  activeVersionId,
  ladder,
  tournamentCounts,
  activatable,
  onActivate,
  editorHref
}: Readonly<VersionHistoryProps>) {
  const t = useTranslations("adminSettings.divisions");
  const format = useFormatter();
  const reasonIdPrefix = useId();
  const ordered = [...versions].sort((left, right) => right.version - left.version);

  return (
    // A container: the list sits in a half-width column beside the divisions table, and the row only has room for a
    // third column of actions when the LIST is wide, not the viewport.
    <Card asChild>
      <ol className="@container divide-y divide-border">
        {ordered.map((version) => {
          const state = versionState(version, activeVersionId);
          const pill = VERSION_PILL[state];
          const bands = bandsFromTiers(ladder, version.tiers);
          const isDraft = version.status === "draft";
          const canActivate = version.id in activatable;
          const ready = activatable[version.id];
          const reasonId = `${reasonIdPrefix}-${version.id}`;

          // The pill already says "in force"; a count of readers is only known for the others.
          const usage =
            state === "active" || tournamentCounts === null
              ? null
              : t("tournamentCount", { count: tournamentCounts[version.id] ?? 0 });
          // A draft has no date; its pill says so.
          const when = version.published_at
            ? format.dateTime(new Date(version.published_at), { dateStyle: "medium" })
            : null;

          return (
            <li
              key={version.id}
              className={cn(
                "grid grid-cols-[3.25rem_minmax(0,1fr)] items-start gap-x-4 gap-y-3 px-4 py-3 @2xl:grid-cols-[3.25rem_minmax(0,1fr)_auto]",
                state === "archived" && "opacity-60"
              )}
            >
              <span
                className={cn(
                  "font-display text-lg font-semibold leading-6 tabular-nums",
                  state === "active" ? "text-primary" : "text-foreground"
                )}
              >
                v{version.version}
              </span>

              <div className="flex min-w-0 flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="min-w-0 truncate text-sm font-medium" title={version.label}>
                    {version.label}
                  </span>
                  {pill ? <StatusPill tone={pill.tone}>{t(pill.key)}</StatusPill> : null}
                </div>
                {ladder ? (
                  <LadderBar ladder={ladder} bands={bands} tone={state === "active" ? "accent" : "neutral"} />
                ) : null}
                <p className="text-caption text-muted-foreground">
                  {[t("divisionCount", { count: bands.length }), usage, when]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>

              <div className="col-start-2 flex flex-wrap items-center gap-2 @2xl:col-start-3 @2xl:max-w-xs @2xl:justify-end">
                {ready === false && onActivate ? (
                  <p id={reasonId} className="basis-full text-caption text-muted-foreground @2xl:text-right">
                    {t("editorDetails.mappingBlocked")}
                  </p>
                ) : null}
                {canActivate && onActivate ? (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={ready !== true}
                    aria-describedby={ready === false ? reasonId : undefined}
                    onClick={() => onActivate(version)}
                  >
                    {t("activateVersion", { version: version.version })}
                  </Button>
                ) : null}
                {isDraft ? (
                  <Button size="sm" asChild>
                    <Link href={editorHref(version.id)}>{t("openEditor")}</Link>
                  </Button>
                ) : (
                  <Button size="sm" variant="ghost" asChild>
                    <Link href={editorHref(version.id)}>{t("view")}</Link>
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
