/**
 * The inbox wire types (`GET /api/v1/notifications`, `GET /api/v1/announcements/active`).
 *
 * A row carries `kind` + a payload *snapshot*, never rendered text: the client
 * renders `t("notifications.kinds." + kind, payload)`, so a wording fix reaches
 * rows written months ago and a deleted team still reads by name. Announcements
 * are the one exception — their operator-written text lives inside the payload,
 * one entry per locale.
 */

export type NotificationAudience = "user" | "workspace" | "global";

/** Operator-written announcement text, per locale, inside `payload.locales`. */
export interface AnnouncementLocaleText {
  title: string;
  body?: string | null;
}

export interface NotificationItem {
  id: number;
  audience: NotificationAudience;
  kind: string;
  /** Snapshot fields the kind's message interpolates. Shape varies by kind. */
  payload: Record<string, unknown>;
  workspace_id: number | null;
  published_at: string;
  expires_at: string | null;
  /** Whether *this* viewer has a read mark on the row. "Read" means "dismissed". */
  is_read: boolean;
}

export interface NotificationInbox {
  items: NotificationItem[];
  unread_count: number;
  /** `null` on the last page. Opaque: parsing it means depending on the sort key. */
  next_cursor: string | null;
}

export interface NotificationMarkReadResult {
  marked: number;
  unread_count: number;
}

export interface NotificationDeleteResult {
  /** How many rows actually left this inbox. */
  deleted: number;
  unread_count: number;
}

/**
 * One row as the *operator* of the producing workspace sees it
 * (`GET /api/v1/admin/notifications`).
 *
 * A different question from `NotificationItem`: not "what am I being told" but
 * "what did my workspace send, to whom, and is it still live". Hence the
 * recipient — which the inbox model has no reason to carry, since there it is
 * always the caller — and no `is_read`, which is a fact about a viewer this
 * screen does not have.
 */
export interface NotificationAdminItem {
  id: number;
  kind: string;
  payload: Record<string, unknown>;
  recipient_auth_user_id: number | null;
  /** The recipient's current username; `null` when the account is gone. */
  recipient_username: string | null;
  source_workspace_id: number | null;
  published_at: string;
  /** Set and in the past means retired: the row reaches no inbox any more. */
  expires_at: string | null;
}

export interface NotificationAdminPage {
  items: NotificationAdminItem[];
  next_cursor: string | null;
}

export interface NotificationRetireResult {
  /** Rows that were live and now are not; a repeat call answers 0. */
  retired: number;
}

/**
 * The operator write body (`POST /api/v1/admin/announcements`).
 *
 * Flat, and deliberately so: the RPC schema is `extra="forbid"`, so a nested
 * `payload` object — the shape the row is *stored* in — is a 422 on the way in.
 * `audience` has no `"user"` member here for the reason the server schema has
 * none either: a personal notification is written by the flow that causes it,
 * from a server-resolved recipient, never from a client-supplied id.
 */
export interface AnnouncementCreateBody {
  audience: Exclude<NotificationAudience, "user">;
  /** Required for `workspace`, and rejected for `global`. */
  workspace_id: number | null;
  /** Only the locales an operator actually wrote in. */
  locales: Partial<Record<string, AnnouncementLocaleText>>;
  default_locale: string;
  href: string | null;
  /** `null` publishes now, and a future stamp schedules it. */
  published_at: string | null;
  /** `null` never expires. */
  expires_at: string | null;
}
