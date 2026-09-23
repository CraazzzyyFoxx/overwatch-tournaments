import { reachedAtLeast } from "@/lib/tournament/lifecycle";
import type { TournamentReadiness } from "@/types/admin.types";
import type { StageSummary, Tournament, TournamentStatus } from "@/types/tournament.types";

/**
 * Living-checklist model for the Overview tab (design §3, D22, D16).
 *
 * Pure function over the readiness aggregate: applicability predicates decide
 * which items exist (inapplicable items are omitted, except explicitly
 * "skipped" ones like an unscheduled check-in), field masking decides
 * "no-access". Hrefs point at the FINAL tab addresses (D20) — `registration`
 * ships in T8, `matches?tab=logs` in Phase 2 — links are already correct.
 */

/**
 * A tournament sources its bracket from Challonge — its own registration form
 * does not apply. Lockstep across the hub's overview/teams/matches/settings
 * tabs and the admin dashboard, so it lives beside `ChecklistContext` rather
 * than in a route module.
 */
export function hasChallongeSource(
  tournament: Tournament | undefined,
  stages: readonly StageSummary[]
): boolean {
  return Boolean(
    tournament?.challonge_slug || stages.some((stage) => Boolean(stage.challonge_slug))
  );
}

export type ChecklistState = "done" | "todo" | "warn" | "skipped" | "no-access";

export type ChecklistPhase =
  | "setup"
  | "registration"
  | "formation"
  | "bracket"
  | "live"
  | "finish";

export interface ChecklistItem {
  key: string;
  phase: ChecklistPhase;
  state: ChecklistState;
  label: string;
  detail?: string;
  href?: string;
}

export interface ChecklistContext {
  /** Hub base path, e.g. `/admin/tournaments/42`. */
  basePath: string;
  /** Statuses present in tournament_phase_schedule. */
  schedule: readonly TournamentStatus[];
  /** Bracket is Challonge-sourced — own registration form does not apply (§3). */
  hasChallongeSource: boolean;
}

