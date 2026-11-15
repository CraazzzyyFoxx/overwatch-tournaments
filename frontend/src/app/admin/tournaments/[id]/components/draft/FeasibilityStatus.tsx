"use client";

import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";

import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import type { RoleOntology } from "@/lib/roster/ontology";
import type { DraftFeasibility } from "@/types/draft.types";
import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";

interface FeasibilityStatusProps {
  feasibility: DraftFeasibility | null;
  loading?: boolean;
  /** The owner game's role dictionary: names of the slots a deficit is about. */
  ontology: RoleOntology | null;
}

export function FeasibilityStatus({ feasibility, loading = false, ontology }: Readonly<FeasibilityStatusProps>) {
  const t = useTranslations("draftAdmin.controlRoom");
  const slotLabel = useSlotLabel(ontology);
  if (loading) return <Skeleton className="h-28 w-full rounded-xl" />;
  if (!feasibility) {
    return (
      <EmptyNote>
        {t("feasibilityUnavailable")}
      </EmptyNote>
    );
  }

  return (
    <section aria-labelledby="draft-feasibility-heading" role="status" className="space-y-3">
      <div>
        <h3
          id="draft-feasibility-heading"
          className={feasibility.is_feasible ? "font-onest text-base font-semibold" : "font-onest text-base font-semibold text-danger"}
        >
          {feasibility.is_feasible ? t("feasible") : t("infeasible")}
        </h3>
        <p className="mt-1 text-sm tabular-nums text-muted-foreground">
          {t("slotCoverage", {
            matched: feasibility.matched_slots,
            total: feasibility.total_open_slots
          })}
        </p>
      </div>
      {feasibility.slot_deficits.length > 0 && (
        <ul className="space-y-2 border-t border-border pt-3">
          {feasibility.slot_deficits.map((deficit) => (
            <li key={deficit.slot_code} className="flex items-center gap-2 text-sm">
              <AlertTriangle className="h-4 w-4 text-warning" aria-hidden />
              <span className="flex-1">{slotLabel(deficit.slot_code)}</span>
              <span className="text-xs tabular-nums text-muted-foreground">
                {t("deficit", {
                  missing: deficit.unmatched_slots,
                  eligible: deficit.eligible_players
                })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
