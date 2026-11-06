import { poll } from "../support/api";
import { expect, test } from "../support/fixtures";
import { OW_FORM, battleTag, rankRegistration, registerSelf, type Registration } from "../support/flows";
import {
  FULL_FORM,
  HOUR,
  ROLE,
  at,
  openTournament,
  type AdminRegistration,
  type MyRegistration,
  type PublicForm,
} from "../support/registration";
import { createTournament, createWorkspace, flowNodes, nodeOf, transitionNode, uniq } from "../support/seed";

// Individual registration after schemasplit01 moved it into the `registration`
// schema: organizer form + templates + status catalog, the player's own
// lifecycle, the organizer's review queue, check-in and subscription gating.

const adminForm = (tid: number) => `/api/v1/admin/balancer/tournaments/${tid}/registration-form`;
const adminRegs = (tid: number) => `/api/v1/admin/balancer/tournaments/${tid}/registrations`;
const adminReg = (rid: number) => `/api/v1/admin/balancer/registrations/${rid}`;
const pub = (tid: number) => `/api/v1/tournaments/${tid}/registration`;

const fullAnswers = (username: string, extra: Record<string, unknown> = {}) => ({
  identity_battlenet: [battleTag(username)],
  roles: [
    { role: "tank", is_primary: true },
    { role: "support", is_primary: false },
  ],
  current_rank: { tank: 3000, support: 2500 },
  tshirt: "M",
  ...extra,
});

