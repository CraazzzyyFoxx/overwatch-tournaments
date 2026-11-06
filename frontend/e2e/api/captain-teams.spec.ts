import type { Api } from "../support/api";
import { expect, test } from "../support/fixtures";
import { registerSelf } from "../support/flows";
import {
  TEAM_FORM,
  createTeam,
  joinByLink,
  member,
  openTournament,
  teamAnswers,
  type CreatedInvite,
  type MyRegistration,
  type RegTeam,
} from "../support/registration";
import { transitionNode } from "../support/seed";

// Team registration (team_formation = "registration"): a captain founds a team
// with their own sign-up, fills the 5v5 role-queue roster by invites, and the
// organizer moderates it. Every slot decision runs in the `registration` schema.

const teamsOf = (tid: number) => `/api/v1/tournaments/${tid}/registration-teams`;
const adminTeams = (tid: number) => `/api/v1/admin/balancer/tournaments/${tid}/registration-teams`;
const regTeam = (teamId: number) => `/api/v1/registration-teams/${teamId}`;

async function teamTournament(adminApi: Api, formExtra?: Record<string, unknown>) {
  return openTournament(adminApi, { form: TEAM_FORM, teamFormation: "registration", formExtra });
}

test("captain founds a team; name rules; a free agent is invited, sees the offer and accepts", async ({ adminApi, anonApi, makeUser }) => {
  const { t, version, registrationNodeId } = await teamTournament(adminApi);
  const captain = await makeUser("cap");
  const team = await createTeam(captain, t.id, version, "tank");
  expect(team.status).toBe("forming");
  expect(team.members).toEqual([expect.objectContaining({ slot_code: "tank", is_captain: true, status: "pending" })]);
  expect(team.open_slots).toEqual({ damage: 2, support: 2 });
  expect(team.is_complete).toBe(false);

  const rival = await makeUser("cap");
  const taken = await rival.api.raw("POST", teamsOf(t.id), {
    body: { name: team.name.toUpperCase(), slot_code: "tank", registration: { form_version_id: version, answers: teamAnswers(rival, "tank") } },
  });
  expect(taken.status(), "team names are unique per tournament, case-insensitively").toBe(409);
  const hashed = await rival.api.raw("POST", teamsOf(t.id), {
    body: { name: "Bad#Name", slot_code: "tank", registration: { form_version_id: version, answers: teamAnswers(rival, "tank") } },
  });
  expect(hashed.status(), "a team name cannot contain #").toBe(400);
  const badSlot = await rival.api.raw("POST", teamsOf(t.id), {
    body: { name: "Slotless", slot_code: "coach", registration: { form_version_id: version, answers: teamAnswers(rival, "tank") } },
  });
  expect(badSlot.status(), "the captain's slot must exist in the roster shape").toBeGreaterThanOrEqual(400);
  expect(badSlot.status()).toBeLessThan(500);

  const agent = await makeUser("fa");
  const agentReg = await registerSelf(agent, t.id, registrationNodeId, version, { roles: ["damage"] });
  const free = await captain.api.get<{ items: { registration_id: number; primary_handle: string }[] }>(`${teamsOf(t.id)}/free-agents`);
  expect(free.items.map((f) => f.registration_id)).toEqual([agentReg.id]);
  expect((await anonApi.raw("GET", `${teamsOf(t.id)}/free-agents`)).status()).toBe(401);

  const invite = await captain.api.post<CreatedInvite>(`${regTeam(team.id)}/invites`, { slot_code: "damage", target_registration_id: agentReg.id }, 201);
  expect(invite).toMatchObject({ is_link: false, token: null, state: "pending" });
  const offers = await agent.api.get<{ items: { invite_id: number; team_name: string; slot_code: string }[] }>(`${teamsOf(t.id)}/my-invites`);
  expect(offers.items).toEqual([expect.objectContaining({ invite_id: invite.id, team_name: team.name, slot_code: "damage" })]);
  const stranger = await makeUser("str");
  expect((await stranger.api.raw("POST", "/api/v1/registration-teams/invites/accept", { body: { invite_id: invite.id } })).status(), "a targeted invite belongs to its addressee").toBeGreaterThanOrEqual(400);

  const publicView = await anonApi.get<{ items: RegTeam[]; unassigned_players: number }>(teamsOf(t.id));
  expect(publicView.unassigned_players).toBe(1);
  expect(publicView.items.find((x) => x.id === team.id)?.invites, "the public roster never lists invites").toEqual([]);
  const captainView = await captain.api.get<{ items: RegTeam[] }>(teamsOf(t.id));
  expect(captainView.items.find((x) => x.id === team.id)?.invites.map((i) => [i.id, i.target_handle])).toEqual([[invite.id, agentReg.primary_handle]]);

  const joined = await agent.api.post<RegTeam>("/api/v1/registration-teams/invites/accept", { invite_id: invite.id }, 201);
  expect(member(joined, agentReg.id)).toMatchObject({ slot_code: "damage", is_captain: false });
  expect(joined.open_slots).toEqual({ damage: 1, support: 2 });
  expect((await captain.api.get<{ items: unknown[] }>(`${teamsOf(t.id)}/free-agents`)).items).toEqual([]);
  const card = await agent.api.get<MyRegistration>(`/api/v1/tournaments/${t.id}/registration/me`);
  expect(card.team).toMatchObject({ id: team.id, is_captain: false });
});

