import {
  Bell,
  CalendarClock,
  CalendarPlus,
  CircleCheck,
  CircleX,
  ClipboardCheck,
  Gavel,
  Megaphone,
  TriangleAlert,
  UserPlus,
  type LucideIcon
} from "lucide-react";

/**
 * Icon and accent per notification kind, shared by the bell rows and the urgent
 * card in the floating stack so one event wears one colour wherever it appears.
 *
 * The accent is an `--aqt-*` token, never a Tailwind palette colour: a branded
 * workspace re-derives these, and a `rose-500` would survive the re-theme.
 */
export const KIND_VISUAL: Record<string, readonly [LucideIcon, string]> = {
  "team_invite.received": [UserPlus, "var(--aqt-blue)"],
  "team_invite.answered": [UserPlus, "var(--aqt-blue)"],
  "registration.approved": [CircleCheck, "var(--aqt-emerald)"],
  "registration.rejected": [CircleX, "var(--aqt-rose)"],
  "team.kicked": [CircleX, "var(--aqt-rose)"],
  "team.rejected": [CircleX, "var(--aqt-rose)"],
  "team.disbanded": [CircleX, "var(--aqt-rose)"],
  "encounter.report_disputed": [TriangleAlert, "var(--aqt-amber)"],
  // An organizer decision is owed, not just a contradiction to look at: the
  // gavel separates it from the captains' own alert at a glance.
  "encounter.dispute_review": [Gavel, "var(--aqt-rose)"],
  "registration.opened": [CalendarPlus, "var(--aqt-teal)"],
  // Time-boxed and the reader has to act, so it wears the alert tone rather
  // than the neutral one of "registration is open".
  "check_in.opened": [ClipboardCheck, "var(--aqt-amber)"],
  "encounter.scheduled": [CalendarClock, "var(--aqt-blue)"],
  "announcement.published": [Megaphone, "var(--aqt-teal)"]
};

/** Anything the backend adds before the table does. */
export const KIND_FALLBACK: readonly [LucideIcon, string] = [Bell, "var(--aqt-fg-dim)"];

/**
 * Kinds a single click resolves — the same two the Discord bot puts buttons on.
 * The value is the urgency rank: the floating stack shows the lowest first.
 */
export const ACTIONABLE_RANK: Record<string, number> = {
  "check_in.opened": 1,
  "team_invite.received": 2
};
