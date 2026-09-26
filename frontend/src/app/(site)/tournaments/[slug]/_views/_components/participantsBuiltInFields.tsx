"use client";

import { type ReactNode } from "react";

import type { Registration } from "@/types/registration.types";
import {
  answerList,
  answerSearchText,
  answerText,
} from "@/lib/forms/answers";
import type { Hero } from "@/types/hero.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { getPlayerSlug } from "@/lib/player";

import { RolesCell, SmurfTagsCell, TopHeroesCell } from "./participantsCells";
import type { ColumnDefinition } from "./participantsColumns.model";

export const EMPTY_HEROES_MAP: Map<string, Hero> = new Map();

/** Per-table values the built-in cells need, hoisted out of the row render. */
export interface BuiltInRenderContext {
  heroesMap: Map<string, Hero>;
  grid?: DivisionGrid | null;
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

export const BUILT_IN_FIELD_DEFS: Record<string, BuiltInFieldDef> = {
  battle_tag: {
    id: "battle_tag",
    label: "BattleTag",
    defaultVisible: true,
    responsive: "always",
    render: (reg) => (
      <span className="font-medium text-[color:var(--aqt-fg)]">
        {reg.battle_tag ? (
          <a
            href={`/users/${getPlayerSlug(reg.battle_tag)}`}
            target="_blank"
            rel="noopener noreferrer"
            className="transition hover:text-[color:var(--aqt-teal)] hover:underline"
          >
            {reg.battle_tag}
          </a>
        ) : (
          "\u2014"
        )}
      </span>
    ),
    searchValue: (reg) => reg.battle_tag,
  },
  smurf_tags: {
    id: "smurf_tags",
    label: "Smurfs",
    defaultVisible: true,
    responsive: "md",
    render: (reg) => <SmurfTagsCell tags={answerList(reg.answers, "smurf_tags")} />,
    searchValue: (reg) => answerSearchText(reg.answers?.smurf_tags),
  },
  roles: {
    id: "roles",
    label: "Roles",
    defaultVisible: true,
    responsive: "always",
    align: "center",
    width: "badge",
    render: (reg, ctx) => <RolesCell roles={reg.roles} grid={ctx.grid} showRanks={ctx.showRanks} />,
    searchValue: (reg) =>
      reg.roles?.map((r) => r.role).join(" ") ?? null,
  },
  // Not a field of its own: the `roles` question carries `top_heroes` in its
  // params, and this column exists when that is switched on.
  top_heroes: {
    id: "top_heroes",
    label: "Top Heroes",
    defaultVisible: true,
    responsive: "sm",
    align: "center",
    render: (reg, ctx) => <TopHeroesCell roles={reg.roles} heroesMap={ctx.heroesMap} />,
    searchValue: (reg) =>
      reg.roles?.flatMap((r) => r.top_heroes).join(" ") ?? null,
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
export const FALLBACK_FIELD_KEYS = [
  "battle_tag",
  "roles",
  "top_heroes",
  "smurf_tags",
  "public_notes",
] as const;