test.describe("organizer: registration form", () => {
  test("form is absent until saved, versions on change, and the registration node opens the sign-up", async ({ adminApi, anonApi }) => {
    const ws = await createWorkspace(adminApi);
    const t = await createTournament(adminApi, ws.id);
    expect(await adminApi.get(adminForm(t.id)), "admin form before any save").toBeNull();
    expect(await anonApi.get(`${pub(t.id)}/form`), "public form before any save").toBeNull();

    const bad = await adminApi.raw("PUT", adminForm(t.id), {
      body: { form_schema: { sections: [{ key: "x", fields: [{ key: "q", kind: "text" }] }] } },
    });
    expect(bad.status(), "a custom question without a label is refused at save time").toBe(422);

    const v1 = await adminApi.put<PublicForm>(adminForm(t.id), { form_schema: FULL_FORM, auto_approve: false, max_participants: 32 });
    expect(v1.version_number).toBe(1);
    const resaved = await adminApi.put<PublicForm>(adminForm(t.id), { form_schema: v1.form_schema, max_participants: 32 });
    expect(resaved.version_id, "an identical question set does not append a version").toBe(v1.version_id);

    const closed = await anonApi.get<PublicForm>(`${pub(t.id)}/form`);
    expect(closed.version_id).toBe(v1.version_id);
    expect(closed.form_schema.sections.map((s) => s.key)).toEqual(["accounts", "play", "details"]);
    const node = await nodeOf(adminApi, t.id, "registration");
    expect(node.status, "the intake is draft until an organizer opens it").toBe("draft");

    // Openness is the node's: its status, inside the `open` window.
    await adminApi.put(`/api/v1/admin/flow-nodes/${node.id}/schedule`, {
      schedule: [{ phase: "open", starts_at: at(-HOUR), ends_at: at(24 * HOUR) }],
    });
    await transitionNode(adminApi, node.id, "open");
    expect((await flowNodes(anonApi, t.id)).find((candidate) => candidate.id === node.id)?.status).toBe("open");

    const v2 = await adminApi.put<PublicForm>(adminForm(t.id), {
      form_schema: { sections: [...FULL_FORM.sections, { key: "extra", fields: [{ key: "team_pref", kind: "text", label: "Preferred team" }] }] },
    });
    expect(v2.version_number, "changing the questions appends version 2").toBe(2);
    expect((await anonApi.get<PublicForm>(`${pub(t.id)}/form`)).version_id).toBe(v2.version_id);
  });

  test("a stale form version is refused and the registrant's card flags the change", async ({ adminApi, makeUser }) => {
    const { t, version } = await openTournament(adminApi, { form: FULL_FORM });
    const early = await makeUser("stale");
    await early.api.post(pub(t.id), { form_version_id: version, answers: fullAnswers(early.username) }, 201);

    await adminApi.put(adminForm(t.id), {
      form_schema: { sections: [...FULL_FORM.sections, { key: "extra", fields: [{ key: "mic", kind: "checkbox", label: "Has a mic" }] }] },
    });
    const late = await makeUser("stale");
    const refused = await late.api.raw("POST", pub(t.id), { body: { form_version_id: version, answers: fullAnswers(late.username) } });
    expect(refused.status()).toBe(409);
    expect(JSON.stringify(await refused.json())).toContain("form_version_stale");

    const mine = await early.api.get<MyRegistration>(`${pub(t.id)}/me`);
    expect(mine.form_version_stale, "the earlier registrant is told the questions moved on").toBe(true);
    const admin = await adminApi.get<{ stale_registrations: number }>(adminForm(t.id));
    expect(admin.stale_registrations).toBe(1);
  });

  test("workspace templates: CRUD, save the tournament's questions, apply a template as a new version", async ({ adminApi }) => {
    const { ws, t } = await openTournament(adminApi, { form: FULL_FORM });
    const lib = `/api/v1/admin/ws/${ws.id}/registration-form-templates`;
    const minimal = {
      sections: [
        { key: "accounts", fields: [{ key: "identity_battlenet", kind: "builtin", required: true }] },
        { key: "extra", fields: [{ key: "note", kind: "text", label: "Note" }] },
      ],
    };

    const saved = await adminApi.post<{ id: number; name: string; discipline: string }>(
      `${adminForm(t.id)}/save-template`,
      { name: "Cup questions" },
      201
    );
    expect(saved.discipline, "a saved template belongs to the tournament's game").toBe("overwatch");

    const noGame = await adminApi.raw("POST", lib, { body: { name: "No game", form_schema: minimal } });
    expect(noGame.status(), "a template without a discipline is refused").toBe(422);

    const created = await adminApi.post<{ id: number }>(lib, { name: "Minimal", discipline: "overwatch", form_schema: minimal }, 201);
    const renamed = await adminApi.put<{ name: string }>(`${lib}/${created.id}`, { name: "Minimal v2", form_schema: minimal });
    expect(renamed.name).toBe("Minimal v2");
    const otherGame = await adminApi.raw("PUT", `${lib}/${created.id}`, { body: { name: "x", discipline: "lol", form_schema: minimal } });
    expect(otherGame.status(), "a template's game is immutable").toBe(409);

    const listed = await adminApi.get<{ id: number; name: string }[]>(lib, { discipline: "overwatch" });
    expect(listed.map((x) => x.name).sort()).toEqual(["Cup questions", "Minimal v2"]);

    const applied = await adminApi.post<PublicForm>(`${adminForm(t.id)}/apply-template`, { template_id: created.id });
    expect(applied.version_number, "applying a template appends a form version").toBe(2);
    expect(applied.form_schema.sections.map((s) => s.key)).toEqual(["accounts", "extra"]);

    await adminApi.delete(`${lib}/${created.id}`, 204);
    expect((await adminApi.get<{ name: string }[]>(lib)).map((x) => x.name)).toEqual(["Cup questions"]);
  });
});

