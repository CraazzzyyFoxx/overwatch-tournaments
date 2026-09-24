import { StatusDot } from "@/components/ui/status-dot";

/** Small pulsing "live" badge for a card header backed by a polling query. */
export function LiveIndicator() {
  return (
    <span className="flex items-center gap-1 text-xs font-normal text-success">
      <StatusDot pulse />
      live
    </span>
  );
}
