import type { useTranslations } from "next-intl";

import { phaseRank } from "@/lib/tournament/lifecycle";
import type { TournamentReadiness } from "@/types/admin.types";
import type { StageSummary, Tournament, TournamentStatus } from "@/types/tournament.types";

/** The `adminTournaments.checklist` translator of the component that renders the checklist. */
export type ChecklistTranslator = ReturnType<typeof useTranslations<"adminTournaments.checklist">>;

/**
 * Living-checklist model for the Overview tab (design §3, D22, D16).
 *
 * Pure function over the readiness aggregate. Every item has a status window:
 * it exists only while the tournament's status sits inside it, so a finished
 * phase stops asking for work it no longer needs (a closed registration, a
 * check-in nobody can still pass) — the PhaseStrip already says the phase is
 * behind. Applicability predicates drop the rest, field masking decides
 * "no-access".
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

/** `info` is progress without a verdict: shown, never counted as open work. */
export type ChecklistState = "done" | "todo" | "warn" | "info" | "skipped" | "no-access";

/** The checklist's groups, in render order; the status itself lives in the PhaseStrip. */
export type ChecklistPhase = "setup" | "registration" | "formation" | "bracket" | "matches" | "wrap_up";

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
  /** The tournament's status: it picks which items exist at all. */
  status: TournamentStatus;
  /** Bracket is Challonge-sourced — own registration form does not apply (§3). */
  hasChallongeSource: boolean;
}

/** The one thing worth doing next (F3 ·3): the first warning, else the first to-do. */
export function pickNextAction(items: readonly ChecklistItem[]): ChecklistItem | undefined {
  return (
    items.find((item) => item.state === "warn" && item.href) ??
    items.find((item) => item.state === "todo" && item.href)
  );
}

