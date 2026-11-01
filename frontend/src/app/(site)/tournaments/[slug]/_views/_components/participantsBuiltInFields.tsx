"use client";

import { roleOf } from "@/lib/roster/role-ref";
import type { RoleOntology } from "@/lib/roster/ontology";
import { type ReactNode } from "react";

import type { Registration } from "@/types/registration.types";
import {
  answerList,
  answerSearchText,
  answerText,
} from "@/lib/forms/answers";
import type { CatalogEntityChip } from "@/types/catalog.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { identityKey } from "@/lib/forms/builtin-keys";
import { getPlayerSlug } from "@/lib/player";
import { PersonLabel } from "@/components/PlayerName";

import { RolesCell, SmurfTagsCell, TopHeroesCell } from "./participantsCells";
import {
  IDENTITY_COLUMN_ID,
  IDENTITY_EXTRAS_COLUMN_ID,
  type ColumnDefinition,
} from "./participantsColumns.model";

export const EMPTY_HEROES_MAP: Map<string, CatalogEntityChip> = new Map();

/** Per-table values the built-in cells need, hoisted out of the row render. */
export interface BuiltInRenderContext {
  heroesMap: Map<string, CatalogEntityChip>;
  /** The owner game's scoped ontology (role names and glyphs); `null` while it loads. */
  ontology?: RoleOntology | null;
  /** The owner game's grid; `null` renders no crest, never another game's. */
  grid?: DivisionGrid | null;
  /** The owner game, for the grid-less crest fallback of a division icon. */
  discipline?: string;
  showRanks?: boolean;
}

export interface BuiltInFieldDef {
  id: string;
  label: string;
  defaultVisible: boolean;
  responsive?: ColumnDefinition["responsive"];
  widthClass?: string;
  width?: ColumnDefinition["width"];
  align?: ColumnDefinition["align"];
  render: (reg: Registration, ctx: BuiltInRenderContext) => ReactNode;
  searchValue?: (reg: Registration) => string | null;
}

/**
 * The roster's identity column: the primary handle of the owner game's identity provider (Battle.net,
 * Riot, …), linked to the player's profile. One definition for every provider, under a provider-independent
 * column id.
 */
export function identityColumnDef(label: string): BuiltInFieldDef {
  return {
    id: IDENTITY_COLUMN_ID,
    label,
    defaultVisible: true,
    responsive: "always",
    render: (reg) => (
      <span className="flex min-w-0 font-medium text-[color:var(--aqt-fg)]">
        {reg.display.name ? (
          reg.display.canonical ? (
            <a
              href={`/users/${getPlayerSlug(reg.display.canonical)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex min-w-0 transition hover:text-[color:var(--aqt-teal)] hover:underline"
            >
              <PersonLabel display={reg.display} />
            </a>
          ) : (
            <PersonLabel display={reg.display} />
          )
        ) : (
          "\u2014"
        )}
      </span>
    ),
    searchValue: (reg) =>
      [...new Set([reg.display.name + (reg.display.tag ?? ""), reg.display.canonical, reg.primary_handle])]
        .filter(Boolean)
        .join(" ") || null,
  };
}

/**
 * The handles after the primary one. A column of its own rather than a second line under the identity:
 * the identity column is mandatory, and these stay organizers-only (`ADMIN_ONLY_COLUMN_IDS`) exactly as
 * the smurf column they replace did.
 */
export function identityExtrasColumnDef(provider: string, label: string): BuiltInFieldDef {
  const key = identityKey(provider);
  return {
    id: IDENTITY_EXTRAS_COLUMN_ID,
    label,
    defaultVisible: true,
    responsive: "md",
    render: (reg) => <SmurfTagsCell tags={answerList(reg.answers, key).slice(1)} />,
    searchValue: (reg) => answerSearchText(answerList(reg.answers, key).slice(1)),
  };
}

export const BUILT_IN_FIELD_DEFS: Record<string, BuiltInFieldDef> = {
  roles: {
    id: "roles",
    label: "Roles",
    defaultVisible: true,
    responsive: "always",
    align: "center",
    width: "badge",
    render: (reg, ctx) => (
      <RolesCell
        roles={reg.roles}
        ontology={ctx.ontology ?? null}
        grid={ctx.grid}
        discipline={ctx.discipline}
        showRanks={ctx.showRanks}
      />
    ),
    searchValue: (reg) =>
      reg.roles?.map((r) => roleOf(r.role)).join(" ") ?? null,
  },
  // Not a field of its own: the `roles` question carries `top_heroes` (the persisted form
  // spelling) in its params, and this column exists when that is switched on.
  top_heroes: {
    id: "top_heroes",
    label: "Top Heroes",
    defaultVisible: true,
    responsive: "sm",
    align: "center",
    render: (reg, ctx) => (
      <TopHeroesCell roles={reg.roles} heroesMap={ctx.heroesMap} ontology={ctx.ontology ?? null} />
    ),
    searchValue: (reg) =>
      reg.roles?.flatMap((r) => r.top_characters).join(" ") ?? null,
  },
  public_notes: {
    id: "public_notes",
    label: "Notes",
    defaultVisible: true,
    responsive: "md",
    widthClass: "max-w-50",
    render: (reg) => {
      const notes = answerText(reg.answers, "public_notes");
      return notes ? (
        <span
          className="line-clamp-3 max-w-50 wrap-break-word text-xs text-[color:var(--aqt-fg-muted)]"
          title={notes}
        >
          {notes}
        </span>
      ) : (
        <span className="text-[color:var(--aqt-fg-dim)]">&mdash;</span>
      );
    },
    searchValue: (reg) => answerText(reg.answers, "public_notes"),
  },
};

/** What the roster shows when the tournament has no form configured — the
 *  registrations still exist (a Google-Sheets feed writes them), and these are
 *  the answers such a row can carry. */
export const FALLBACK_FIELD_KEYS = ["roles", "top_heroes", "public_notes"] as const;
