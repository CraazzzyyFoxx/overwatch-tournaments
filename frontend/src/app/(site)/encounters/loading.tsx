import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";

const ROWS = 8;

/** The page's outline: the compact hero, the toolbar, then the list. */
export default function Loading() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-36 rounded-2xl" />
      <div className="space-y-3">
        <Skeleton className="h-14 rounded-xl" />
        <div className="space-y-2 rounded-xl border border-[color:var(--aqt-border)] p-3">
          {Array.from({ length: ROWS }, (_, index) => (
            <Skeleton key={index} className="h-14 rounded-md" />
          ))}
        </div>
      </div>
    </div>
  );
}
