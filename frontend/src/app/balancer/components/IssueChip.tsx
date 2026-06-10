"use client";

import React from "react";

import DivisionIcon from "@/components/DivisionIcon";

import { ROLE_LABELS, type PlayerValidationIssue } from "./workspace-helpers";

const CHIP_CLASS =
  "inline-flex shrink-0 items-center gap-1 rounded-full border border-amber-300/20 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-100/80";

function staticLabel(issue: PlayerValidationIssue): string {
  if (issue.code === "missing_ranked_role") {
    return "No ranked roles";
  }
  return "Role mismatch";
}

/**
 * Amber validation chip. For rank-delta warnings it renders a compact icon form
 * (role · current-division-icon → ow-division-icon · Δpts); the full text is in the tooltip.
 */
export function IssueChip({ issue }: { issue: PlayerValidationIssue }) {
  if (issue.code === "rank_delta_warning") {
    return (
      <span className={CHIP_CLASS} title={issue.message}>
        <span className="font-semibold uppercase tracking-wide">{ROLE_LABELS[issue.role]}</span>
        {issue.currentDivision != null ? (
          <DivisionIcon division={issue.currentDivision} width={14} height={14} />
        ) : null}
        <span aria-hidden className="opacity-70">
          →
        </span>
        {issue.owDivision != null ? (
          <DivisionIcon division={issue.owDivision} width={14} height={14} />
        ) : null}
        <span className="tabular-nums">Δ{issue.delta} pts</span>
      </span>
    );
  }

  return (
    <span className={CHIP_CLASS} title={issue.message}>
      {staticLabel(issue)}
    </span>
  );
}

export default IssueChip;
