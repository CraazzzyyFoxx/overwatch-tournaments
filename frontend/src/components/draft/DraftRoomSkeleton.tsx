import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * The room's page surface. Flat on purpose: the room is a reading screen
 * (nicks, roles, timer). No `isolation` either — the floating pick layer
 * (z-60) has to outrank the page-level RoomChat dock (z-40, portalled to <body>).
 */
export const DRAFT_ROOM_CLASS =
  "site-theme relative min-h-svh overflow-x-clip bg-[color:var(--aqt-bg)] text-[color:var(--aqt-fg)]";

/**
 * At `xl` the two room panels fill the viewport under the header: the header's
 * live height arrives as `--draft-header-h`, 34px is the body's block padding.
 */
export const DRAFT_PANEL_HEIGHT_CLASS = "xl:h-[max(440px,calc(100svh_-_var(--draft-header-h,220px)_-_34px))]";

/** The loaded room measures its header into `--draft-header-h`; the skeleton has
    no JS, so it states the header it draws (52px row + 1px + 72px strip). */
const SKELETON_HEADER_H = "[--draft-header-h:126px]";

/** The room's content column: header row, clock strip and body share it. */
const COLUMN = "mx-auto max-w-screen-3xl px-4 sm:px-6";

function LoadingRegion({ className, children }: Readonly<{ className: string; children: ReactNode }>) {
  const t = useTranslations("draftRedesign");

  return (
    <div
      className={className}
      role="status"
      aria-live="polite"
      aria-busy="true"
      data-skeleton-variant="draft"
    >
      <span className="sr-only">{t("loadingTitle")}</span>
      <div aria-hidden="true">{children}</div>
    </div>
  );
}

const TICKS = 12;
const POOL_ROWS = 7;
const TEAM_ROWS = 6;
/** The loaded roster row carries five seats; the pool head carries five role meters. */
const TEAM_CELLS = 5;
const METERS = 5;
/** Below `sm` a row keeps its name and first two cells. */
const PHONE_CELLS = 2;

