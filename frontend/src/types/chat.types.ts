/**
 * The room chat wire shape (`shared/services/chat/schemas.py`). Identical for
 * every room kind by construction — one component, one hook and one service
 * serve the pre-game room and the draft room, parameterized only by the room
 * descriptor in `@/lib/realtime/chat-rooms`.
 */

/**
 * Who a participant is IN THIS ROOM. `home`/`away` name a pre-game side,
 * `captain` a drafting team's captain, `staff` an organizer, `spectator`
 * anybody who may watch but never write. Stored per message, never derived:
 * swapping a captain must not relabel a whole history.
 */
export type ChatRole = "home" | "away" | "captain" | "staff" | "spectator";

export interface ChatMessage {
  /** The message's identity AND its total order. */
  id: number;
  created_at: string;
  auth_user_id: number;
  /** Snapshot of the author's name at send time. */
  author_name: string;
  author_role: ChatRole;
  body: string;
  /**
   * The author's avatar as it is NOW — resolved per read, unlike
   * `author_name`, which is the snapshot taken when the message was sent.
   * `null` for an account that has not set one.
   */
  author_avatar_url: string | null;
}

export interface ChatSettings {
  spectators_can_read: boolean;
}

export interface ChatViewer {
  role: ChatRole;
  can_write: boolean;
  can_moderate: boolean;
  /** Set while this viewer is muted; `null` means an indefinite mute is absent. */
  muted_until: string | null;
}

export interface ChatMute {
  auth_user_id: number;
  /** `null` = until an organizer lifts it. */
  muted_until: string | null;
  reason: string | null;
  created_by_auth_user_id: number;
  created_at: string;
}

/**
 * One round trip answers everything the panel renders: the messages, whether
 * this viewer may type, whether they are muted, whether spectators can see the
 * room at all, and — for a moderator only — who is currently muted.
 */
export interface ChatEnvelope {
  messages: ChatMessage[];
  settings: ChatSettings;
  viewer: ChatViewer;
  mutes: ChatMute[];
}

/**
 * Every `chat.*` realtime payload, flattened into one optional-field shape the
 * way `DraftEventData` is: `chat.message` carries a whole `ChatMessage`,
 * `chat.muted` a whole `ChatMute`, and the other three carry one field each.
 */
export interface ChatEventData {
  id?: number;
  created_at?: string;
  auth_user_id?: number;
  author_name?: string;
  author_role?: ChatRole;
  body?: string;
  author_avatar_url?: string | null;
  muted_until?: string | null;
  reason?: string | null;
  created_by_auth_user_id?: number;
  spectators_can_read?: boolean;
}