test("link invite: anonymous preview, accept needs the form answered, a used link is no longer redeemable", async ({ adminApi, anonApi, makeUser }) => {
  const { t, version } = await teamTournament(adminApi);
  const captain = await makeUser("cap");
  const team = await createTeam(captain, t.id, version, "tank");
  const link = await captain.api.post<CreatedInvite>(`${regTeam(team.id)}/invites`, { slot_code: "support" }, 201);
  expect(link.is_link).toBe(true);
  expect(link.token, "the raw token is returned once, at creation").toBeTruthy();

  type Preview = { tournament_id: number; team_id: number; team_name: string; slot_code: string; state: string; is_redeemable: boolean };
  const preview = await anonApi.post<Preview>("/api/v1/registration-teams/invites/preview", { token: link.token });
  expect(preview).toMatchObject({ tournament_id: t.id, team_id: team.id, team_name: team.name, slot_code: "support", is_redeemable: true });
  expect((await anonApi.raw("POST", "/api/v1/registration-teams/invites/preview", { body: { token: "nope" } })).status()).toBe(404);
  expect((await anonApi.raw("POST", "/api/v1/registration-teams/invites/accept", { body: { token: link.token } })).status()).toBe(401);

  const newcomer = await makeUser("new");
  const bare = await newcomer.api.raw("POST", "/api/v1/registration-teams/invites/accept", { body: { token: link.token } });
  expect(bare.status(), "a newcomer must answer the registration form").toBe(422);
  const joined = await newcomer.api.post<RegTeam>(
    "/api/v1/registration-teams/invites/accept",
    { token: link.token, registration: { form_version_id: version, answers: teamAnswers(newcomer, "support") } },
    201
  );
  expect(joined.members.map((m) => m.slot_code).sort()).toEqual(["support", "tank"]);

  const used = await anonApi.post<Preview>("/api/v1/registration-teams/invites/preview", { token: link.token });
  expect(used.is_redeemable, "a consumed link previews as not redeemable").toBe(false);
  const reuse = await makeUser("new");
  const again = await reuse.api.raw("POST", "/api/v1/registration-teams/invites/accept", {
    body: { token: link.token, registration: { form_version_id: version, answers: teamAnswers(reuse, "support") } },
  });
  expect(again.status()).toBe(409);
});

