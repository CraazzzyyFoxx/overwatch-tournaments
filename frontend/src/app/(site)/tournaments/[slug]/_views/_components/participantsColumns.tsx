"use client";

import { Crown } from "lucide-react";

import type { RegistrationForm } from "@/types/registration.types";
import { answerSearchText } from "@/lib/forms/answers";
import { isBuiltinKey } from "@/lib/forms/builtin-keys";
import type { Hero } from "@/types/hero.types";

import {
  AdmissionStatusBadge,
  BalancerStatusBadge,
  CheckInStatusBadge,
  ProfileStatusBadge,
  SubscriptionStatusBadge,
  RegistrationStatusBadge,
} from "@/components/status/RegistrationBadges";
import TournamentHistoryCell from "./TournamentHistoryCell";
import { AnswerValue } from "@/components/forms/AnswerValue";
import type { DivisionGrid } from "@/types/workspace.types";

import { DateCell } from "./participantsCells";
import {
  BUILT_IN_FIELD_DEFS,
  EMPTY_HEROES_MAP,
  FALLBACK_FIELD_KEYS,
  type BuiltInRenderContext,
} from "./participantsBuiltInFields";
import {
  asksTopHeroes,
  getLocalizedColumnLabel,
  type ColumnDefinition,
  type Translator,
} from "./participantsColumns.model";

// ---------------------------------------------------------------------------
// Main builder
// ---------------------------------------------------------------------------

