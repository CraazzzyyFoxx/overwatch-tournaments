import type { MixLobbyState, MixListFilter } from "@/services/custom-game.service";

/**
 * Every open mix of a workspace in one page: the directory's "now" block and the mix page's voice panel read the
 * same cache entry. Open mixes are few (each one has a host running it), so one page of the ceiling covers them.
 */
export const OPEN_MIXES: MixListFilter = { status: "open", limit: 100 };

/** How many lobbies one mix may run at once -- the server's own CHECK ceiling. */
export const MAX_LOBBIES = 6;

/** A lobby's glyph from its 0-based index: A..F, identical in every locale. */
export function lobbyLetter(lobbyIndex: number) {
  return String.fromCharCode(65 + lobbyIndex);
}

/** A lobby's 0-based index from its room's route letter (`A`..`F`, either case); `null` for anything else. */
export function lobbyIndexFromLetter(letter: string | undefined): number | null {
  if (letter == null || !/^[A-Fa-f]$/.test(letter)) return null;
  return letter.toUpperCase().charCodeAt(0) - 65;
}

/** A lobby's room: the page its draft, bans, picks and live match play out on. */
export function mixRoomHref(gameId: number, lobbyIndex: number) {
  return `/balancer/mix/${gameId}/lobby/${lobbyLetter(lobbyIndex)}`;
}

/** A stage that plays out in the lobby's room, not on the overview: the captains' draft, or the hero bans and picks. */
export function playsInRoom(state: MixLobbyState | undefined) {
  return state === "draft_setup" || state === "draft_live" || state === "pregame";
}

/** The "Away" chip: on a seat, a lineup row and the player's own panel. */
export const AWAY_CHIP_CLASS =
  "shrink-0 rounded-[4px] border border-[color:color-mix(in_srgb,var(--aqt-amber)_35%,transparent)] px-1.5 py-0.5 text-label font-semibold uppercase tracking-label text-[color:var(--aqt-amber)]";

/**
 * The recurring chrome of the mix surface, named once.
 *
 * The mix screen, the fullscreen lobby board, the player pool and the player
 * sheet all repeat the same shapes — a mono metric pill and a card head.
 * Inlining them meant a density or tracking change was eight
 * edits in five files, and they had already drifted by a pixel in two places.
 */

/** Same voice one step tighter, for a caption that sits beside a label. */
export const CAPTION_CLASS = "text-label tabular-nums text-[color:var(--aqt-fg-dim)]";

/** The one card title of the mix surface: display face, mixed case (DESIGN §3 `text-heading`). */
export const CARD_TITLE_CLASS = "font-display text-heading font-semibold text-[color:var(--aqt-fg)]";

/** A read-only stat: pill, hairline border, tabular mono. Tone comes from the caller. */
export const METRIC_PILL_CLASS =
  "flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-label font-semibold tabular-nums tracking-[0.06em]";

/** Neutral metric tone — the default for a number that carries no verdict. */
export const METRIC_NEUTRAL_CLASS =
  "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] text-[color:var(--aqt-fg-muted)]";

/**
 * Team accents. Index is the 0-based team position, matching the design's
 * teal/amber pair; a third team would wrap rather than invent a colour.
 */
const TEAM_ACCENTS = [
  {
    bar: "bg-[color:var(--aqt-teal)]",
    border: "border-[color:var(--aqt-teal)]",
    crestPanel: "bg-[color:color-mix(in_srgb,var(--aqt-teal)_14%,transparent)]",
    crestBorder: "border-[color:color-mix(in_srgb,var(--aqt-teal)_28%,transparent)]",
    /** The "this team won" button: filled in the team's colour so it reads as that team's, not as a generic control. */
    win: "border-[color:color-mix(in_srgb,var(--aqt-teal)_45%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_16%,transparent)] text-[color:var(--aqt-teal)] hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_28%,transparent)] hover:border-[color:var(--aqt-teal)]",
  },
  {
    bar: "bg-[color:var(--aqt-amber)]",
    border: "border-[color:var(--aqt-amber)]",
    crestPanel: "bg-[color:color-mix(in_srgb,var(--aqt-amber)_13%,transparent)]",
    crestBorder: "border-[color:color-mix(in_srgb,var(--aqt-amber)_28%,transparent)]",
    win: "border-[color:color-mix(in_srgb,var(--aqt-amber)_45%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_16%,transparent)] text-[color:var(--aqt-amber)] hover:bg-[color:color-mix(in_srgb,var(--aqt-amber)_28%,transparent)] hover:border-[color:var(--aqt-amber)]",
  },
] as const;

export function teamAccent(teamIndex: number) {
  return TEAM_ACCENTS[teamIndex % TEAM_ACCENTS.length];
}
