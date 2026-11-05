import type { Api } from "./api";
import { battleTag, openRegistration, type FormField, type FormSchema, type Registration, type FlowNodeScheduleEntry } from "./flows";
import { createTournament, createWorkspace, uniq, type Tournament, type Workspace } from "./seed";
import type { TestUser } from "./users";

/**
 * Registration-surface builders (individual sign-up + captain teams). Lifecycle
 * builders (`openRegistration`, `registerSelf`, `battleTag`) come from flows.ts;
 * this file only adds what the registration specs need on top.
 */

export const HOUR = 3_600_000;
export const at = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();

export const ROLE = (role: string) => ({ dimension: "player_role", role });

/** flows' FormSchema plus `visibility`, which an organizers-only question needs. */
export type RegFormSchema = { sections: { key: string; fields: (FormField & { visibility?: "public" | "organizers" })[] }[] };

/** BattleTag + roles + a per-role rank block + an editable select + an organizers-only note. */
export const FULL_FORM: RegFormSchema = {
  sections: [
    { key: "accounts", fields: [{ key: "identity_battlenet", kind: "builtin", required: true }, { key: "identity_discord", kind: "builtin" }] },
    {
      key: "play",
      fields: [
        { key: "roles", kind: "builtin", required: true },
        { key: "current_rank", kind: "role_ranks", label: "Current rank", required: true },
      ],
    },
    {
      key: "details",
      fields: [
        { key: "public_notes", kind: "builtin", editable: true },
        { key: "tshirt", kind: "select", label: "T-shirt", options: ["S", "M", "L"], editable: true },
        { key: "staff_note", kind: "text", label: "Staff note", visibility: "organizers" },
      ],
    },
  ],
};

/** The minimal team-registration form: BattleTag + roles. */
export const TEAM_FORM: FormSchema = {
  sections: [{ key: "main", fields: [{ key: "identity_battlenet", kind: "builtin", required: true }, { key: "roles", kind: "builtin" }] }],
};

export type PublicForm = {
  id: number;
  version_id: number;
  version_number: number;
  is_open: boolean;
  registration_late: boolean;
  hide_registrations: boolean;
  stale_registrations: number | null;
  form_schema: FormSchema;
};

export type MyRegistration = Registration & {
  form_version_id: number | null;
  form_version_stale: boolean;
  submitted_late: boolean;
  queue_position: number | null;
  can_edit: boolean;
  edit_locked_reason: string | null;
  edit_writable_keys: string[];
  team: { id: number; name: string; status: string; is_captain: boolean } | null;
};

export type AdminRegistration = Registration & {
  source: string;
  exclude_reason: string | null;
  checked_in_by_username: string | null;
  deleted_at: string | null;
  reviewed_by_username: string | null;
  submitted_late: boolean;
  balancer_status_meta: { value: string; name: string; excludes_from_balancer: boolean };
};

export type ReadyTournament = { ws: Workspace; t: Tournament; version: number; registrationNodeId: number };

/** A fresh workspace + tournament with registration open now (form saved, the registration node `open`). */
export async function openTournament(
  api: Api,
  opts: { form?: FormSchema; teamFormation?: string; schedule?: FlowNodeScheduleEntry[]; formExtra?: Record<string, unknown> } = {}
): Promise<ReadyTournament> {
  const ws = await createWorkspace(api);
  const t = await createTournament(api, ws.id, opts.teamFormation ? { team_formation: opts.teamFormation } : {});
  const { versionId: version, registrationNodeId } = await openRegistration(api, t.id, { form: opts.form, schedule: opts.schedule });
  if (opts.formExtra) {
    const form = await api.get<PublicForm>(`/api/v1/admin/balancer/tournaments/${t.id}/registration-form`);
    await api.put(`/api/v1/admin/balancer/tournaments/${t.id}/registration-form`, { form_schema: form.form_schema, ...opts.formExtra });
  }
  return { ws, t, version, registrationNodeId };
}

/** Answers for TEAM_FORM / OW_FORM: the user's own BattleTag, `role` primary. */
export function teamAnswers(user: Pick<TestUser, "username">, role: string) {
  return { identity_battlenet: [battleTag(user.username)], roles: [{ role, is_primary: true }] };
}

export type TeamMember = {
  registration_id: number;
  primary_handle: string | null;
  slot_code: string | null;
  is_substitute: boolean;
  is_captain: boolean;
  is_manager: boolean;
  checked_in: boolean;
  status: string;
};
export type TeamInvite = { id: number; slot_code: string; state: string; is_link: boolean; target_handle: string | null; expires_at: string | null };
export type RegTeam = {
  id: number;
  tournament_id: number;
  name: string;
  status: string;
  captain_registration_id: number | null;
  members: TeamMember[];
  invites: TeamInvite[];
  open_slots: Record<string, number>;
  is_complete: boolean;
  admission: string;
  rejection_reason: string | null;
  organizer_notes: string | null;
  roster_locked_at: string | null;
  checked_in_count: number;
  check_in_total: number;
};
export type CreatedInvite = TeamInvite & { token: string | null };

/** `captain` founds a team in `slot` (their registration rides along). */
export async function createTeam(captain: TestUser, tournamentId: number, version: number, slot = "tank", name = uniq("Squad")) {
  return captain.api.post<RegTeam>(
    `/api/v1/tournaments/${tournamentId}/registration-teams`,
    { name, slot_code: slot, registration: { form_version_id: version, answers: teamAnswers(captain, slot) } },
    201
  );
}

/** A link invite for `slot`, redeemed by `user` with a fresh registration. */
export async function joinByLink(captain: TestUser, user: TestUser, team: Pick<RegTeam, "id">, version: number, slot: string) {
  const invite = await captain.api.post<CreatedInvite>(`/api/v1/registration-teams/${team.id}/invites`, { slot_code: slot }, 201);
  return user.api.post<RegTeam>(
    "/api/v1/registration-teams/invites/accept",
    { token: invite.token, registration: { form_version_id: version, answers: teamAnswers(user, slot) } },
    201
  );
}

export function member(team: RegTeam, registrationId: number) {
  return team.members.find((m) => m.registration_id === registrationId);
}