export function buildChecklist(
  // The status comes from `ctx`, so the dashboard's wire copy (a plain string) fits too.
  readiness: Omit<TournamentReadiness, "status">,
  ctx: ChecklistContext,
  t: ChecklistTranslator
): ChecklistItem[] {
  // The backend masks each permission group as a whole (D16), so one sentinel
  // field per group tells access apart from a legitimate zero/null value.
  const setupAccess = readiness.schedule_configured != null;
  const teamAccess = readiness.registrations_approved != null;
  const matchAccess = readiness.results_disputed != null;

  const rank = phaseRank(ctx.status);
  /** The item matters from `from` through `until`, and only then. The registration, check-in, draft and play phases are one `live` status. */
  const during = (from: TournamentStatus, until: TournamentStatus) =>
    phaseRank(from) <= rank && rank <= phaseRank(until);
  const completed = ctx.status === "completed";

  const settingsHref = `${ctx.basePath}/settings/general`;
  const registrationHref = `${ctx.basePath}/registration/entries`;
  const teamsHref = `${ctx.basePath}/teams/roster`;
  const stagesHref = `${ctx.basePath}/bracket`;

  const items: ChecklistItem[] = [];

  // ── Setup ──────────────────────────────────────────────────────────────
  if (during("announcement", "live")) {
    items.push({
      key: "schedule",
      phase: "setup",
      label: t("phaseSchedule"),
      state: !setupAccess ? "no-access" : readiness.schedule_configured ? "done" : "todo",
      href: settingsHref
    });
  }
  if (during("announcement", "live")) {
    items.push({
      key: "grid",
      phase: "setup",
      label: t("divisionGrid"),
      state: !setupAccess ? "no-access" : readiness.grid_selected ? "done" : "todo",
      href: settingsHref
    });
  }
  if (!ctx.hasChallongeSource && during("announcement", "live")) {
    items.push({
      key: "registration_form",
      phase: "setup",
      label: t("registrationForm"),
      state: !teamAccess
        ? "no-access"
        : readiness.registration_form_configured
          ? "done"
          : "todo",
      href: `${ctx.basePath}/settings/registration`
    });
  }

  // ── Registration ───────────────────────────────────────────────────────
  const approved = readiness.registrations_approved ?? 0;
  const pending = readiness.registrations_pending ?? 0;
  if (during("live", "live")) {
    items.push({
      key: "registrations_reviewed",
      phase: "registration",
      label: t("registrationsReviewed"),
      state: !teamAccess ? "no-access" : pending > 0 ? "warn" : "done",
      detail: teamAccess ? t("approvedDetail", { approved, pending }) : undefined,
      href: registrationHref
    });
  }
  if (during("live", "live")) {
    const ranked = readiness.registrations_ranked ?? 0;
    items.push({
      key: "ranks",
      phase: "registration",
      label: t("ranksCovered"),
      state: !teamAccess ? "no-access" : approved > 0 && ranked >= approved ? "done" : "todo",
      detail: teamAccess ? t("rankedDetail", { ranked, approved }) : undefined,
      href: registrationHref
    });
  }
  if (during("live", "live")) {
    // No-shows are normal, so "everyone checked in" is no finish line: progress only.
    items.push({
      key: "check_in",
      phase: "registration",
      label: t("checkIn"),
      state: !teamAccess ? "no-access" : "info",
      detail: teamAccess
        ? t("checkedInDetail", { checkedIn: readiness.registrations_checked_in ?? 0, approved })
        : undefined,
      href: registrationHref
    });
  }

  // ── Formation (by the formation nodes' modes, §3) ──────────────────────
  if (during("live", "live")) {
    if (readiness.formation_modes.includes("draft")) {
      const draftStatus = readiness.draft_session_status;
      items.push({
        key: "draft_completed",
        phase: "formation",
        label: t("draftCompleted"),
        state: !teamAccess ? "no-access" : draftStatus === "completed" ? "done" : "todo",
        detail:
          !teamAccess || draftStatus === "completed"
            ? undefined
            : draftStatus
              ? t("sessionDetail", { status: draftStatus })
              : t("noDraftSession"),
        // The draft board, not the roster: it is where a draft is run.
        href: `${ctx.basePath}/teams/draft`
      });
    } else {
      const poolReady = readiness.pool_ready ?? 0;
      const poolNeedFix = readiness.pool_need_fix ?? 0;
      items.push({
        key: "pool_ready",
        phase: "formation",
        label: t("playerPoolReady"),
        state: !teamAccess
          ? "no-access"
          : poolNeedFix > 0
            ? "warn"
            : poolReady > 0
              ? "done"
              : "todo",
        detail: teamAccess
          ? t("poolDetail", { ready: poolReady, needFix: poolNeedFix })
          : undefined,
        href: teamsHref
      });
      items.push({
        key: "balance_saved",
        phase: "formation",
        label: t("balanceSaved"),
        state: !teamAccess ? "no-access" : readiness.balance_saved ? "done" : "todo",
        href: teamsHref
      });
      items.push({
        key: "balance_exported",
        phase: "formation",
        label: t("balanceExported"),
        state: !teamAccess ? "no-access" : readiness.balance_exported_at != null ? "done" : "todo",
        href: teamsHref
      });
    }
  }

  // ── Bracket ────────────────────────────────────────────────────────────
  if (during("announcement", "live")) {
    items.push({
      key: "stages",
      phase: "bracket",
      label: t("stagesConfigured"),
      state: !setupAccess ? "no-access" : (readiness.stages_total ?? 0) > 0 ? "done" : "todo",
      href: stagesHref
    });
  }
  if (during("live", "live")) {
    items.push({
      key: "slots",
      phase: "bracket",
      label: t("stageSlotsFilled"),
      state: !setupAccess ? "no-access" : readiness.stage_slots_filled ? "done" : "todo",
      href: stagesHref
    });
    items.push({
      key: "bracket",
      phase: "bracket",
      label: t("bracketGenerated"),
      state: !setupAccess ? "no-access" : readiness.bracket_generated ? "done" : "todo",
      href: stagesHref
    });
  }

  // ── Matches ────────────────────────────────────────────────────────────
  if (during("live", "completed")) {
    const disputed = readiness.results_disputed ?? 0;
    const awaiting = readiness.results_pending_confirmation ?? 0;
    // A match still unplayed once the tournament is over is not "overdue" any more.
    const overdue = completed ? 0 : (readiness.results_overdue ?? 0);
    const problems = [
      disputed > 0 ? t("resultsDisputed", { count: disputed }) : null,
      awaiting > 0 ? t("resultsAwaiting", { count: awaiting }) : null,
      overdue > 0 ? t("resultsOverdue", { count: overdue }) : null
    ].filter((part) => part !== null);
    items.push({
      key: "results",
      phase: "matches",
      label: t("resultsConfirmed"),
      state: !matchAccess ? "no-access" : problems.length > 0 ? "warn" : "done",
      detail: matchAccess && problems.length > 0 ? problems.join(" · ") : undefined,
      href: `${ctx.basePath}/matches/encounters`
    });

    const duels = readiness.duel_encounters_total ?? 0;
    const withLogs = readiness.duel_encounters_with_logs ?? 0;
    items.push({
      key: "logs",
      phase: "matches",
      label: t("logsCoverMatches"),
      // Neutral until the first log arrives (§3: otherwise "Logs: not used"),
      // and only progress while play goes on: logs trail the matches.
      state: !setupAccess
        ? "no-access"
        : !readiness.logs_used
          ? "skipped"
          : withLogs >= duels
            ? "done"
            : completed
              ? "todo"
              : "info",
      detail: !setupAccess
        ? undefined
        : !readiness.logs_used
          ? t("logsNotUsed")
          : t("logsDetail", { withLogs, total: duels }),
      href: `${ctx.basePath}/matches/logs`
    });
  }

  // ── Wrap-up ────────────────────────────────────────────────────────────
  if (completed) {
    const achievements = readiness.achievements_status;
    items.push({
      key: "achievements",
      phase: "wrap_up",
      label: t("achievementsEvaluated"),
      state:
        achievements == null
          ? "no-access"
          : achievements === "not_configured"
            ? "skipped"
            : achievements === "done"
              ? "done"
              : achievements === "partial" || achievements === "failed"
                ? "warn"
                : "todo",
      detail:
        achievements == null || achievements === "done"
          ? undefined
          : t("achievementsDetail", { status: achievements }),
      href: "/admin/achievements"
    });
    items.push({
      key: "standings",
      phase: "wrap_up",
      label: t("standingsRecalculated"),
      state: !setupAccess ? "no-access" : readiness.standings_recalc_pending ? "todo" : "done",
      detail: setupAccess && readiness.standings_recalc_pending ? t("standingsQueued") : undefined,
      href: stagesHref
    });
  }

  return items;
}
