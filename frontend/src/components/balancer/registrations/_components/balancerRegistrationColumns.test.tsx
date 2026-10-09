import type { FilterFn, Row } from "@tanstack/react-table";
import { describe, expect, it } from "vitest";

import { readColumnMeta, readAdminColumnFilter } from "@/components/data-table";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { StatusMeta } from "@/types/registration.types";
import type { FormField } from "@/types/forms.types";

import { buildBalancerRegistrationColumns } from "./balancerRegistrationColumns";

function field(key: string, overrides: Partial<FormField> = {}): FormField {
  return {
    key,
    kind: "builtin",
    required: false,
    visibility: "public",
    params: {},
    ...overrides,
  };
}

const SCHEMA_FIELDS: FormField[] = [
  field("identity_battlenet"),
  field("identity_discord"),
  field("identity_twitch"),
  field("identity_boosty"),
  field("vk", { kind: "text", label: "VK profile" }),
  field("rules", { kind: "checkbox", label: "Read the rules", required: true }),
];

function registration(overrides: Partial<AdminRegistration> = {}): AdminRegistration {
  return {
    id: 1,
    primary_handle: "Player#1234",
    display_name: "Player",
    answers: {
      identity_battlenet: ["Player#1234", "Smurf#5678"],
      identity_discord: ["player"],
      identity_twitch: ["player_tv"],
      identity_boosty: ["player_boosty"],
    },
    source: "manual",
    source_record_key: null,
    ...overrides,
  } as unknown as AdminRegistration;
}

function column(id: string, ...args: Parameters<typeof buildBalancerRegistrationColumns>) {
  const found = buildBalancerRegistrationColumns(...args).find((candidate) => candidate.id === id);
  if (!found) {
    throw new Error(`No "${id}" column was built`);
  }

  return found;
}

describe("balancer registration column model", () => {
  it("builds one column per question the schema asks", () => {
    // The admin table rendered no custom fields at all: an organizer could read
    // an answer nowhere and fix it nowhere. Builtins are questions too — the
    // schema knows no difference — so they get their column the same way.
    const ids = buildBalancerRegistrationColumns(undefined, false, SCHEMA_FIELDS).map(
      (candidate) => candidate.id,
    );

    expect(ids).toContain("answer_vk");
    expect(ids).toContain("answer_rules");
    expect(ids).toContain("answer_identity_boosty");
  });

  it("keeps only the roles column out of the answer set — the BattleTags get one", () => {
    const ids = buildBalancerRegistrationColumns(undefined, false, [
      field("identity_battlenet"),
      field("roles"),
    ]).map((candidate) => candidate.id);

    expect(ids).not.toContain("answer_roles");
    // The participant column shows the primary handle; this one shows every
    // handle behind it, smurfs included.
    expect(ids).toContain("answer_identity_battlenet");
  });

  it("reads the stored answer for its own question", () => {
    const vk = column("answer_vk", undefined, false, SCHEMA_FIELDS);
    const meta = readColumnMeta<AdminRegistration>(vk.meta);

    const value = meta.searchValue?.(registration({ answers: { vk: "vk.com/player" } }));
    expect(value).toBe("vk.com/player");
  });

  it("adds no answer columns when the form asks nothing", () => {
    const ids = buildBalancerRegistrationColumns().map((candidate) => candidate.id);

    expect(ids.some((id) => id?.startsWith("answer_"))).toBe(false);
  });

  it("searches the participant by every handle the form collects, smurfs and boosty included", () => {
    const meta = readColumnMeta<AdminRegistration>(
      column("participant", undefined, false, SCHEMA_FIELDS).meta,
    );

    const searchText = meta.searchValue?.(registration());
    expect(searchText).toContain("player_boosty");
    expect(searchText).toContain("Player#1234");
    expect(searchText).toContain("Smurf#5678");
  });

  it("offers the status values the caller collected, not a hardcoded list", () => {
    // Statuses are workspace-configurable, so a literal list in the column would
    // hide every custom one an organizer added.
    const statusOptions = [
      { value: "pending", label: "Pending" },
      { value: "shortlisted", label: "Shortlisted" },
    ];

    const filter = readAdminColumnFilter(
      column("status", undefined, false, [], statusOptions).meta,
    );

    expect(filter?.param).toBe("status");
    expect(filter?.options).toEqual(statusOptions);
  });

  it("splits the balancer pool from the rows it excludes", () => {
    const balancer = column("balancer");
    const filterFn = balancer.filterFn as FilterFn<AdminRegistration>;
    const excludedRow = {
      original: registration({
        balancer_status: "excluded",
        balancer_status_meta: { excludes_from_balancer: true } as StatusMeta,
      }),
    } as Row<AdminRegistration>;

    expect(filterFn(excludedRow, "balancer", ["excluded"], () => {})).toBe(true);
    expect(filterFn(excludedRow, "balancer", ["included"], () => {})).toBe(false);
  });

  it("answers 'who agreed to cover' on its own axis, not through the pool", () => {
    const filterFn = column("balancer").filterFn as FilterFn<AdminRegistration>;
    const outOfPool = { excludes_from_balancer: true } as StatusMeta;
    const reserveRow = {
      original: registration({ answers: { reserve: true }, balancer_status_meta: outOfPool }),
    } as Row<AdminRegistration>;
    const plainRow = {
      original: registration({ answers: {}, balancer_status_meta: outOfPool }),
    } as Row<AdminRegistration>;

    expect(filterFn(reserveRow, "balancer", ["reserve"], () => {})).toBe(true);
    expect(filterFn(plainRow, "balancer", ["reserve"], () => {})).toBe(false);
    expect(filterFn(reserveRow, "balancer", ["not_reserve"], () => {})).toBe(false);
    expect(filterFn(plainRow, "balancer", ["not_reserve"], () => {})).toBe(true);
    // Both sit outside the pool, so the pool clause cannot tell a volunteer from
    // a row nobody has processed yet — which is why reserve is a second axis.
    expect(filterFn(reserveRow, "balancer", ["excluded"], () => {})).toBe(true);
    expect(filterFn(plainRow, "balancer", ["excluded"], () => {})).toBe(true);
  });

  it("offers the reserve axis on the same param as the pool split", () => {
    const filter = readAdminColumnFilter(column("balancer").meta);

    expect(filter?.param).toBe("inclusion");
    expect(filter?.options?.map((option) => option.value)).toEqual([
      "included",
      "excluded",
      "reserve",
      "not_reserve",
    ]);
  });
});
