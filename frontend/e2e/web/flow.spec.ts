import { expect, openPage, test } from "../support/fixtures";
import { balanceAndExport, battleTag, openRegistration, rankRegistration, registerSelf, rosterSlots, seedPlayers, startStage, type Registration } from "../support/flows";
import { addItems, adminFlow, applyPreset, nodeNamed, playOut, waitNode } from "../support/flow";
import { createTournament, createWorkspace, transitionNode } from "../support/seed";
import type { TestUser } from "../support/users";

// Spec §17: the three flows organizers build from presets in the Flow tab,
// run through the real API, and read back on the public tabs.

test("league season: 3 days → best 2 → season table", async ({ adminApi, anonApi, makeUser, page }) => {
  test.setTimeout(1_200_000);
  const ws = await createWorkspace(adminApi);
  const t = await createTournament(adminApi, ws.id);
  await applyPreset(page, t.id, "League season (N days, best K)", { days: 3, best: 2 });

  let flow = await adminFlow(adminApi, t.id);
  expect(flow.nodes.filter((n) => n.kind === "registration").map((n) => n.name)).toEqual(["Day 1", "Day 2", "Day 3"]);
  expect(nodeNamed(flow, "aggregate", "Season").config).toMatchObject({ mode: "sum_best_n", n: 2, unit: "players" });

  const slots = await rosterSlots(adminApi, t.id);
  const players: TestUser[] = [];
  for (let i = 0; i < 10; i++) players.push(await makeUser(`lg${i}`));
  for (const day of [1, 2, 3]) {
    const reg = nodeNamed(flow, "registration", `Day ${day}`);
    const formation = nodeNamed(flow, "formation", `Day ${day} teams`);
    const stage = nodeNamed(flow, "stage", `Day ${day}`);
    const { versionId } = await openRegistration(adminApi, t.id, { registrationNodeId: reg.id, autoApprove: true });
    const regs: Registration[] = [];
    for (const [i, user] of players.entries()) {
      const role = slots[i % slots.length]!;
      const r = await registerSelf(user, t.id, reg.id, versionId, { roles: [role.role], handle: battleTag(user.username) });
      if (day === 1) await rankRegistration(adminApi, r.id, [{ role, rank: 2000 + i * 50 }]);
      regs.push(r);
    }
    await adminApi.post(`/api/v1/admin/balancer/tournaments/${t.id}/registrations/bulk-add-to-balancer?registration_node_id=${reg.id}`, {
      registration_ids: regs.map((r) => r.id),
    });
    await transitionNode(adminApi, reg.id, "closed");
    await balanceAndExport(adminApi, t.id, formation.id);
    await addItems(adminApi, stage.stage_id!, 1);
    await startStage(adminApi, { node_id: stage.id });
    await playOut(adminApi, t.id, stage.stage_id!);
    await waitNode(adminApi, t.id, stage.id, "completed");
  }
  flow = await adminFlow(adminApi, t.id);
  await waitNode(adminApi, t.id, nodeNamed(flow, "leaderboard", "Season table").id, "final");

  await openPage(page, `/tournaments/${t.slug}/table`);
  for (const day of ["Day 1", "Day 2", "Day 3"]) await expect(page.getByRole("columnheader", { name: day })).toBeVisible();
  await expect(page.getByText("Only the best 2 results count.")).toBeVisible();
  const rows = page.locator("tbody tr");
  await expect(rows).toHaveCount(10);
  for (let i = 0; i < 10; i++) await expect(rows.nth(i).locator('[data-counted="true"]')).toHaveCount(2);
  expect((await anonApi.get<{ status: string }>(`/api/v1/tournaments/${t.id}`)).status).toBe("completed");
});