test.describe("organizer: balancer status catalog", () => {
  test("custom statuses: create, rename, list in catalog, assign in bulk, delete", async ({ adminApi, makeUser }) => {
    const { ws, t, version, registrationNodeId } = await openTournament(adminApi);
    const base = `/api/v1/admin/ws/${ws.id}/balancer-statuses`;
    type Status = { id: number; slug: string; scope: string; kind: string; name: string; excludes_from_balancer: boolean };

    const bench = await adminApi.post<Status>(`${base}/custom`, { scope: "balancer", name: "Bench", icon_color: "#ff0000", excludes_from_balancer: true }, 201);
    expect(bench).toMatchObject({ slug: "bench", kind: "custom", excludes_from_balancer: true });
    const info = await adminApi.post<Status>(`${base}/custom`, { scope: "registration", name: "Needs info" }, 201);
    const renamed = await adminApi.patch<Status>(`${base}/custom/${bench.id}`, { name: "Bench warmers" });
    expect(renamed.name).toBe("Bench warmers");
    expect(renamed.slug, "renaming keeps the slug registrations reference").toBe("bench");

    const catalog = await adminApi.get<Status[]>(`${base}/catalog`);
    const customInCatalog = catalog.filter((s) => s.kind === "custom").map((s) => `${s.scope}:${s.slug}`);
    expect(customInCatalog.sort()).toEqual(["balancer:bench", "registration:needs_info"]);
    expect(catalog.some((s) => s.kind === "builtin" && s.scope === "registration" && s.slug === "pending"), "the catalog lists the built-in statuses too").toBe(true);
    expect((await adminApi.get<Status[]>(base)).map((s) => s.slug).sort()).toEqual(["bench", "needs_info"]);

    const player = await makeUser("cst");
    const reg = await registerSelf(player, t.id, registrationNodeId, version, { roles: ["damage"] });
    await adminApi.patch(`${adminReg(reg.id)}/approve`);
    const res = await adminApi.post<{ updated: number; skipped: number }>(`${adminRegs(t.id)}/bulk-set-balancer-status`, {
      registration_ids: [reg.id],
      balancer_status: "bench",
    });
    expect(res).toEqual({ updated: 1, skipped: 0 });
    const [row] = await adminApi.get<AdminRegistration[]>(adminRegs(t.id));
    expect(row.balancer_status).toBe("bench");
    expect(row.balancer_status_meta).toMatchObject({ name: "Bench warmers", excludes_from_balancer: true });
    const excluded = await adminApi.get<AdminRegistration[]>(adminRegs(t.id), { inclusion_filter: "excluded" });
    expect(excluded.map((r) => r.id), "a status that excludes from the balancer filters as excluded").toEqual([reg.id]);

    const unknown = await adminApi.raw("PATCH", `${adminReg(reg.id)}/balancer-status`, { body: { balancer_status: "no_such_status" } });
    expect(unknown.status(), "an unknown balancer status is refused").toBe(400);

    await adminApi.delete(`${base}/custom/${info.id}`, 204);
    expect((await adminApi.get<Status[]>(base)).map((s) => s.slug)).toEqual(["bench"]);
  });

  test("system statuses can be overridden per workspace and reset", async ({ adminApi }) => {
    const ws = await createWorkspace(adminApi);
    const base = `/api/v1/admin/ws/${ws.id}/balancer-statuses`;
    const unknown = await adminApi.raw("PUT", `${base}/system/registration/not_a_status`, { body: { name: "x" } });
    expect(unknown.status()).toBe(400);

    // The override copies the canonical (workspace_id NULL) builtin row; on a
    // freshly migrated database that row must exist for this to work.
    const res = await adminApi.raw("PUT", `${base}/system/registration/pending`, { body: { name: "Awaiting review", icon_color: "#123456" } });
    expect(res.status(), `override a builtin status -> ${res.status()} ${await res.text()}`).toBe(200);
    const catalog = await adminApi.get<{ slug: string; name: string; is_override: boolean }[]>(`${base}/catalog`);
    expect(catalog.find((s) => s.slug === "pending")).toMatchObject({ name: "Awaiting review", is_override: true });
    await adminApi.delete(`${base}/system/registration/pending`, 204);
    const after = await adminApi.get<{ slug: string; is_override: boolean }[]>(`${base}/catalog`);
    expect(after.find((s) => s.slug === "pending")?.is_override ?? false).toBe(false);
  });
});

