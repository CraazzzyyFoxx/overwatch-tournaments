import { describe, expect, it } from "bun:test";

import { notificationHref } from "@/lib/notification-href";
import type { NotificationItem } from "@/types/notification.types";

const item: NotificationItem = {
  id: 1,
  audience: "user",
  kind: "registration.approved",
  payload: {},
  workspace_id: null,
  published_at: "2026-09-08T00:00:00Z",
  expires_at: null,
  is_read: false
};

describe("notification destinations", () => {
  it("opens the participant surface from numeric tournament snapshots", () => {
    for (const kind of [
      "team_invite.received",
      "registration.approved",
      "registration.rejected",
      "team.kicked",
      "team.rejected",
      "team.disbanded",
    ]) {
      expect(notificationHref({ ...item, kind, payload: { tournament_id: 42 } })).toBe(
        "/tournaments/42/participants"
      );
    }
  });

  it("opens the room where captains can correct disputed map reports", () => {
    expect(
      notificationHref({
        ...item,
        kind: "encounter.report_disputed",
        payload: { tournament_id: 42, encounter_id: 87, map_id: 3, map_index: 1 }
      })
    ).toBe("/tournaments/42/pregame/87");
    expect(
      notificationHref({
        ...item,
        kind: "encounter.report_disputed",
        payload: { encounter_id: 87 }
      })
    ).toBeNull();
    expect(
      notificationHref({
        ...item,
        kind: "encounter.report_disputed",
        payload: { tournament_id: 42, encounter_id: "87/../../admin" }
      })
    ).toBeNull();
  });

  it("rejects malformed IDs instead of coercing wire values into routes", () => {
    for (const tournament_id of [
      undefined,
      null,
      "42",
      "../../admin",
      0,
      -1,
      1.5,
      Number.MAX_SAFE_INTEGER + 1
    ]) {
      expect(notificationHref({ ...item, payload: { tournament_id } })).toBeNull();
    }
  });

  it("never substitutes unrelated team routes or system-provided hrefs", () => {
    expect(
      notificationHref({
        ...item,
        kind: "team_invite.answered",
        payload: { team_id: 7, invite_id: 9, answer: "accepted", href: "/teams/7" }
      })
    ).toBeNull();
    expect(
      notificationHref({ ...item, kind: "future.kind", payload: { href: "/admin" } })
    ).toBeNull();
    expect(notificationHref({ ...item, payload: { href: "/admin" } })).toBeNull();
  });

  it("uses the existing safe announcement link contract", () => {
    const announcement = { ...item, kind: "announcement.published" };
    expect(
      notificationHref({ ...announcement, payload: { href: "https://example.com/news" } })
    ).toBe("https://example.com/news");
    expect(notificationHref({ ...announcement, payload: { href: "/news" } })).toBe("/news");
    expect(
      notificationHref({ ...announcement, payload: { href: "javascript:alert(1)" } })
    ).toBeNull();
    expect(notificationHref({ ...announcement, payload: { href: "//example.com" } })).toBeNull();
  });
});