test("groups → re-formation → playoff", async ({ adminApi, anonApi, page }) => {
  test.setTimeout(900_000);
  const ws = await createWorkspace(adminApi);
  const t = await createTournament(adminApi, ws.id);
  await applyPreset(page, t.id, "Groups → re-formation → playoff");

  const flow = await adminFlow(adminApi, t.id);
  const reg = flow.nodes.find((n) => n.kind === "registration")!;
  const [first, second] = flow.nodes.filter((n) => n.kind === "formation");
  const groups = nodeNamed(flow, "stage", "Groups");
  const playoff = nodeNamed(flow, "stage", "Playoff");

  await openRegistration(adminApi, t.id, { registrationNodeId: reg.id });
  await seedPlayers(adminApi, t.id, 20, { registrationNodeId: reg.id });
  await transitionNode(adminApi, reg.id, "closed");
  await balanceAndExport(adminApi, t.id, first.id);
  await addItems(adminApi, groups.stage_id!, 2);
  await startStage(adminApi, { node_id: groups.id });
  await playOut(adminApi, t.id, groups.stage_id!);
  await waitNode(adminApi, t.id, groups.id, "completed");

  await balanceAndExport(adminApi, t.id, second.id);
  await addItems(adminApi, playoff.stage_id!, 0, true);
  await startStage(adminApi, { node_id: playoff.id });
  await playOut(adminApi, t.id, playoff.stage_id!);
  await waitNode(adminApi, t.id, playoff.id, "completed");
  expect((await anonApi.get<{ status: string }>(`/api/v1/tournaments/${t.id}`)).status).toBe("completed");

  await openPage(page, `/tournaments/${t.slug}/bracket?stage=${playoff.stage_id}`);
  await expect(page.getByLabel("Branches")).toHaveCount(0);
  await openPage(page, `/tournaments/${t.slug}/format`);
  for (const name of ["Groups", "Top 4", "Playoff teams", "Playoff"]) await expect(page.getByText(name, { exact: true })).toBeVisible();
});

test("individual Swiss → draft → playoff", async ({ adminApi, page }) => {
  test.setTimeout(900_000);
  const ws = await createWorkspace(adminApi);
  const t = await createTournament(adminApi, ws.id);
  await applyPreset(page, t.id, "Individual Swiss → draft → playoff");

  let flow = await adminFlow(adminApi, t.id);
  const reg = flow.nodes.find((n) => n.kind === "registration")!;
  const swiss = nodeNamed(flow, "stage", "Swiss");
  const qualifiers = nodeNamed(flow, "filter", "Qualifiers");
  const formation = flow.nodes.find((n) => n.kind === "formation")!;
  expect(formation.config).toMatchObject({ mode: "draft" });
  expect(flow.edges.some((e) => e.source_node_id === reg.id && e.target_node_id === swiss.id)).toBe(true);
  expect(flow.edges.some((e) => e.source_node_id === qualifiers.id && e.target_node_id === formation.id)).toBe(true);

  // Small run: one round, 2 playoff teams of 5 qualify.
  await adminApi.patch(`/api/v1/admin/stages/${swiss.stage_id}`, { max_rounds: 1, playoff_team_count: 2 });
  await adminApi.put(`/api/v1/admin/tournaments/${t.id}/flow`, {
    nodes: [{ id: qualifiers.id, kind: "filter", name: qualifiers.name, config: { mode: "top", n: 10 } }],
  });

  await openRegistration(adminApi, t.id, { registrationNodeId: reg.id });
  await seedPlayers(adminApi, t.id, 20, { registrationNodeId: reg.id });
  await transitionNode(adminApi, reg.id, "closed");
  await startStage(adminApi, { node_id: swiss.id });
  await playOut(adminApi, t.id, swiss.stage_id!);
  await adminApi.post(`/api/v1/admin/tournaments/${t.id}/stages/${swiss.stage_id}/lock-qualification`);
  await waitNode(adminApi, t.id, swiss.id, "completed");
  await waitNode(adminApi, t.id, qualifiers.id, "final");

  flow = await adminFlow(adminApi, t.id);
  expect(flow.results.filter((r) => r.node_id === qualifiers.id && r.port === "passed")).toHaveLength(10);
  await transitionNode(adminApi, formation.id, "forming");
  await waitNode(adminApi, t.id, formation.id, "forming");

  await openPage(page, `/tournaments/${t.slug}/format`);
  await expect(page.getByLabel(/^Swiss, Stage, Completed$/)).toBeVisible();
  await expect(page.getByLabel(/, Formation, Forming$/)).toBeVisible();
});