test.describe("player: self-service registration", () => {
  test("register, read, edit only editable answers, duplicate refused, withdraw is final", async ({ adminApi, anonApi, makeUser }) => {
    const { t, version } = await openTournament(adminApi, { form: FULL_FORM });
    const player = await makeUser("self");

    const missingRank = await player.api.raw("POST", pub(t.id), {
      body: { form_version_id: version, answers: fullAnswers(player.username, { current_rank: { tank: 3000 } }) },
    });
    expect(missingRank.status(), "a rank is required for every declared role").toBe(422);
    expect(JSON.stringify(await missingRank.json())).toContain("current_rank");

    const answers = fullAnswers(player.username, { staff_note: "needs a mic" });
    const created = await player.api.post<MyRegistration>(pub(t.id), { form_version_id: version, answers }, 201);
    expect(created.status).toBe("pending");
    expect(created.primary_handle).toBe(answers.identity_battlenet[0]);
    expect(created.roles.map((r) => [r.role.role, r.is_primary])).toEqual([
      ["tank", true],
      ["support", false],
    ]);
    expect(created.answers).toMatchObject({ current_rank: { tank: 3000, support: 2500 }, tshirt: "M" });
    expect(created.queue_position).toBe(1);
    expect(created.can_edit).toBe(true);
    expect(created.edit_writable_keys).toEqual(expect.arrayContaining(["public_notes", "tshirt"]));
    expect(created.edit_writable_keys, "the BattleTag is frozen at submit").not.toContain("identity_battlenet");

    const me = await player.api.get<MyRegistration>(`${pub(t.id)}/me`);
    expect(me.id).toBe(created.id);
    expect((await anonApi.raw("GET", `${pub(t.id)}/me`)).status()).toBe(401);

    const edited = await player.api.patch<MyRegistration>(`${pub(t.id)}/me`, {
      form_version_id: version,
      answers: { tshirt: "L", public_notes: "duo with a friend" },
    });
    expect(edited.answers).toMatchObject({ tshirt: "L", public_notes: "duo with a friend", current_rank: { tank: 3000, support: 2500 } });
    const locked = await player.api.raw("PATCH", `${pub(t.id)}/me`, {
      body: { form_version_id: version, answers: { identity_battlenet: [battleTag(`x${player.username}`)] } },
    });
    expect(locked.status(), "a non-editable answer cannot be rewritten by the registrant").toBe(409);

    const dup = await player.api.raw("POST", pub(t.id), { body: { form_version_id: version, answers } });
    expect(dup.status(), "a second registration for the same tournament").toBe(409);

    const withdrawn = await player.api.delete<{ status: string }>(`${pub(t.id)}/me`);
    expect(withdrawn.status).toBe("withdrawn");
    expect((await player.api.get<MyRegistration>(`${pub(t.id)}/me`)).status).toBe("withdrawn");
    const again = await player.api.raw("POST", pub(t.id), { body: { form_version_id: version, answers } });
    expect(again.status(), "a withdrawn registration cannot be resubmitted").toBe(409);
  });

  test("registration outside the window is refused; allow_late_registration admits and marks latecomers", async ({ adminApi, makeUser }) => {
    const ws = await createWorkspace(adminApi);
    const t = await createTournament(adminApi, ws.id);
    const form = await adminApi.put<PublicForm>(adminForm(t.id), { form_schema: OW_FORM });
    const node = await nodeOf(adminApi, t.id, "registration");
    const setWindow = (starts: number, ends: number) =>
      adminApi.put(`/api/v1/admin/flow-nodes/${node.id}/schedule`, { schedule: [{ phase: "open", starts_at: at(starts), ends_at: at(ends) }] });
    const player = await makeUser("win");
    const body = { form_version_id: form.version_id, answers: { identity_battlenet: [battleTag(player.username)], roles: [{ role: "tank", is_primary: true }] } };

    expect((await player.api.raw("POST", pub(t.id), { body })).status(), "the intake is still draft").toBe(400);

    await setWindow(2 * HOUR, 24 * HOUR);
    await transitionNode(adminApi, node.id, "open");
    expect((await player.api.raw("POST", pub(t.id), { body })).status(), "window not started").toBe(400);

    await setWindow(-3 * HOUR, -HOUR);
    expect((await player.api.raw("POST", pub(t.id), { body })).status(), "window already closed").toBe(400);

    // Late registration is the node's switch: it lifts the end of the window and nothing else.
    await adminApi.put(`/api/v1/admin/tournaments/${t.id}/flow`, {
      nodes: [{ id: node.id, kind: node.kind, name: node.name, config: { ...node.config, allow_late_registration: true } }],
    });
    const reg = await player.api.post<MyRegistration>(pub(t.id), body, 201);
    expect(reg.submitted_late).toBe(true);
    const [row] = await adminApi.get<AdminRegistration[]>(adminRegs(t.id));
    expect(row.submitted_late).toBe(true);
  });

  test("public participants list hides organizer-only answers and collapses under hide_registrations", async ({ adminApi, anonApi, makeUser }) => {
    const { t, version } = await openTournament(adminApi, { form: FULL_FORM });
    const [a, b] = [await makeUser("lst"), await makeUser("lst")];
    const answersA = fullAnswers(a.username, { staff_note: "secret" });
    const answersB = { ...fullAnswers(b.username), roles: [{ role: "damage", is_primary: true }], current_rank: { damage: 2800 } };
    await a.api.post(pub(t.id), { form_version_id: version, answers: answersA }, 201);
    await b.api.post(pub(t.id), { form_version_id: version, answers: answersB }, 201);

    type PublicList = { registrations: Registration[]; hidden: boolean; total: number; role_counts: Record<string, number>; max_participants: number | null };
    const list = await anonApi.get<PublicList>(`${pub(t.id)}/list`);
    expect(list.total).toBe(2);
    expect(list.registrations.map((r) => r.primary_handle).sort()).toEqual(
      [answersA.identity_battlenet[0], answersB.identity_battlenet[0]].sort()
    );
    for (const r of list.registrations) expect(r.answers, "organizers-only answer on the public list").not.toHaveProperty("staff_note");
    expect(list.role_counts).toEqual({ tank: 1, damage: 1 });
    const adminRows = await adminApi.get<AdminRegistration[]>(adminRegs(t.id));
    expect(adminRows.find((r) => r.primary_handle === answersA.identity_battlenet[0])?.answers.staff_note, "the organizer sees it").toBe("secret");

    const form = await adminApi.get<PublicForm>(adminForm(t.id));
    await adminApi.put(adminForm(t.id), { form_schema: form.form_schema, hide_registrations: true, max_participants: 10 });
    // Eventually consistent through the gateway's 30 s response-cache TTL; the
    // immediate eviction is pinned separately below.
    const hidden = await poll(
      async () => {
        const read = await anonApi.get<PublicList>(`${pub(t.id)}/list`);
        return read.hidden ? read : undefined;
      },
      "public list collapses under hide_registrations",
      45_000
    );
    expect(hidden).toMatchObject({ hidden: true, registrations: [], total: 2, role_counts: { tank: 1, damage: 1 }, max_participants: 10 });
  });

  test("saving the form evicts the cached public participants list at once", async ({ adminApi, anonApi, makeUser }) => {
    const { t, version, registrationNodeId } = await openTournament(adminApi);
    await registerSelf(await makeUser("evc"), t.id, registrationNodeId, version, { roles: ["tank"] });
    const before = await anonApi.get<{ hidden: boolean; registrations: unknown[] }>(`${pub(t.id)}/list`);
    expect(before.registrations).toHaveLength(1);
    const form = await adminApi.get<PublicForm>(adminForm(t.id));
    await adminApi.put(adminForm(t.id), { form_schema: form.form_schema, hide_registrations: true });
    const after = await anonApi.get<{ hidden: boolean; registrations: unknown[] }>(`${pub(t.id)}/list`);
    expect(after.hidden, "right after the organizer hides registrations, the public list must not keep serving names").toBe(true);
    expect(after.registrations).toEqual([]);
  });
});