export function buildChecklist(
  readiness: TournamentReadiness,
  ctx: ChecklistContext
): ChecklistItem[] {
  // The backend masks each permission group as a whole (D16), so one sentinel
  // field per group tells access apart from a legitimate zero/null value.
  const setupAccess = readiness.schedule_configured != null;
  const teamAccess = readiness.registrations_approved != null;

  const settingsHref = `${ctx.basePath}/settings/general`;
  const registrationHref = `${ctx.basePath}/registration/entries`;
  const teamsHref = `${ctx.basePath}/teams/roster`;
  const stagesHref = `${ctx.basePath}/bracket`;

  const items: ChecklistItem[] = [];

  // ── Setup ──────────────────────────────────────────────────────────────
  items.push({
    key: "schedule",
    phase: "setup",
    label: "Phase schedule",
    state: !setupAccess ? "no-access" : readiness.schedule_configured ? "done" : "todo",
    href: settingsHref
  });
  items.push({
    key: "grid",
    phase: "setup",
    label: "Division grid",
    state: !setupAccess ? "no-access" : readiness.grid_selected ? "done" : "todo",
    href: settingsHref
  });
  if (!ctx.hasChallongeSource) {
    items.push({
      key: "registration_form",
      phase: "setup",
      label: "Registration form",
      state: !teamAccess
        ? "no-access"
        : readiness.registration_form_configured
          ? "done"
          : "todo",
      href: `${registrationHref}/form`
    });
    items.push({
      key: "registration_open",
      phase: "setup",
      label: "Registration open",
      state: !teamAccess ? "no-access" : readiness.registration_open ? "done" : "todo",
      href: registrationHref
    });
  }

  // ── Registration ───────────────────────────────────────────────────────
  const approved = readiness.registrations_approved ?? 0;
  items.push({
    key: "approved",
    phase: "registration",
    label: "Approved registrations",
    // Informational, no threshold (§3) — never nags about a count.
    state: !teamAccess ? "no-access" : "done",
    detail: teamAccess
      ? `${approved} approved · ${readiness.registrations_pending ?? 0} pending`
      : undefined,
    href: registrationHref
  });
  const ranked = readiness.registrations_ranked ?? 0;
  items.push({
    key: "ranks",
    phase: "registration",
    label: "Ranks covered",
    state: !teamAccess ? "no-access" : approved > 0 && ranked >= approved ? "done" : "todo",
    detail: teamAccess ? `${ranked}/${approved} ranked` : undefined,
    href: registrationHref
  });
  const checkInScheduled = ctx.schedule.includes("check_in");
  const checkedIn = readiness.registrations_checked_in ?? 0;
  items.push({
    key: "check_in",
    phase: "registration",
    label: "Check-in",
    state: !checkInScheduled
      ? "skipped"
      : !teamAccess
        ? "no-access"
        : approved > 0 && checkedIn >= approved
          ? "done"
          : "todo",
    detail: checkInScheduled && teamAccess ? `${checkedIn}/${approved} checked in` : undefined,
    href: registrationHref
  });

  // ── Formation (by team_formation, §3) ──────────────────────────────────
  if (readiness.team_formation === "draft") {
    const draftSessionDetail = readiness.draft_session_status
      ? `Session: ${readiness.draft_session_status}`
      : "No draft session";
    items.push({
      key: "draft_completed",
      phase: "formation",
      label: "Draft completed",
      state: !teamAccess
        ? "no-access"
        : readiness.draft_session_status === "completed"
          ? "done"
          : "todo",
      detail: teamAccess ? draftSessionDetail : undefined,
      href: teamsHref
    });
  } else {
    const poolReady = readiness.pool_ready ?? 0;
    const poolNeedFix = readiness.pool_need_fix ?? 0;
    items.push({
      key: "pool_ready",
      phase: "formation",
      label: "Player pool ready",
      state: !teamAccess
        ? "no-access"
        : poolNeedFix > 0
          ? "warn"
          : poolReady > 0
            ? "done"
            : "todo",
      detail: teamAccess
        ? `${poolReady} ready${poolNeedFix > 0 ? ` · ${poolNeedFix} need fix` : ""}`
        : undefined,
      href: teamsHref
    });
    items.push({
      key: "balance_saved",
      phase: "formation",
      label: "Balance saved",
      state: !teamAccess ? "no-access" : readiness.balance_saved ? "done" : "todo",
      href: teamsHref
    });
    items.push({
      key: "balance_exported",
      phase: "formation",
      label: "Balance exported",
      state: !teamAccess ? "no-access" : readiness.balance_exported_at != null ? "done" : "todo",
      href: teamsHref
    });
  }

  // ── Bracket ────────────────────────────────────────────────────────────
  items.push({
    key: "stages",
    phase: "bracket",
    label: "Stages configured",
    state: !setupAccess ? "no-access" : (readiness.stages_total ?? 0) > 0 ? "done" : "todo",
    href: stagesHref
  });
  items.push({
    key: "slots",
    phase: "bracket",
    label: "Stage slots filled",
    state: !setupAccess ? "no-access" : readiness.stage_slots_filled ? "done" : "todo",
    href: stagesHref
  });
  items.push({
    key: "bracket",
    phase: "bracket",
    label: "Bracket generated",
    state: !setupAccess ? "no-access" : readiness.bracket_generated ? "done" : "todo",
    href: stagesHref
  });
  items.push({
    key: "activation",
    phase: "bracket",
    label: "Tournament live",
    // Status is never masked — derived from the state machine, not counters.
    state: reachedAtLeast(readiness.status, "live") ? "done" : "todo"
  });

  // ── Live ───────────────────────────────────────────────────────────────
  const encountersTotal = readiness.encounters_total ?? 0;
  const withLogs = readiness.encounters_with_logs ?? 0;
  items.push({
    key: "logs",
    phase: "live",
    label: "Logs cover matches",
    // Neutral until the first log arrives (§3: otherwise "Logs: not used").
    state: !setupAccess
      ? "no-access"
      : !readiness.logs_used
        ? "skipped"
        : encountersTotal > 0 && withLogs >= encountersTotal
          ? "done"
          : "warn",
    detail: !setupAccess
      ? undefined
      : !readiness.logs_used
        ? "Logs: not used"
        : `${withLogs}/${encountersTotal} matches with logs`,
    href: `${ctx.basePath}/matches/logs`
  });

  // ── Finish ─────────────────────────────────────────────────────────────
  items.push({
    key: "completed",
    phase: "finish",
    label: "Completed",
    state: reachedAtLeast(readiness.status, "completed") ? "done" : "todo"
  });
  items.push({
    key: "archived",
    phase: "finish",
    label: "Archived",
    // Optional phase (§3): never warns or nags — done or quietly skipped.
    state: readiness.status === "archived" ? "done" : "skipped"
  });

  return items;
}
