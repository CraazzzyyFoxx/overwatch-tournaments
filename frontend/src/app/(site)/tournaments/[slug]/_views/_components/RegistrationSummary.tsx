"use client";

import { useTranslations } from "next-intl";

import { ProfileStat } from "@/components/profile/atoms";
import { StatusDot } from "@/components/ui/status-dot";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { roleColor, slotCodeOrder, slotRank } from "@/lib/roster/ontology";

/** A figure with its advisory capacity as a quiet inline `/ N` suffix. */
function CapacityValue({ value, max }: Readonly<{ value: number; max?: number | null }>) {
  return (
    <>
      {value}
      {max != null && max > 0 ? (
        <span className="ms-1.5 font-[family-name:var(--aqt-data)] text-label font-normal text-[color:var(--aqt-fg-faint)]">
          / {max}
        </span>
      ) : null}
    </>
  );
}

/**
 * Count + split by role, from the server's own aggregate.
 *
 * The one place this shape is rendered: the overview's registration card shows
 * it beside the latest sign-ups, and the participants page shows it INSTEAD of
 * the roster when the organizer hid the list — in which case it is the only
 * thing either page can say, because the server sends no rows at all.
 */
export function RegistrationSummary({
  workspaceId,
  discipline,
  total,
  roleCounts,
  maxParticipants
}: Readonly<{
  /** The owner tournament's workspace and game: roles are named and tinted in that game's own ontology. */
  workspaceId: number;
  discipline: string;
  total: number;
  roleCounts: Readonly<Record<string, number>>;
  /** Advisory capacity. Rendered as a `/ N` suffix; never compared against `total`. */
  maxParticipants?: number | null;
}>) {
  const t = useTranslations();
  const ontology = useDisciplineMetadata(workspaceId, discipline).data ?? null;
  const roleLabel = useSlotLabel(ontology);
  const order = slotCodeOrder(ontology);
  // Only roles somebody actually declared: tiles that read zero describe the component, not the
  // field. A bucket this game's ontology does not know keeps its own code and a neutral tint — it is
  // never folded into another role.
  const counts = roleCounts as Readonly<Record<string, number>>;
  const shares = Object.keys(counts)
    .filter((code) => counts[code] > 0)
    .sort((a, b) => slotRank(order, a) - slotRank(order, b));
  const shareTotal = shares.reduce((sum, code) => sum + counts[code], 0);

  return (
    <>
      {/* Two abreast on a phone: four headline figures stacked one per row
          cost ~300px of a 390px screen for four numbers. */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
        <ProfileStat
          label={t("tournamentDetail.overview.registration.total")}
          value={<CapacityValue value={total} max={maxParticipants} />}
        />
        {shares.map((code) => {
          const tint = roleColor(ontology, code);
          return (
            <ProfileStat
              key={code}
              label={
                <span className="inline-flex items-center gap-1.5">
                  {tint ? <StatusDot style={{ color: tint }} /> : null}
                  {roleLabel(code)}
                </span>
              }
              value={counts[code]}
            />
          );
        })}
      </div>
      {shares.length > 1 && shareTotal > 0 ? (
        <div aria-hidden className="mt-4 flex h-1.5 gap-px overflow-hidden rounded-sm">
          {shares.map((code) => (
            <span
              key={code}
              style={{
                width: `${(counts[code] / shareTotal) * 100}%`,
                background: roleColor(ontology, code) ?? "var(--aqt-fg-dim)"
              }}
            />
          ))}
        </div>
      ) : null}
    </>
  );
}