test.describe("organizer: review queue", () => {
  test("filters, approve/reject, bulk approve, balancer inclusion, withdraw/restore, soft delete, admin check-in", async ({ adminApi, admin, makeUser }) => {
    const { t, version, registrationNodeId } = await openTournament(adminApi);
    const users = [await makeUser("rq"), await makeUser("rq"), await makeUser("rq"), await makeUser("rq")];
    const [a, b, c, d] = await Promise.all(users.map((u, i) => registerSelf(u, t.id, registrationNodeId, version, { roles: [["tank", "damage", "support", "damage"][i]] })));

    const pending = await adminApi.get<AdminRegistration[]>(adminRegs(t.id), { status_filter: "pending" });
    expect(pending.map((r) => r.id).sort()).toEqual([a.id, b.id, c.id, d.id].sort());

    const approved = await adminApi.patch<AdminRegistration>(`${adminReg(a.id)}/approve`);
    expect(approved.status).toBe("approved");
    expect.soft(approved.reviewed_by_username, "approve response names the reviewer").toBe(admin.username);
    const reviewed = (await adminApi.get<AdminRegistration[]>(adminRegs(t.id))).find((r) => r.id === a.id);
    expect(reviewed?.reviewed_by_username, "the review queue names the reviewer").toBe(admin.username);
    expect((await adminApi.patch<AdminRegistration>(`${adminReg(b.id)}/reject`)).status).toBe("rejected");
    expect((await adminApi.get<AdminRegistration[]>(adminRegs(t.id), { status_filter: "rejected" })).map((r) => r.id)).toEqual([b.id]);

    const bulk = await adminApi.post<{ approved: number; skipped: number }>(`${adminRegs(t.id)}/bulk-approve`, {
      registration_ids: [a.id, c.id, d.id],
    });
    expect(bulk, "already-approved rows are skipped, not re-approved").toEqual({ approved: 2, skipped: 1 });

    const rejectedInclude = await adminApi.raw("POST", `${adminReg(b.id)}/include`);
    expect(rejectedInclude.status(), "only approved registrations enter the pool").toBe(409);
    expect((await adminApi.post<AdminRegistration>(`${adminReg(c.id)}/include`)).balancer_status, "no rank yet").toBe("incomplete");
    await rankRegistration(adminApi, d.id, [{ role: ROLE("damage"), rank: 3200 }]);
    expect((await adminApi.post<AdminRegistration>(`${adminReg(d.id)}/include`)).balancer_status, "every role ranked").toBe("ready");

    const autoManaged = await adminApi.raw("PATCH", `${adminReg(c.id)}/balancer-status`, { body: { balancer_status: "ready" } });
    expect(autoManaged.status(), "ready/incomplete are derived, never set by hand").toBe(400);
    const excluded = await adminApi.patch<AdminRegistration>(`${adminReg(c.id)}/balancer-status`, {
      balancer_status: "excluded",
      exclude_reason: "no mic",
    });
    expect(excluded).toMatchObject({ balancer_status: "excluded", exclude_reason: "no mic" });
    const included = await adminApi.get<AdminRegistration[]>(adminRegs(t.id), { inclusion_filter: "included" });
    expect(included.map((r) => r.id)).toEqual([d.id]);

    const bulkAdd = await adminApi.post<{ updated: number; skipped: number }>(`${adminRegs(t.id)}/bulk-add-to-balancer`, {
      registration_ids: [a.id, b.id, c.id],
    });
    expect(bulkAdd, "the rejected row is skipped").toEqual({ updated: 2, skipped: 1 });
    const bulkOut = await adminApi.post<{ updated: number; skipped: number }>(`${adminRegs(t.id)}/bulk-set-balancer-status`, {
      registration_ids: [a.id, c.id],
      balancer_status: "not_in_balancer",
    });
    expect(bulkOut).toEqual({ updated: 2, skipped: 0 });

    expect((await adminApi.patch<AdminRegistration>(`${adminReg(a.id)}/withdraw`)).status).toBe("withdrawn");
    expect((await adminApi.patch<AdminRegistration>(`${adminReg(a.id)}/restore`)).status).toBe("approved");

    const checked = await adminApi.patch<AdminRegistration>(`${adminReg(d.id)}/check-in`, { checked_in: true });
    expect(checked.checked_in, "organizer check-in is not gated by the CHECK_IN phase").toBe(true);
    expect.soft(checked.checked_in_by_username, "check-in response names who checked in").toBe(admin.username);
    const checkedRow = (await adminApi.get<AdminRegistration[]>(adminRegs(t.id))).find((r) => r.id === d.id);
    expect(checkedRow?.checked_in_by_username, "the review queue names who checked in").toBe(admin.username);
    const unchecked = await adminApi.patch<AdminRegistration>(`${adminReg(d.id)}/check-in`, { checked_in: false });
    expect(unchecked).toMatchObject({ checked_in: false, checked_in_by_username: null });

    await adminApi.delete(adminReg(c.id), 204);
    expect((await adminApi.get<AdminRegistration[]>(adminRegs(t.id))).map((r) => r.id)).not.toContain(c.id);
    const withDeleted = await adminApi.get<AdminRegistration[]>(adminRegs(t.id), { include_deleted: true });
    expect(withDeleted.find((r) => r.id === c.id)?.deleted_at, "soft-deleted rows stay readable on request").toBeTruthy();
    const mine = await users[2].api.get<MyRegistration | null>(`${pub(t.id)}/me`);
    expect(mine, "a deleted registration is gone from the player's own card").toBeNull();
  });

  test("a plain user cannot read or act on the review queue", async ({ adminApi, makeUser }) => {
    const { t, version, registrationNodeId } = await openTournament(adminApi);
    const player = await makeUser("nr");
    const reg = await registerSelf(player, t.id, registrationNodeId, version, { roles: ["tank"] });
    expect((await player.api.raw("GET", adminRegs(t.id))).status()).toBe(403);
    expect((await player.api.raw("PATCH", `${adminReg(reg.id)}/approve`)).status()).toBe(403);
    expect((await player.api.raw("GET", adminForm(t.id))).status()).toBe(403);
  });

  test("rank autofill preview/apply keeps organizer ranks; rank history reads past registrations of one game", async ({ adminApi, makeUser }) => {
    const { ws, t, version, registrationNodeId } = await openTournament(adminApi);
    const player = await makeUser("rk");
    const reg = await registerSelf(player, t.id, registrationNodeId, version, { roles: ["tank", "support"] });
    await rankRegistration(adminApi, reg.id, [
      { role: ROLE("tank"), rank: 3100 },
      { role: ROLE("support"), rank: 2600 },
    ]);

    type Autofill = { total_registrations: number; applied_registrations: number; players: { registration_id: number; status: string }[] };
    const preview = await adminApi.post<Autofill>(`${adminRegs(t.id)}/rank-autofill/preview`, {});
    expect(preview.total_registrations).toBe(1);
    expect(preview.players.map((p) => p.registration_id)).toEqual([reg.id]);
    const applied = await adminApi.post<Autofill>(`${adminRegs(t.id)}/rank-autofill/apply`, { overwrite_existing: false });
    expect(applied.applied_registrations, "nothing parsed in this stack, nothing applied").toBe(0);
    const [row] = await adminApi.get<AdminRegistration[]>(adminRegs(t.id));
    expect(row.roles.map((r) => [r.role.role, r.rank_value])).toEqual([
      ["tank", 3100],
      ["support", 2600],
    ]);

    const history = `/api/v1/admin/balancer/users/${reg.user_id}/registration-rank-history`;
    const entries = await adminApi.get<{ entries: { tournament_id: number; role: { role: string }; rank_value: number }[] }>(history, {
      workspace_id: ws.id,
      discipline: "overwatch",
    });
    expect(entries.entries.map((e) => [e.tournament_id, e.role.role, e.rank_value])).toEqual([
      [t.id, "tank", 3100],
      [t.id, "support", 2600],
    ]);
    expect((await adminApi.raw("GET", history, { query: { workspace_id: ws.id } })).status(), "the game is never implied").toBe(422);
  });
});

