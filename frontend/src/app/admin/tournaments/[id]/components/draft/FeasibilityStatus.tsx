"use client";

import { AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { Progress } from "@/components/ui/progress";
import type { DraftFeasibility } from "@/types/draft.types";

interface FeasibilityStatusProps {
  feasibility: DraftFeasibility | null;
  loading?: boolean;
}

export function FeasibilityStatus({ feasibility, loading = false }: FeasibilityStatusProps) {
  const t = useTranslations("draftAdmin.controlRoom");
  if (loading) return <div className="h-28 animate-pulse rounded-xl bg-[color:var(--aqt-card-2)]" />;
  if (!feasibility) {
    return <p className="text-sm text-[color:var(--aqt-fg-muted)]">{t("feasibilityUnavailable")}</p>;
  }
  const percent = feasibility.total_open_slots
    ? Math.round((feasibility.matched_slots / feasibility.total_open_slots) * 100)
    : 100;

  return (
    <section aria-labelledby="draft-feasibility-heading" className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex gap-3">
          {feasibility.is_feasible ? (
            <CheckCircle2 className="mt-0.5 h-5 w-5 text-[color:var(--aqt-support)]" />
          ) : (
            <ShieldAlert className="mt-0.5 h-5 w-5 text-[color:var(--aqt-live)]" />
          )}
          <div>
            <h3 id="draft-feasibility-heading" className="font-onest text-base font-semibold">
              {feasibility.is_feasible ? t("feasible") : t("infeasible")}
            </h3>
            <p className="mt-1 text-sm text-[color:var(--aqt-fg-muted)]">
              {t("slotCoverage", {
                matched: feasibility.matched_slots,
                total: feasibility.total_open_slots
              })}
            </p>
          </div>
        </div>
        <span className="font-mono text-sm tabular-nums text-[color:var(--aqt-fg)]">{percent}%</span>
      </div>
      <Progress value={percent} className="h-1.5" />
      {feasibility.role_deficits.length > 0 && (
        <div className="space-y-2 border-t border-[color:var(--aqt-border)] pt-3">
          {feasibility.role_deficits.map((deficit) => (
            <div key={deficit.role} className="flex items-center gap-2 text-sm">
              <AlertTriangle className="h-4 w-4 text-[color:var(--aqt-warm)]" />
              <span className="flex-1">{t(`roles.${deficit.role}`)}</span>
              <span className="font-mono text-xs text-[color:var(--aqt-fg-muted)]">
                {t("deficit", {
                  missing: deficit.unmatched_slots,
                  eligible: deficit.eligible_players
                })}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