test("invite lifecycle: extend, decline, revoke, captain + organizer history, cap reset, organizer revoke", async ({ adminApi, makeUser }) => {
  const { t, version, registrationNodeId } = await teamTournament(adminApi);
  const captain = await makeUser("cap");
  const team = await createTeam(captain, t.id, version, "tank");
  const agent = await makeUser("fa");
  const agentReg = await registerSelf(agent, t.id, registrationNodeId, version, { roles: ["support"] });

  const offer = await captain.api.post<CreatedInvite>(`${regTeam(team.id)}/invites`, { slot_code: "support", target_registration_id: agentReg.id, ttl_days: 2 }, 201);
  const extended = await captain.api.post<CreatedInvite>(`${regTeam(team.id)}/invites/${offer.id}/extend`, { ttl_days: 14 });
  expect(Date.parse(extended.expires_at!), "extend pushes the expiry out").toBeGreaterThan(Date.parse(offer.expires_at!));
  await agent.api.post("/api/v1/registration-teams/invites/decline", { invite_id: offer.id }, 204);
  const late = await agent.api.raw("POST", "/api/v1/registration-teams/invites/accept", { body: { invite_id: offer.id } });
  expect(late.status(), "a declined invite cannot be accepted").toBe(409);

  const link = await captain.api.post<CreatedInvite>(`${regTeam(team.id)}/invites`, { slot_code: "damage" }, 201);
  await captain.api.delete(`/api/v1/registration-teams/invites/${link.id}`, 204);
  const organizerLink = await captain.api.post<CreatedInvite>(`${regTeam(team.id)}/invites`, { slot_code: "damage" }, 201);
  await adminApi.delete(`${adminTeams(t.id)}/invites/${organizerLink.id}`, 204);

  type History = {
    items: { id: number; state?: string; is_link: boolean; target_handle: string | null; revoked_by_organizer: boolean }[];
    cap_used: number;
    cap_limit: number;
    cap_reset_at: string | null;
  };
  const mine = await captain.api.get<History>(`${regTeam(team.id)}/invite-history`);
  expect(mine.items.map((i) => i.id).sort()).toEqual([offer.id, link.id, organizerLink.id].sort());
  expect(mine.items.find((i) => i.id === offer.id)?.target_handle).toBe(agentReg.primary_handle);
  expect(mine.items.find((i) => i.id === organizerLink.id)?.revoked_by_organizer).toBe(true);
  expect(mine.cap_used).toBe(3);
  expect((await agent.api.raw("GET", `${regTeam(team.id)}/invite-history`)).status(), "only team staff read the history").toBe(403);
  // The history is what explains a finished offer; without its state a declined
  // and a revoked row read the same.
  expect(Object.fromEntries(mine.items.map((i) => [i.id, i.state])), "invite history carries each invite's state").toEqual({
    [offer.id]: "declined",
    [link.id]: "revoked",
    [organizerLink.id]: "revoked",
  });

  await adminApi.post(`${adminTeams(t.id)}/${team.id}/invite-cap/reset`, undefined, 204);
  const organizer = await adminApi.get<History>(`${adminTeams(t.id)}/${team.id}/invite-history`);
  expect(organizer.cap_used, "the organizer forgave the count").toBe(0);
  expect(organizer.cap_reset_at).toBeTruthy();
  expect(organizer.items).toHaveLength(3);
});