test.describe("check-in", () => {
  test("self check-in needs approval, CHECK_IN status and an open window; afterwards edits and withdrawal lock", async ({ adminApi, makeUser }) => {
    const { t, version, registrationNodeId } = await openTournament(adminApi, {
      schedule: [
        { phase: "open", starts_at: at(-HOUR), ends_at: at(24 * HOUR) },
        { phase: "check_in", starts_at: at(2 * HOUR), ends_at: at(36 * HOUR) },
      ],
    });
    const player = await makeUser("ci");
    const reg = await registerSelf(player, t.id, registrationNodeId, version, { roles: ["tank"] });
    const checkIn = () => player.api.raw("POST", `${pub(t.id)}/me/check-in`);

    expect((await checkIn()).status(), "pending registration").toBe(409);
    await adminApi.patch(`${adminReg(reg.id)}/approve`);
    expect((await checkIn()).status(), "the intake is still open, not in check-in").toBe(409);
    await transitionNode(adminApi, registrationNodeId, "check_in");
    expect((await checkIn()).status(), "CHECK_IN window has not opened yet").toBe(409);

    await adminApi.put(`/api/v1/admin/flow-nodes/${registrationNodeId}/schedule`, {
      schedule: [
        { phase: "open", starts_at: at(-2 * HOUR), ends_at: at(24 * HOUR) },
        { phase: "check_in", starts_at: at(-HOUR), ends_at: at(36 * HOUR) },
      ],
    });
    const res = await checkIn();
    expect(res.status(), await res.text()).toBe(200);
    const checked = (await res.json()) as MyRegistration;
    expect(checked).toMatchObject({ checked_in: true, can_edit: false, edit_locked_reason: "checked_in" });
    expect((await player.api.raw("DELETE", `${pub(t.id)}/me`)).status(), "self-withdrawal after check-in").toBe(409);

    expect((await player.api.raw("POST", `${pub(t.id)}/me/recheck`)).status()).toBe(204);
    expect((await player.api.raw("POST", `${pub(t.id)}/me/recheck`)).status(), "recheck is behind a cooldown").toBe(429);
  });
});

