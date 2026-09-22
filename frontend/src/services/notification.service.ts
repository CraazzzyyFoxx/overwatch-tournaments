import { apiFetch } from "@/lib/api/fetch";
import type {
  AnnouncementCreateBody,
  NotificationAdminPage,
  NotificationDeleteResult,
  NotificationInbox,
  NotificationItem,
  NotificationMarkReadResult,
  NotificationPreferences,
  NotificationPreferencesUpdate,
  NotificationRetireResult,
  NotificationWorkspaceConfig,
  NotificationWorkspaceConfigUpdate
} from "@/types/notification.types";

export default class notificationService {
  /**
   * One page of the caller's inbox, newest first, plus the badge count and an
   * opaque continuation. The audience is computed server-side from the token —
   * there is no recipient parameter, and `skipWorkspace` because the page spans
   * every workspace the caller belongs to rather than the current one.
   */
  static async list(params: { limit?: number; cursor?: string | null } = {}): Promise<NotificationInbox> {
    return apiFetch("/api/v1/notifications", {
      query: { limit: params.limit, cursor: params.cursor ?? undefined },
      skipWorkspace: true
    }).then((response) => response.json());
  }

  /**
   * Mark notifications read — which in this feature also means *dismissed*: the
   * announcement banner reads the same marks. `ids` omitted marks the whole
   * visible inbox, and that is the server's own semantic, so "mark all read"
   * must not enumerate the page it happens to be showing.
   */
  static async markRead(ids?: number[]): Promise<NotificationMarkReadResult> {
    return apiFetch("/api/v1/notifications/read", {
      method: "POST",
      body: ids ? { ids } : {},
      skipWorkspace: true
    }).then((response) => response.json());
  }

  /**
   * Remove notifications from *this* caller's inbox.
   *
   * Per viewer, not global: the row survives server-side, so throwing away a
   * platform-wide announcement does not take it out of anyone else's inbox.
   * `ids` omitted clears the whole visible inbox, and `onlyRead` narrows that
   * to the rows already marked read — the "clear read" button, which must not
   * be able to swallow something unopened.
   *
   * POST to a verb path rather than `DELETE /api/v1/notifications`: the id list
   * travels in the body, and a body on DELETE is the corner of HTTP that
   * caches and proxies disagree about.
   */
  static async remove(
    params: { ids?: number[]; onlyRead?: boolean } = {}
  ): Promise<NotificationDeleteResult> {
    return apiFetch("/api/v1/notifications/delete", {
      method: "POST",
      body: {
        ...(params.ids ? { ids: params.ids } : {}),
        ...(params.onlyRead ? { only_read: true } : {})
      },
      skipWorkspace: true
    }).then((response) => response.json());
  }

  /**
   * Platform-wide announcements for the banner. Anonymous callers are welcome
   * (the gateway caches that response for every visitor), so no workspace id
   * may ride along and fragment it.
   */
  static async activeAnnouncements(): Promise<NotificationItem[]> {
    return apiFetch("/api/v1/announcements/active", {
      skipWorkspace: true
    }).then((response) => response.json());
  }

  /**
   * One scope's announcements for the operator screen, expired ones included.
   *
   * `skipWorkspace` on all three writes and on this read: the scope is the
   * argument, not the ambient workspace. Without it the platform-wide feed
   * (`workspaceId: null`) would silently arrive scoped to whatever workspace
   * the switcher happens to hold, and a superuser would see an empty list
   * instead of the global announcements.
   */
  static async listAnnouncements(params: { workspaceId: number | null }): Promise<NotificationItem[]> {
    return apiFetch("/api/v1/admin/announcements", {
      query: params.workspaceId == null ? {} : { workspace_id: params.workspaceId },
      skipWorkspace: true
    }).then((response) => response.json());
  }

  /** Publish (or schedule) one. 422 when the locales do not cover the audience. */
  static async createAnnouncement(body: AnnouncementCreateBody): Promise<NotificationItem> {
    return apiFetch("/api/v1/admin/announcements", {
      method: "POST",
      body,
      skipWorkspace: true
    }).then((response) => response.json());
  }

  /**
   * Take it off the air. The row stays and so do its read marks — the server
   * sets `expires_at` to now rather than deleting, so "who saw this" survives.
   */
  static async retireAnnouncement(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/announcements/${id}`, {
      method: "DELETE",
      skipWorkspace: true
    });
  }

  /**
   * The notifications one workspace's own activity produced, newest first and
   * including already-retired rows — the operator screen exists to show them.
   *
   * `skipWorkspace` and an explicit `workspace_id` for the reason the
   * announcement reads give: the scope is the argument, not whatever the
   * switcher happens to hold, and the server authorizes exactly the id sent.
   */
  static async listWorkspaceNotifications(params: {
    workspaceId: number;
    kind?: string | null;
    cursor?: string | null;
    limit?: number;
  }): Promise<NotificationAdminPage> {
    return apiFetch("/api/v1/admin/notifications", {
      query: {
        workspace_id: params.workspaceId,
        kind: params.kind ?? undefined,
        cursor: params.cursor ?? undefined,
        limit: params.limit
      },
      skipWorkspace: true
    }).then((response) => response.json());
  }

  /**
   * Take produced notifications out of circulation: `ids`, a whole `kind`, or
   * both. Like the announcement retire this expires the rows rather than
   * deleting them, so the read marks that record who saw them survive.
   * Naming neither filter is a 422 — there is no "retire everything" call.
   */
  static async retireWorkspaceNotifications(params: {
    workspaceId: number;
    ids?: number[];
    kind?: string | null;
  }): Promise<NotificationRetireResult> {
    return apiFetch("/api/v1/admin/notifications/retire", {
      method: "POST",
      body: {
        workspace_id: params.workspaceId,
        ...(params.ids ? { ids: params.ids } : {}),
        ...(params.kind ? { kind: params.kind } : {})
      },
      skipWorkspace: true
    }).then((response) => response.json());
  }

  /**
   * The caller's own DM opt-outs. `skipWorkspace` like the inbox reads: the row
   * is per account and spans every workspace, and the recipient is the token.
   */
  static async preferences(): Promise<NotificationPreferences> {
    return apiFetch("/api/v1/notifications/preferences", { skipWorkspace: true }).then(
      (response) => response.json()
    );
  }

  /** Partial: a group left out of the body keeps whatever is stored. */
  static async updatePreferences(
    body: NotificationPreferencesUpdate
  ): Promise<NotificationPreferences> {
    return apiFetch("/api/v1/notifications/preferences", {
      method: "PUT",
      body,
      skipWorkspace: true
    }).then((response) => response.json());
  }

  /**
   * Where one workspace posts its broadcasts, and which of them it posts.
   * Scoped by the id in the path, not the switcher — the same rule the operator
   * reads above follow.
   */
  static async workspaceConfig(workspaceId: number): Promise<NotificationWorkspaceConfig> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/notification-config`).then((response) =>
      response.json()
    );
  }

  static async updateWorkspaceConfig(
    workspaceId: number,
    body: NotificationWorkspaceConfigUpdate
  ): Promise<NotificationWorkspaceConfig> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/notification-config`, {
      method: "PUT",
      body
    }).then((response) => response.json());
  }
}