test("roster management: place, manager, transfer captaincy, kick, leave; only the captain edits", async ({ adminApi, makeUser }) => {
  const { t, version } = await teamTournament(adminApi, { max_substitutes: 1 });
  const [captain, b, c] = [await makeUser("cap"), await makeUser("mb"), await makeUser("mb")];
  let team = await createTeam(captain, t.id, version, "tank");
  const captainId = team.captain_registration_id!;
  team = await joinByLink(captain, b, team, version, "damage");
  team = await joinByLink(captain, c, team, version, "support");
  const bId = team.members.find((m) => m.slot_code === "damage")!.registration_id;
  const cId = team.members.find((m) => m.slot_code === "support")!.registration_id;

  const forbidden = await b.api.raw("POST", `${regTeam(team.id)}/members/${cId}/manager`, { body: { is_manager: true } });
  expect(forbidden.status(), "a member cannot manage the roster").toBe(403);

  team = await captain.api.post<RegTeam>(`${regTeam(team.id)}/members/${cId}/place`, { slot_code: "support", is_substitute: true });
  expect(member(team, cId)).toMatchObject({ slot_code: "support", is_substitute: true });
  team = await captain.api.post<RegTeam>(`${regTeam(team.id)}/members/${cId}/place`, { slot_code: "damage" });
  expect(member(team, cId)).toMatchObject({ slot_code: "damage", is_substitute: false });
  team = await captain.api.post<RegTeam>(`${regTeam(team.id)}/members/${bId}/manager`, { is_manager: true });
  expect(member(team, bId)?.is_manager).toBe(true);
  const renamed = await captain.api.patch<RegTeam>(regTeam(team.id), { name: `${team.name} Prime` });
  expect(renamed.name).toBe(`${team.name} Prime`);

  await captain.api.post(`${regTeam(team.id)}/captain/${bId}`, undefined, 204);
  expect((await captain.api.raw("DELETE", `${regTeam(team.id)}/members/${cId}`)).status(), "the former captain lost the roster").toBe(403);
  await b.api.delete(`${regTeam(team.id)}/members/${cId}`, 204);
  await captain.api.delete(`${regTeam(team.id)}/members/me`, 204);

  const roster = (await b.api.get<{ items: RegTeam[] }>(teamsOf(t.id))).items.find((x) => x.id === team.id)!;
  expect(roster.captain_registration_id).toBe(bId);
  expect(roster.members.map((m) => m.registration_id)).toEqual([bId]);
  // Kick and leave withdraw the registration (withdrawal is final) and detach it.
  for (const [user, id] of [
    [c, cId],
    [captain, captainId],
  ] as const) {
    const card = await user.api.get<MyRegistration>(`/api/v1/tournaments/${t.id}/registration/me`);
    expect([card.id, card.status, card.team], "a kicked / departed member is withdrawn and off the team").toEqual([id, "withdrawn", null]);
  }
  expect((await b.api.get<{ items: unknown[] }>(`${teamsOf(t.id)}/free-agents`)).items).toEqual([]);
});

test("complete roster locks; organizer unlocks; team check-in needs CHECK_IN and approved members", async ({ adminApi, makeUser }) => {
  const { t, version, registrationNodeId } = await teamTournament(adminApi);
  const captain = await makeUser("cap");
  let team = await createTeam(captain, t.id, version, "tank");
  const early = await captain.api.raw("POST", `${regTeam(team.id)}/lock`);
  expect(early.status(), "an incomplete roster cannot lock").toBe(409);
  for (const slot of ["damage", "damage", "support", "support"]) team = await joinByLink(captain, await makeUser("mb"), team, version, slot);
  expect(team).toMatchObject({ is_complete: true, status: "complete", open_slots: {} });

  const locked = await captain.api.post<RegTeam>(`${regTeam(team.id)}/lock`);
  expect(locked.roster_locked_at).toBeTruthy();
  const unlocked = await adminApi.post<RegTeam>(`${adminTeams(t.id)}/${team.id}/unlock`);
  expect(unlocked.roster_locked_at).toBeNull();

  const ids = team.members.map((m) => m.registration_id);
  await transitionNode(adminApi, registrationNodeId, "check_in");
  const unapproved = await captain.api.raw("POST", `${regTeam(team.id)}/check-in`, { body: {} });
  expect(unapproved.status(), "every member must be approved first").toBe(409);
  await adminApi.post(`/api/v1/admin/balancer/tournaments/${t.id}/registrations/bulk-approve`, { registration_ids: ids });
  const checked = await captain.api.post<RegTeam>(`${regTeam(team.id)}/check-in`, { exclude_registration_ids: [ids[4]] });
  expect(checked.checked_in_count).toBe(4);
  expect(checked.check_in_total).toBe(5);
  expect(member(checked, ids[4])?.checked_in, "an excluded member is left for later").toBe(false);
});

