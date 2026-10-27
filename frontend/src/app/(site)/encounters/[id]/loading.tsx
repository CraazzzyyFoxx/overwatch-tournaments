import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  BOARD,
  BOARD_CENTER,
  BOARD_SIDE,
  BOARD_SIDE_TWO,
  HEADER_CARD,
  HEADER_FOOT,
  HEADER_TOP,
  MAP_ACTION,
  MAP_IDENTITY,
  MAP_INDEX,
  MAP_ROW,
  MAP_SCORE,
  MAP_THUMB,
  MAP_TIME,
  SECTION_HEAD,
  SURFACE
} from "@/components/match/EncounterAtoms";
import { cn } from "@/lib/utils";

/**
 * Mirrors the real layout: one header card (crumbs, board, series facts), the
 * tab strip, then the map rows of the default tab — so nothing re-flows the
 * moment data arrives.
 */
export default function Loading() {
  return (
    <div className={SURFACE} aria-busy>
      <Card className={HEADER_CARD}>
        <div className={HEADER_TOP}>
          <Skeleton className="h-3 w-72 max-w-full" />
          <Skeleton className="h-8 w-36 rounded-lg" />
        </div>
        <div className={BOARD}>
          <div className={BOARD_SIDE}>
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-3 w-28" />
            </div>
          </div>
          <div className={BOARD_CENTER}>
            <Skeleton className="h-12 w-32" />
            <Skeleton className="h-3 w-40" />
            <Skeleton className="h-4.5 w-24" />
          </div>
          <div className={cn(BOARD_SIDE, BOARD_SIDE_TWO)}>
            <div className="flex min-w-0 flex-1 flex-col items-end gap-2">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-3 w-28" />
            </div>
          </div>
        </div>
        <div className={HEADER_FOOT}>
          <Skeleton className="h-8 w-80 max-w-full" />
        </div>
      </Card>

      {/* The tab row's geometry (`LinkTabs`): 36px tabs over a hairline. */}
      <div className="flex gap-1 border-b border-[color:var(--aqt-border)]">
        {Array.from({ length: 3 }).map((_, index) => (
          <span key={index} className="inline-flex h-9 items-center px-3">
            <Skeleton className="h-4 w-20" />
          </span>
        ))}
      </div>

      <section>
        <div className={SECTION_HEAD}>
          <Skeleton className="h-6 w-28" />
          <Skeleton className="h-3 w-32" />
        </div>
        <Card className="flex flex-col divide-y divide-[color:var(--aqt-overlay-border)] overflow-hidden">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className={MAP_ROW}>
              <Skeleton className={cn(MAP_INDEX, "h-4 w-4")} />
              <Skeleton className={MAP_THUMB} />
              <div className={cn(MAP_IDENTITY, "gap-2")}>
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-24" />
              </div>
              <Skeleton className={cn(MAP_SCORE, "h-5 w-12")} />
              <Skeleton className={cn(MAP_TIME, "h-3 w-12")} />
              <Skeleton className={cn(MAP_ACTION, "h-8 w-32 rounded-lg")} />
            </div>
          ))}
        </Card>
      </section>
    </div>
  );
}