export function buildParticipantColumns(
  form: RegistrationForm | null,
  t: Translator,
  grid?: DivisionGrid | null,
  heroesMap?: Map<string, Hero>,
  /** Whether the loaded roster actually carries teams. There is no team flag on
   *  `RegistrationForm`, so the data itself is the only per-tournament signal;
   *  without it the column is not built at all. */
  hasTeams: boolean = false,
): ColumnDefinition[] {
  const columns: ColumnDefinition[] = [];

  const renderContext: BuiltInRenderContext = {
    heroesMap: heroesMap ?? EMPTY_HEROES_MAP,
    grid,
    showRanks: form?.show_ranks,
  };

  // Meta: row number
  columns.push({
    id: "_index",
    label: "#",
    category: "meta",
    defaultVisible: false,
    responsive: "always",
    width: "icon",
    render: (_reg, index) => (
      <span className="text-[color:var(--aqt-fg-dim)] tabular-nums">{index + 1}</span>
    ),
  });

  // Meta: registered team. Built ONLY when the roster actually carries teams:
  // on a solo tournament every cell is empty, so the column would eat a grid
  // track, sit in the picker and the "Reset to defaults" set, and print a
  // blank "Team" row in every expanded details panel. When teams exist it is
  // on by default — search walks VISIBLE columns only, and finding players by
  // team is the point of the column.
  if (hasTeams) {
    const teamCaptainLabel = t("registrationTeams.member.captain");
    const teamSubstituteLabel = t("registrationTeams.member.substitute");
    columns.push({
      id: "team",
      label: t("registrationTeams.myCard.teamLabel"),
      category: "meta",
      defaultVisible: true,
      responsive: "sm",
      width: "badge",
      render: (reg) =>
        reg.team ? (
          <span className="inline-flex max-w-[200px] items-center gap-1.5">
            <span className="truncate font-medium text-[color:var(--aqt-fg)]" title={reg.team.name}>
              {reg.team.name}
            </span>
            {reg.team.is_captain ? (
              <span
                className="inline-flex shrink-0 items-center text-[color:var(--aqt-amber)]"
                title={teamCaptainLabel}
              >
                <Crown className="size-3.5" aria-hidden />
                <span className="sr-only">{teamCaptainLabel}</span>
              </span>
            ) : null}
            {reg.team.is_substitute ? (
              <span className="shrink-0 rounded border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] px-1 py-px text-label font-semibold leading-4 text-[color:var(--aqt-fg-dim)]">
                {teamSubstituteLabel}
              </span>
            ) : null}
          </span>
        ) : null,
      searchValue: (reg) => reg.team?.name ?? null,
    });
  }

  const pushBuiltIn = (key: string, label: string, defaultVisible: boolean) => {
    const def = BUILT_IN_FIELD_DEFS[key];
    if (!def) return;
    columns.push({
      id: def.id,
      label: getLocalizedColumnLabel(t, key, label),
      category: "built_in",
      defaultVisible,
      responsive: def.responsive ?? "sm",
      widthClass: def.widthClass,
      width: def.width,
      align: def.align,
      render: (reg) => def.render(reg, renderContext),
      searchValue: def.searchValue,
    });
  };

  // One column per question the form asks, in the order the organizer arranged
  // them: the schema IS the layout now, not a JSON blob whose key order was an
  // accident. Questions only organizers may read are skipped — a public read
  // carries none of their answers, so the column would be permanently empty.
  //
  // The fallback below is for "this tournament HAS no form", not for "its form
  // asks the public nothing". The second is reachable — no invariant makes
  // `battle_tag` mandatory and every question may be organizers-only — and it
  // must render an empty roster rather than five columns the organizer never
  // asked for. Only `battle_tag` and the notes column survive that, and both
  // for reasons of their own, below.
  const schema = form?.form_schema ?? null;
  const publicFields = (schema?.sections ?? [])
    .flatMap((section) => section.fields)
    .filter((field) => field.visibility === "public");

  if (schema) {
    for (const field of publicFields) {
      if (BUILT_IN_FIELD_DEFS[field.key]) {
        const def = BUILT_IN_FIELD_DEFS[field.key];
        pushBuiltIn(field.key, field.label || def.label, def.defaultVisible);
        if (field.key === "roles" && asksTopHeroes(field)) {
          pushBuiltIn("top_heroes", BUILT_IN_FIELD_DEFS.top_heroes.label, true);
        }
        continue;
      }
      // Social handles and the organizer's own questions: one answer, one
      // column, rendered by the same `AnswerValue` the admin table and the
      // draft inspector use.
      columns.push({
        id: field.key,
        label: field.label || getLocalizedColumnLabel(t, field.key, field.key),
        category: isBuiltinKey(field.key) ? "built_in" : "custom",
        defaultVisible: false,
        responsive: "md",
        render: (reg) => (
          <AnswerValue
            value={reg.answers?.[field.key] ?? null}
            kind={field.kind}
            labels={{ yes: t("common.yes"), no: t("common.no") }}
          />
        ),
        searchValue: (reg) => answerSearchText(reg.answers?.[field.key]),
      });
    }
  } else {
    for (const key of FALLBACK_FIELD_KEYS) {
      pushBuiltIn(key, BUILT_IN_FIELD_DEFS[key].label, true);
    }
  }

  if (!columns.some((column) => column.id === "battle_tag")) {
    const identity = BUILT_IN_FIELD_DEFS.battle_tag;
    columns.splice(1, 0, {
      id: identity.id,
      label: getLocalizedColumnLabel(t, "battle_tag", identity.label),
      category: "built_in",
      defaultVisible: true,
      responsive: "always",
      render: (reg) => identity.render(reg, renderContext),
      searchValue: identity.searchValue,
    });
  }

  // Notes may hold data even when the form does not ask for them (a Google
  // Sheets sync maps a notes column), so the roster always offers the column.
  if (!columns.some((column) => column.id === "public_notes")) {
    const notesDef = BUILT_IN_FIELD_DEFS.public_notes;
    pushBuiltIn("public_notes", notesDef.label, notesDef.defaultVisible);
  }

  // Meta: tournament history
  columns.push({
    id: "_history",
    label: t("common.history"),
    category: "meta",
    defaultVisible: true,
    responsive: "md",
    align: "center",
    width: "icon",
    render: (reg) => (
      <TournamentHistoryCell
        history={reg.tournament_history ?? []}
        count={reg.tournament_history_count}
      />
    ),
  });

  // Meta: registration date
  columns.push({
    id: "_submitted_at",
    label: t("common.registered"),
    category: "meta",
    defaultVisible: false,
    responsive: "md",
    render: (reg) => <DateCell iso={reg.submitted_at} />,
  });

  // Meta: registration status, plus the schedule's "signed up after the window
  // closed". The registrant's "you can call me in" does NOT ride here: it is
  // organizer bookkeeping, and stacked under every Pending pill it read as a
  // second status the player was in. It is a column of its own, off by default,
  // built from the question like any other answer.
  columns.push({
    id: "_status",
    label: t("common.status"),
    category: "meta",
    defaultVisible: true,
    responsive: "always",
    align: "center",
    width: "badge",
    render: (reg) => (
      <div className="flex flex-col items-center gap-1">
        <RegistrationStatusBadge status={reg.status} meta={reg.status_meta} />
        {reg.submitted_late ? (
          <span
            data-row-late="true"
            title={t("tournamentDetail.participants.lateHint")}
            className="rounded-full border border-[color:var(--aqt-border)] px-1.5 py-px text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-muted)]"
          >
            {t("tournamentDetail.participants.lateBadge")}
          </span>
        ) : null}
      </div>
    ),
  });

  // Meta: balancer status
  columns.push({
    id: "_balancer_status",
    label: t("common.balancer"),
    category: "meta",
    defaultVisible: true,
    responsive: "md",
    align: "center",
    width: "badge",
    render: (reg) => <BalancerStatusBadge status={reg.balancer_status} meta={reg.balancer_status_meta} />,
  });

  // Meta: check-in status
  columns.push({
    id: "_check_in",
    label: t("common.checkIn"),
    category: "meta",
    defaultVisible: true,
    responsive: "md",
    align: "center",
    width: "icon",
    render: (reg) => <CheckInStatusBadge checkedIn={reg.checked_in} />,
  });

  // Meta: profile open/closed — only when the tournament requires it.
  if (form?.require_open_profile) {
    columns.push({
      id: "_profile",
      label: t("common.profile"),
      category: "meta",
      defaultVisible: true,
      responsive: "always",
      align: "center",
      width: "icon",
      render: (reg) => <ProfileStatusBadge profilesOpen={reg.profiles_open} />,
    });
  }

  // Meta: subscription — only when the tournament requires it. ONE column with
  // the COMPOSED outcome, not one per provider: under `any` mode a red provider
  // cell beside a green one reads as a failure when it is not.
  if (form?.require_subscription) {
    columns.push({
      id: "_subscription",
      label: t("common.subscriptionColumn"),
      category: "meta",
      defaultVisible: true,
      responsive: "always",
      align: "center",
      width: "icon",
      render: (reg) => <SubscriptionStatusBadge outcome={reg.subscription_outcome} />,
    });
  }

  // Meta: admission composite — always last (rightmost)
  columns.push({
    id: "_admission",
    label: t("common.admission"),
    category: "meta",
    defaultVisible: true,
    responsive: "always",
    align: "center",
    width: "icon",
    render: (reg) => <AdmissionStatusBadge admission={reg.admission} />,
  });

  return columns;
}