test("organizer moderation: rename, admission, notes, attach by handle, reject with withdrawal; captain still sees the reason", async ({ adminApi, anonApi, makeUser }) => {
  const { t, version, registrationNodeId } = await teamTournament(adminApi);
  const captain = await makeUser("cap");
  const team = await createTeam(captain, t.id, version, "tank");
  const agent = await makeUser("fa");
  const agentReg = await registerSelf(agent, t.id, registrationNodeId, version, { roles: ["support"] });

  const listed = await adminApi.get<{ items: RegTeam[]; total: number; unassigned_players: number }>(adminTeams(t.id));
  expect(listed.total).toBe(1);
  expect(listed.unassigned_players).toBe(1);

  expect((await adminApi.patch<RegTeam>(`${adminTeams(t.id)}/${team.id}`, { name: "Organizer Named" })).name).toBe("Organizer Named");
  expect((await adminApi.post<RegTeam>(`${adminTeams(t.id)}/${team.id}/admission`, { admission: "waitlisted" })).admission).toBe("waitlisted");
  expect((await adminApi.post<RegTeam>(`${adminTeams(t.id)}/${team.id}/notes`, { notes: "check the roster" })).organizer_notes).toBe("check the roster");
  const publicTeam = (await anonApi.get<{ items: RegTeam[] }>(teamsOf(t.id))).items[0];
  expect(publicTeam.organizer_notes ?? null, "organizer notes are private").toBeNull();

  const attached = await adminApi.post<RegTeam>(`${adminTeams(t.id)}/${team.id}/members/attach`, {
    handle: agentReg.primary_handle,
    slot_code: "support",
  });
  expect(member(attached, agentReg.id)?.slot_code).toBe("support");

  const noReason = await adminApi.raw("POST", `${adminTeams(t.id)}/${team.id}/reject`, { body: { reason: " " } });
  expect(noReason.status(), "a rejection needs a reason").toBe(422);
  const rejected = await adminApi.post<RegTeam>(`${adminTeams(t.id)}/${team.id}/reject`, { reason: "Roster incomplete", withdraw_members: true });
  expect(rejected).toMatchObject({ status: "rejected", rejection_reason: "Roster incomplete" });

  expect((await anonApi.get<{ items: RegTeam[] }>(teamsOf(t.id))).items, "a rejected team leaves the public roster").toEqual([]);
  const own = await captain.api.get<{ items: RegTeam[] }>(teamsOf(t.id));
  expect(own.items.map((x) => [x.id, x.status, x.rejection_reason])).toEqual([[team.id, "rejected", "Roster incomplete"]]);
  const card = await agent.api.get<MyRegistration>(`/api/v1/tournaments/${t.id}/registration/me`);
  expect(card.status, "withdraw_members withdrew the roster").toBe("withdrawn");
});

test("captain disbands a forming team; members are withdrawn and their card explains why", async ({ adminApi, anonApi, makeUser }) => {
  const { t, version } = await teamTournament(adminApi);
  const [captain, mate] = [await makeUser("cap"), await makeUser("mb")];
  let team = await createTeam(captain, t.id, version, "tank");
  team = await joinByLink(captain, mate, team, version, "damage");
  const pending = await captain.api.post<CreatedInvite>(`${regTeam(team.id)}/invites`, { slot_code: "support" }, 201);
  expect((await mate.api.raw("DELETE", regTeam(team.id))).status(), "only the captain disbands").toBe(403);
  await captain.api.delete(regTeam(team.id), 204);
  expect((await anonApi.get<{ items: RegTeam[] }>(teamsOf(t.id))).items).toEqual([]);
  const card = await mate.api.get<MyRegistration>(`/api/v1/tournaments/${t.id}/registration/me`);
  expect(card.status).toBe("withdrawn");
  expect(card.team, "the link survives so the card can say the team ended").toMatchObject({ id: team.id, status: "disbanded" });
  const preview = await anonApi.post<{ is_redeemable: boolean }>("/api/v1/registration-teams/invites/preview", { token: pending.token });
  expect(preview.is_redeemable, "a disbanded team's open link is revoked").toBe(false);
});
