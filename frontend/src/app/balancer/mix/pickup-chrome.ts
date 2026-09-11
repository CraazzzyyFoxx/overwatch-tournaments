import type { CustomGameStatus } from "@/services/custom-game.service";

/**
 * The recurring chrome of the mix surface, named once.
 *
 * The mix screen, the fullscreen lobby board, the player pool and the player
 * sheet all repeat the same three shapes — a mono eyebrow, a mono metric pill
 * and a card head. Inlining them meant a density or tracking change was eight
 * edits in five files, and they had already drifted by a pixel in two places.
 */

/** Mono, wide-tracked, uppercase: the "tactical voice" label above a heading. */
export const EYEBROW_CLASS =
  "text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]";

/** Same voice one step tighter, for a caption that sits beside a label. */
export const CAPTION_CLASS = "text-xs tabular-nums text-[color:var(--aqt-fg-dim)]";

/** Section title inside a card head — display face, uppercase, short tracking. */
export const CARD_TITLE_CLASS =
  "font-display text-sm font-bold uppercase tracking-[0.04em] text-[color:var(--aqt-fg)]";

/** A read-only stat: pill, hairline border, tabular mono. Tone comes from the caller. */
export const METRIC_PILL_CLASS =
  "flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-label font-semibold tabular-nums tracking-[0.06em]";

/** Neutral metric tone — the default for a number that carries no verdict. */
export const METRIC_NEUTRAL_CLASS =
  "border-[color:var(--aqt-border-2)] bg-white/[0.025] text-[color:var(--aqt-fg-muted)]";

/**
 * Team accents. Index is the 0-based team position, matching the design's
 * teal/amber pair; a third team would wrap rather than invent a colour.
 */
export const TEAM_ACCENTS = [
  {
    bar: "bg-[color:var(--aqt-teal)]",
    crestPanel: "bg-[color:color-mix(in_srgb,var(--aqt-teal)_14%,transparent)]",
    crestBorder: "border-[color:color-mix(in_srgb,var(--aqt-teal)_28%,transparent)]",
    /** The "this team won" button: filled in the team's colour so it reads as that team's, not as a generic control. */
    win: "border-[color:color-mix(in_srgb,var(--aqt-teal)_45%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_16%,transparent)] text-[color:var(--aqt-teal)] hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_28%,transparent)] hover:border-[color:var(--aqt-teal)]",
  },
  {
    bar: "bg-[color:var(--aqt-amber)]",
    crestPanel: "bg-[color:color-mix(in_srgb,var(--aqt-amber)_13%,transparent)]",
    crestBorder: "border-[color:color-mix(in_srgb,var(--aqt-amber)_28%,transparent)]",
    win: "border-[color:color-mix(in_srgb,var(--aqt-amber)_45%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_16%,transparent)] text-[color:var(--aqt-amber)] hover:bg-[color:color-mix(in_srgb,var(--aqt-amber)_28%,transparent)] hover:border-[color:var(--aqt-amber)]",
  },
] as const;

export function teamAccent(teamIndex: number) {
  return TEAM_ACCENTS[teamIndex % TEAM_ACCENTS.length];
}

/**
 * Status tone for a mix. Only `completed`/`cancelled` are terminal, so those are
 * the two that read as "done" rather than as a stage in progress.
 */
export const MIX_STATUS_CLASS: Record<CustomGameStatus, string> = {
  draft: "border-[color:var(--aqt-border-2)] bg-white/[0.03] text-[color:var(--aqt-fg-muted)]",
  balanced:
    "border-[color:color-mix(in_srgb,var(--aqt-teal)_35%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] text-[color:var(--aqt-teal)]",
  completed:
    "border-[color:color-mix(in_srgb,var(--aqt-emerald)_32%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_10%,transparent)] text-[color:var(--aqt-emerald)]",
  cancelled: "border-[color:var(--aqt-border-2)] bg-white/[0.02] text-[color:var(--aqt-fg-faint)]",
};

/**
 * Role tile tint: a low-alpha fill plus a 2px inset underline in the role
 * colour, so a lit chip states its role without a text label and a dimmed one
 * still reads as the same role.
 *
 * The underline is load-bearing in the lineup rail, where it marks the *first*
 * role a player will be seated in — so a tile that is playable but not first
 * takes `ROLE_TINT_CLASS` instead and leaves the underline unspent.
 */
export const ROLE_TILE_CLASS: Record<string, string> = {
  tank: "bg-[color:color-mix(in_srgb,var(--aqt-tank)_12%,transparent)] shadow-[inset_0_-2px_0_var(--aqt-tank)]",
  dps: "bg-[color:color-mix(in_srgb,var(--aqt-damage)_12%,transparent)] shadow-[inset_0_-2px_0_var(--aqt-damage)]",
  support:
    "bg-[color:color-mix(in_srgb,var(--aqt-support)_12%,transparent)] shadow-[inset_0_-2px_0_var(--aqt-support)]",
};

/** Same fill, no underline: a role the balancer may use, but not first. */
export const ROLE_TINT_CLASS: Record<string, string> = {
  tank: "bg-[color:color-mix(in_srgb,var(--aqt-tank)_9%,transparent)]",
  dps: "bg-[color:color-mix(in_srgb,var(--aqt-damage)_9%,transparent)]",
  support: "bg-[color:color-mix(in_srgb,var(--aqt-support)_9%,transparent)]",
};

/**
 * Role glyph colour for the "on" state -- paints the icon itself in the role
 * colour rather than tinting a background behind it, so a lit role reads at
 * a glance without depending on a low-alpha fill catching the light. An
 * "off" role passes no colour at all and falls back to the glyph's own
 * neutral grey (see `PlayerRoleIcon`).
 */
export const ROLE_ICON_COLOR: Record<string, string> = {
  tank: "var(--aqt-tank)",
  dps: "var(--aqt-damage)",
  support: "var(--aqt-support)",
};