function SkeletonRows({ kind, rows, cells }: Readonly<{ kind: "pool-row" | "team-row"; rows: number; cells: number }>) {
  return (
    <div className="grid divide-y divide-[color:var(--aqt-border)]">
      {Array.from({ length: rows }, (_, index) => (
        <div
          className={cn("flex items-center gap-3 px-4 py-2.5", kind === "pool-row" ? "min-h-16" : "min-h-13")}
          data-draft-skeleton={kind}
          key={index}
        >
          <Skeleton className="h-3.5 w-36 flex-none" />
          {Array.from({ length: cells }, (_, cell) => (
            <Skeleton
              className={cn(
                "flex-1",
                kind === "pool-row" ? "h-13" : "h-7.5",
                cell >= PHONE_CELLS && "hidden sm:block"
              )}
              key={cell}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Mirrors the loaded room: header row + clock strip, then the pool and teams panels. */
function RoomSkeleton() {
  return (
    <>
      <div
        className="border-b border-[color:var(--aqt-border)] bg-[color:color-mix(in_srgb,var(--aqt-bg)_88%,transparent)]"
        data-draft-skeleton="header"
      >
        <div
          className={cn(
            COLUMN,
            "flex min-h-13 min-w-0 flex-wrap items-center gap-4 py-1.5 sm:h-13 sm:flex-nowrap sm:py-0"
          )}
        >
          <div className="flex flex-none items-center gap-1.5" data-draft-skeleton="back-action">
            <Skeleton className="size-4" />
            <Skeleton className="h-3.5 w-30" />
          </div>
          <Separator orientation="vertical" className="hidden h-5 bg-[color:var(--aqt-border-2)] sm:block" />
          <Skeleton className="h-4.5 w-18" />
          <Skeleton className="h-6 w-18 flex-none rounded-full" data-draft-skeleton="status-pill" />
          <div className="ml-auto flex min-w-0 items-center gap-4">
            <Skeleton className="hidden h-3 w-64 xl:block" />
            <Skeleton className="hidden h-3 w-20 sm:block" />
            <Skeleton className="h-7.5 w-36 rounded-full" />
          </div>
        </div>
        <div className="border-t border-[color:var(--aqt-border)]">
          <div
            className={cn(COLUMN, "flex min-w-0 flex-wrap items-center gap-4.5 py-2.5 sm:flex-nowrap")}
            data-draft-skeleton="clock-strip"
          >
            <Skeleton className="size-13 flex-none rounded-full" data-draft-skeleton="timer" />
            <div className="grid min-w-37.5 gap-1.5">
              <Skeleton className="h-2.75 w-24" />
              <Skeleton className="h-5 w-36" />
            </div>
            <div className="grid min-w-0 flex-[1_1_300px] gap-2">
              <Skeleton className="h-3.5 w-full max-w-88" />
              <div className="flex gap-0.75" data-draft-skeleton="tick-track">
                {Array.from({ length: TICKS }, (_, index) => (
                  <Skeleton className="h-2.5 min-w-1 flex-1 rounded-sm" key={index} />
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className={cn(COLUMN, "grid gap-3.5 pb-5 pt-3.5")}>
        {/* Below `xl` the loaded room switches panels with a full-width tab bar. */}
        <div className="flex gap-2 xl:hidden" data-draft-skeleton="tab-bar">
          <Skeleton className="h-11 flex-1 rounded-lg" />
          <Skeleton className="h-11 flex-1 rounded-lg" />
        </div>
        <div className="flex min-w-0 items-start gap-3.5">
          <Card
            asChild
            className={cn("flex min-h-110 min-w-0 flex-[1.2_1_600px] flex-col overflow-hidden", DRAFT_PANEL_HEIGHT_CLASS)}
          >
            <section data-draft-skeleton="pool">
              <div className="grid gap-3 border-b border-[color:var(--aqt-border)] px-4 pb-3 pt-3.5">
                <div className="flex min-w-0 items-center gap-3">
                  <Skeleton className="h-4.5 w-40 flex-none" />
                  <Skeleton className="h-9 min-w-0 flex-1 rounded-lg" />
                </div>
                <div className="flex gap-3.5">
                  <Skeleton className="h-7 w-20" />
                  <Skeleton className="h-7 w-20" />
                  <Skeleton className="h-7 w-20" />
                </div>
                <div className="flex gap-2">
                  <Skeleton className="h-8 w-22 rounded-lg" />
                  <Skeleton className="h-8 w-22 rounded-lg" />
                  <Skeleton className="h-8 w-22 rounded-lg" />
                </div>
                <div className="flex gap-2">
                  {Array.from({ length: METERS }, (_, index) => (
                    <Skeleton className="h-8 flex-1 rounded-lg" key={index} />
                  ))}
                </div>
              </div>
              <SkeletonRows kind="pool-row" rows={POOL_ROWS} cells={3} />
            </section>
          </Card>
          {/* Below `xl` the loaded room is two tabs over one panel at natural height. */}
          <Card
            asChild
            className={cn(
              "hidden min-h-110 min-w-130 flex-[1_1_600px] flex-col overflow-hidden xl:flex",
              DRAFT_PANEL_HEIGHT_CLASS
            )}
          >
            <section data-draft-skeleton="teams">
              <div className="grid gap-3 border-b border-[color:var(--aqt-border)] px-4 pb-3 pt-3.5">
                <div className="flex gap-3.5">
                  <Skeleton className="h-7 w-20" />
                  <Skeleton className="h-7 w-20" />
                </div>
                <div className="flex items-center gap-3">
                  {Array.from({ length: TEAM_CELLS }, (_, index) => (
                    <Skeleton className="h-2.75 flex-1" key={index} />
                  ))}
                </div>
              </div>
              <SkeletonRows kind="team-row" rows={TEAM_ROWS} cells={TEAM_CELLS} />
            </section>
          </Card>
        </div>
      </div>
    </>
  );
}

/** Route-level loading: the page frame is not mounted yet, so this brings the room surface. */
export function DraftRoomSkeleton() {
  return (
    <LoadingRegion className={cn(DRAFT_ROOM_CLASS, "w-full min-w-0 max-w-full", SKELETON_HEADER_H)}>
      <RoomSkeleton />
    </LoadingRegion>
  );
}

/** Inside the loaded page while the board's first fetch runs. */
export function DraftBoardSkeleton() {
  return (
    <LoadingRegion className={cn("w-full min-w-0", SKELETON_HEADER_H)}>
      <RoomSkeleton />
    </LoadingRegion>
  );
}
