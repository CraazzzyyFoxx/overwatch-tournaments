"use client";

import { ArrowRight } from "lucide-react";

import DivisionIcon from "@/components/DivisionIcon";

import { ROLE_LABELS, type PlayerValidationIssue } from "@/components/balancer/workspace-helpers";

const CHIP_CLASS =
  "inline-flex shrink-0 items-center gap-1 rounded-full border border-amber-300/20 bg-amber-500/10 px-1.5 py-0.5 text-label font-medium text-amber-100/80";

function staticLabel(issue: PlayerValidationIssue): string {
  if (issue.code === "missing_ranked_role") {
    return "No ranked roles";
  }
  if (issue.code === "status_blocks_ready") {
    return "Blocks Ready";
  }
  return "Role mismatch";
}

/**
 * Stable React key for an issue chip. Rank-delta warnings can occur once per role,
 * so the role is folded in to keep keys unique within a player's chip list.
 */
export function issueChipKey(issue: PlayerValidationIssue): string {
  return issue.code === "rank_delta_warning" ? `${issue.code}-${issue.role}` : issue.code;
}

/**
 * Amber validation chip. For rank-delta warnings it renders a compact icon form
 * (role · current-division-icon → ow-division-icon · Δpts); the full text is in the tooltip.
 */
export function IssueChip({ issue }: Readonly<{ issue: PlayerValidationIssue }>) {
  if (issue.code === "rank_delta_warning") {
    return (
      <span className={CHIP_CLASS} title={issue.message}>
        <span className="font-semibold uppercase tracking-label">{ROLE_LABELS[issue.role]}</span>
        {issue.currentDivision != null ? (
          <DivisionIcon division={issue.currentDivision} width={14} height={14} />
        ) : null}
        <ArrowRight className="size-4 shrink-0 opacity-70" aria-hidden />
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
