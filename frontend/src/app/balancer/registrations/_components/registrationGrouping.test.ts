import { describe, expect, it } from "bun:test";

import type { AdminRegistration, StatusMeta } from "@/types/balancer-admin.types";
import { groupRegistrations } from "./registrationGrouping";

const createStatusMeta = (value: string, scope: StatusMeta["scope"], name: string): StatusMeta => ({
  value,
  scope,
  is_builtin: true,
  kind: "builtin",
  is_override: false,
  can_edit: true,
  can_delete: false,
  can_reset: false,
  icon_slug: null,
  icon_color: null,
  name,
  description: null
});

const createRegistration = (
  id: number,
  overrides: Partial<AdminRegistration> = {}
): AdminRegistration =>
  ({
    id,
    tournament_id: 64,
    workspace_id: 1,
    auth_user_id: null,
    user_id: null,
    display_name: `Player ${id}`,
    battle_tag: `Player#${id}`,
    battle_tag_normalized: `player#${id}`,
    source: "manual",
    source_record_key: null,
    smurf_tags_json: [],
    discord_nick: null,
    twitch_nick: null,
    stream_pov: false,
    roles: [],
    notes: null,
    admin_notes: null,
    custom_fields_json: null,
    is_flex: false,
    status: "pending",
    status_meta: createStatusMeta("pending", "registration", "Pending"),
    balancer_status: "not_in_balancer",
    balancer_status_meta: createStatusMeta("not_in_balancer", "balancer", "Not Added"),
    exclude_from_balancer: false,
    exclude_reason: null,
    checked_in: false,
    checked_in_at: null,
    checked_in_by_username: null,
    deleted_at: null,
    submitted_at: null,
    reviewed_at: null,
    reviewed_by_username: null,
    balancer_profile_overridden_at: null,
    ...overrides
  }) as AdminRegistration;

describe("registration grouping", () => {
  it("groups registrations by check-in status", () => {
    const groups = groupRegistrations(
      [createRegistration(1, { checked_in: false }), createRegistration(2, { checked_in: true })],
      "check_in"
    );

    expect(
      groups.map((group) => [group.key, group.label, group.registrations.map((item) => item.id)])
    ).toEqual([
      ["checked_in", "Checked in", [2]],
      ["not_checked_in", "Not checked in", [1]]
    ]);
  });

  it("groups registrations by balancer status using status meta labels", () => {
    const groups = groupRegistrations(
      [
        createRegistration(1, {
          balancer_status: "not_in_balancer",
          balancer_status_meta: createStatusMeta("not_in_balancer", "balancer", "Not Added")
        }),
        createRegistration(2, {
          balancer_status: "ready",
          balancer_status_meta: createStatusMeta("ready", "balancer", "Ready")
        }),
        createRegistration(3, {
          balancer_status: "ready",
          balancer_status_meta: createStatusMeta("ready", "balancer", "Ready")
        })
      ],
      "balancer_status"
    );

    expect(
      groups.map((group) => [group.key, group.label, group.registrations.map((item) => item.id)])
    ).toEqual([
      ["ready", "Ready", [2, 3]],
      ["not_in_balancer", "Not Added", [1]]
    ]);
  });

  it("groups registrations by computed admission status", () => {
    const groups = groupRegistrations(
      [
        createRegistration(1, {
          status: "approved",
          balancer_status: "ready",
          checked_in: true
        }),
        createRegistration(2, {
          status: "approved",
          balancer_status: "ready",
          checked_in: false
        }),
        createRegistration(3, {
          status: "pending",
          balancer_status: "ready",
          checked_in: true
        })
      ],
      "admission"
    );

    expect(
      groups.map((group) => [group.key, group.label, group.registrations.map((item) => item.id)])
    ).toEqual([
      ["admitted", "Admitted", [1]],
      ["not_admitted", "Not admitted", [2, 3]]
    ]);
  });

  it("groups registrations by computed admission status with requireOpenProfile enabled", () => {
    const groups = groupRegistrations(
      [
        createRegistration(1, {
          status: "approved",
          balancer_status: "ready",
          checked_in: true,
          profiles_open: true
        }),
        createRegistration(2, {
          status: "approved",
          balancer_status: "ready",
          checked_in: true,
          profiles_open: false
        }),
        createRegistration(3, {
          status: "approved",
          balancer_status: "ready",
          checked_in: true,
          profiles_open: null
        })
      ],
      "admission",
      true
    );

    expect(
      groups.map((group) => [group.key, group.label, group.registrations.map((item) => item.id)])
    ).toEqual([
      ["admitted", "Admitted", [1, 3]],
      ["not_admitted", "Not admitted", [2]]
    ]);
  });
});