test.describe("subscription gate (Boosty challenge code)", () => {
  test("workspace requirement + code provider: sign-up allowed, check-in refused until a valid code is redeemed", async ({ adminApi, makeUser }) => {
    const { ws, t, version, registrationNodeId } = await openTournament(adminApi, { form: OW_FORM });
    const code = uniq("PATRON");
    const requirement = await adminApi.put<{ requirement: Record<string, unknown> }>(`/api/v1/admin/ws/${ws.id}/subscription-requirement`, {
      requirement: { mode: "any", requirements: [{ provider: "boosty", min_tier_rank: 1 }] },
    });
    expect(requirement.requirement).toMatchObject({ mode: "any" });
    const badRule = await adminApi.raw("PUT", `/api/v1/admin/ws/${ws.id}/subscription-requirement`, {
      body: { requirement: { mode: "sometimes", requirements: [{ provider: "boosty" }] } },
    });
    expect(badRule.status(), "an unknown requirement mode is refused on save").toBe(422);
    await adminApi.put(`/api/v1/admin/ws/${ws.id}/subscription-providers`, {
      provider: "boosty",
      enabled: true,
      verification_method: "code",
      codes: [{ code, tier_rank: 1, tier_label: "Base" }],
    });
    const providers = await adminApi.get<{ configs: { provider: string; enabled: boolean; codes: Record<string, unknown>[] }[] }>(
      `/api/v1/admin/ws/${ws.id}/subscription-providers`
    );
    const boosty = providers.configs.find((c) => c.provider === "boosty");
    expect(boosty?.enabled).toBe(true);
    expect(JSON.stringify(boosty), "the stored code is never echoed back").not.toContain(code);

    const form = await adminApi.get<PublicForm>(adminForm(t.id));
    await adminApi.put(adminForm(t.id), { form_schema: form.form_schema, require_subscription: true, subscription_stage: "check_in" });

    const [payer, freeloader] = [await makeUser("sub"), await makeUser("sub")];
    const regs = [await registerSelf(payer, t.id, registrationNodeId, version, { roles: ["tank"] }), await registerSelf(freeloader, t.id, registrationNodeId, version, { roles: ["damage"] })];
    type SubStatus = { required: boolean; outcome: string; blocks_registration: boolean; verdicts: Record<string, { state: string; code_accepted: boolean }> };
    const before = await payer.api.get<SubStatus>(`/api/v1/tournaments/${t.id}/subscription/me`);
    expect(before).toMatchObject({ required: true, outcome: "refused", blocks_registration: false });
    expect(before.verdicts.boosty.code_accepted).toBe(true);

    const wrong = await payer.api.raw("POST", `/api/v1/tournaments/${t.id}/subscription/redeem-code`, { body: { code: "WRONG-CODE" } });
    expect(wrong.status()).toBe(400);
    const redeemed = await payer.api.post<SubStatus>(`/api/v1/tournaments/${t.id}/subscription/redeem-code`, { code });
    expect(redeemed.outcome).toBe("satisfied");
    expect(redeemed.verdicts.boosty.state).toBe("active");

    await adminApi.post(`${adminRegs(t.id)}/bulk-approve`, { registration_ids: regs.map((r) => r.id) });
    await transitionNode(adminApi, registrationNodeId, "check_in");
    const refused = await freeloader.api.raw("POST", `${pub(t.id)}/me/check-in`);
    expect(refused.status(), "check-in without the subscription").toBe(400);
    expect(JSON.stringify(await refused.json())).toContain("no_code_redeemed");
    expect((await payer.api.post<MyRegistration>(`${pub(t.id)}/me/check-in`)).checked_in).toBe(true);
  });
});
