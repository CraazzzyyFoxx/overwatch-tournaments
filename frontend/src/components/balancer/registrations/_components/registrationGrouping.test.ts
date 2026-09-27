import { describe, expect, it } from "vitest";

import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { Admission, AdmissionDecision, StatusMeta } from "@/types/registration.types";
import { groupRegistrations } from "./registrationGrouping";

/** The server's answer, as the read sends it. Only `decision` is load-bearing
 *  for grouping — that is the whole point of the layer: the grouping key is a
 *  projection of one field, not a re-derivation from four. */
const admission = (decision: AdmissionDecision): Admission => ({
  decision,
  requirements: [],
  blockers: [],
  overridden: [],
  checked_in: decision === "admitted",
  ready: decision !== "not_admitted"
});

const createStatusMeta = (
  value: string,
  scope: StatusMeta["scope"],
  name: string,
  excludesFromBalancer = false,
  excludesFromReady = false
): StatusMeta => ({
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
  description: null,
  excludes_from_balancer: excludesFromBalancer,
  excludes_from_ready: excludesFromReady
});

const createRegistration = (
  id: number,
  overrides: Partial<AdminRegistration> = {}
): AdminRegistration =>
  ({
    id,
    tournament_id: 64,
    workspace_id: 1,
    user_id: null,
    display_name: `Player ${id}`,
    battle_tag: `Player#${id}`,
    battle_tag_normalized: `player#${id}`,
    source: "manual",
    source_record_key: null,
    roles: [],
    answers: { smurf_tags: [], stream_pov: false },
    form_version_id: 2,
    form_version_stale: false,
    admin_notes: null,
    is_flex: false,
    status: "pending",
    status_meta: createStatusMeta("pending", "registration", "Pending"),
    balancer_status: "not_in_balancer",
    balancer_status_meta: createStatusMeta("not_in_balancer", "balancer", "Not Added", true),
    exclude_reason: null,
    checked_in: false,
    checked_in_at: null,
    checked_in_by_username: null,
    deleted_at: null,
    submitted_at: null,
    reviewed_at: null,
    reviewed_by_username: null,
    balancer_profile_overridden_at: null,
    admission: admission("not_admitted"),
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

  it("groups registrations by the server's admission decision", () => {
    const groups = groupRegistrations(
      [
        createRegistration(1, { admission: admission("admitted") }),
        createRegistration(2, { admission: admission("pending_check_in") }),
        createRegistration(3, { admission: admission("not_admitted") })
      ],
      "admission"
    );

    expect(
      groups.map((group) => [group.key, group.label, group.registrations.map((item) => item.id)])
    ).toEqual([
      ["admitted", "Admitted", [1]],
      ["pending_check_in", "Check-in pending", [2]],
      ["not_admitted", "Not admitted", [3]]
    ]);
  });

  it("reads nothing but the decision, so the raw signals cannot disagree with it", () => {
    // Four separate copies of the admission rule used to answer this from
    // `status`, `balancer_status`, `profiles_open` and `subscription_outcome`,
    // and two of them ignored the subscription. A row whose raw fields all say
    // "out" but whose server decision says "admitted" — a hand check-in with a
    // since-closed profile — must group as admitted, or the override this layer
    // exists to represent is broken again on the way out.
    const groups = groupRegistrations(
      [
        createRegistration(1, {
          status: "rejected",
          balancer_status: "not_in_balancer",
          profiles_open: false,
          subscription_outcome: "refused",
          admission: admission("admitted")
        })
      ],
      "admission"
    );

    expect(groups.map((group) => group.key)).toEqual(["admitted"]);
  });

  it("keeps one section per decision, in reading order", () => {
    // Encounter order is the reverse of the intended order, so a group list that
    // merely preserved insertion would fail this.
    const groups = groupRegistrations(
      [
        createRegistration(1, { admission: admission("not_admitted") }),
        createRegistration(2, { admission: admission("pending_check_in") }),
        createRegistration(3, { admission: admission("admitted") }),
        createRegistration(4, { admission: admission("admitted") })
      ],
      "admission"
    );

    expect(groups.map((group) => [group.key, group.registrations.length])).toEqual([
      ["admitted", 2],
      ["pending_check_in", 1],
      ["not_admitted", 1]
    ]);
  });
});
