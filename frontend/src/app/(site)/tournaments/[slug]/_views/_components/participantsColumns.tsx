"use client";

import { Crown } from "lucide-react";

import type { RegistrationForm } from "@/types/registration.types";
import { answerSearchText } from "@/lib/forms/answers";
import { identityKey, identityMaxCount, isBuiltinKey, isGameIdentityKey } from "@/lib/forms/builtin-keys";
import { showsRoles, type LadderedOntology } from "@/lib/roster/ontology";
import type { CatalogEntityChip } from "@/types/catalog.types";

import {
  AdmissionStatusBadge,
  BalancerStatusBadge,
  CheckInStatusBadge,
  LateSignUpBadge,
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
  identityColumnDef,
  identityExtrasColumnDef,
  type BuiltInFieldDef,
  type BuiltInRenderContext,
} from "./participantsBuiltInFields";
import {
  asksTopHeroes,
  getLocalizedColumnLabel,
  IDENTITY_COLUMN_ID,
  IDENTITY_EXTRAS_COLUMN_ID,
  type ColumnDefinition,
  type Translator,
} from "./participantsColumns.model";

// ---------------------------------------------------------------------------
// Icon-only status columns
// ---------------------------------------------------------------------------

/**
 * The word beside the admission glyph for the pending state only, so an amber
 * clock does not hang on hue alone. `aria-hidden`: the badge's own `aria-label`
 * already carries the full verdict. Hidden below `lg`, where the icon track has
 * no room.
 */
function StatusWord({ children }: Readonly<{ children: string }>) {
  return (
    <span className="hidden text-label text-[color:var(--aqt-fg-muted)] lg:inline" aria-hidden>
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main builder
// ---------------------------------------------------------------------------

/** What the owner game contributes to the roster's columns. */
export interface ParticipantColumnOwner {
  /** The game: scopes the grid-less crest fallback. */
  discipline: string;
  /** Its identity provider (Battle.net, Riot, …); `null` while metadata loads or when it declares none. */
  identityProvider: string | null;
  /** Its scoped ontology (role names and glyphs) and native ladder (answer crests); `null` while it loads. */
  ontology: LadderedOntology | null;
}

export function buildParticipantColumns(
  form: RegistrationForm | null,
  t: Translator,
  owner: ParticipantColumnOwner,
  grid?: DivisionGrid | null,
  heroesMap?: Map<string, CatalogEntityChip>,
  /** Whether the loaded roster actually carries teams. There is no team flag on
   *  `RegistrationForm`, so the data itself is the only per-tournament signal;
   *  without it the column is not built at all. */
  hasTeams: boolean = false,
  /** The registration node's `require_subscription`: with it the roster gets a subscription column. */
  requireSubscription: boolean = false,
): ColumnDefinition[] {
  const columns: ColumnDefinition[] = [];
  const provider = owner.identityProvider;

  const renderContext: BuiltInRenderContext = {
    heroesMap: heroesMap ?? EMPTY_HEROES_MAP,
    ontology: owner.ontology,
    grid,
    discipline: owner.discipline,
    showRanks: form?.show_ranks,
  };
  // The owner provider's two identity columns: the primary handle and the handles after it.
  const identityDef = provider
    ? identityColumnDef(getLocalizedColumnLabel(t, identityKey(provider), provider))
    : null;
  const extrasDef = provider
    ? identityExtrasColumnDef(provider, getLocalizedColumnLabel(t, IDENTITY_EXTRAS_COLUMN_ID, provider))
    : null;

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

  const builtInDef = (key: string): BuiltInFieldDef | undefined => {
    if (provider && key === identityKey(provider)) return identityDef ?? undefined;
    if (key === IDENTITY_EXTRAS_COLUMN_ID) return extrasDef ?? undefined;
    return BUILT_IN_FIELD_DEFS[key];
  };

  // A one-role game names no role (the single-role rule): its roles column would be one identical glyph per row, so
  // it is not built -- no header, no search, no picker entry. Only a loaded ontology can say so; while it loads the
  // column stays, so a many-role roster does not shift when the metadata lands.
  const namesRoles = owner.ontology === null || showsRoles(owner.ontology);

  const pushBuiltIn = (key: string, label: string, defaultVisible: boolean) => {
    if (key === "roles" && !namesRoles) return;
    const def = builtInDef(key);
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
  // the owner game's identity question mandatory and every question may be
  // organizers-only — and it must render an empty roster rather than five columns
  // the organizer never asked for. Only the identity column and the notes column
  // survive that, and both for reasons of their own, below.
  const schema = form?.form_schema ?? null;
  const publicFields = (schema?.sections ?? [])
    .flatMap((section) => section.fields)
    .filter((field) => field.visibility === "public");

  if (schema) {
    for (const field of publicFields) {
      const def = builtInDef(field.key);
      // While the owner's provider is unknown (metadata pending or failed) a game account gets no column: the
      // generic answer renderer would print every alternate handle, which a public read must not.
      if (!def && provider === null && isGameIdentityKey(field.key)) continue;
      if (def) {
        pushBuiltIn(field.key, field.label || def.label, def.defaultVisible);
        if (field.key === "roles" && asksTopHeroes(field)) {
          pushBuiltIn("top_heroes", BUILT_IN_FIELD_DEFS.top_heroes.label, true);
        }
        // One question, two columns: the primary handle is the roster's
        // identity and the rest are an organizers-only aside, so they are
        // split the way `roles` splits off its top heroes.
        if (provider && field.key === identityKey(provider) && identityMaxCount(provider, field.params) > 1) {
          pushBuiltIn(IDENTITY_EXTRAS_COLUMN_ID, extrasDef?.label ?? "", true);
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
            ontology={owner.ontology}
          />
        ),
        searchValue: (reg) => answerSearchText(reg.answers?.[field.key]),
      });
    }
  } else {
    for (const key of FALLBACK_FIELD_KEYS) {
      pushBuiltIn(key, BUILT_IN_FIELD_DEFS[key].label, true);
      if (key === "top_heroes" && provider) pushBuiltIn(IDENTITY_EXTRAS_COLUMN_ID, extrasDef?.label ?? "", true);
    }
  }

  // The roster's face is the owner game's primary handle: always offered, whatever the form asks.
  if (identityDef && !columns.some((column) => column.id === IDENTITY_COLUMN_ID)) {
    columns.splice(1, 0, {
      id: IDENTITY_COLUMN_ID,
      label: identityDef.label,
      category: "built_in",
      defaultVisible: true,
      responsive: "always",
      render: (reg) => identityDef.render(reg, renderContext),
      searchValue: identityDef.searchValue,
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
        workspaceId={reg.workspace_id}
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
        {reg.submitted_late ? <LateSignUpBadge data-row-late="true" /> : null}
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
  if (requireSubscription) {
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
    render: (reg) => (
      <span className="inline-flex items-center gap-1">
        <AdmissionStatusBadge admission={reg.admission} />
        {reg.admission.decision === "pending_check_in" ? (
          <StatusWord>{t("common.admissionStatus.pendingShort")}</StatusWord>
        ) : null}
      </span>
    ),
  });

  return columns;
}
