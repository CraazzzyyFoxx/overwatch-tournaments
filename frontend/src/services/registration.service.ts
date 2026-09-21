import { apiFetch } from "@/lib/api-fetch";
import { rehydrateRegistrationList } from "@/services/registration.helpers";
import type {
  Registration,
  RegistrationForm,
  RegistrationListResponse,
  RegistrationSubmitInput,
  SubscriptionStatus,
} from "@/types/registration.types";

const registrationService = {
  async getForm(tournamentId: number): Promise<RegistrationForm | null> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/registration/form`,
    );
    return response.json();
  },

  /** The whole answer document, against the version it was written for. A
   *  schema change since then comes back as a 409 `form_version_stale`. */
  async register(tournamentId: number, input: RegistrationSubmitInput): Promise<Registration> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/registration`,
      { method: "POST", body: input },
    );
    return response.json();
  },

  async getMyRegistration(tournamentId: number): Promise<Registration | null> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/registration/me`,
    );
    return response.json();
  },

  async updateMyRegistration(
    tournamentId: number,
    input: RegistrationSubmitInput,
  ): Promise<Registration> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/registration/me`,
      { method: "PATCH", body: input },
    );
    return response.json();
  },

  async withdrawMyRegistration(tournamentId: number): Promise<void> {
    await apiFetch(`/api/v1/tournaments/${tournamentId}/registration/me`,
      { method: "DELETE" },
    );
  },

  async checkInMyRegistration(tournamentId: number): Promise<Registration> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/registration/me/check-in`,
      { method: "POST" },
    );
    return response.json();
  },

  /** The caller's own subscription standing. Never forces a provider refresh, so
   *  the registration form can poll it on render. */
  async getMySubscriptionStatus(tournamentId: number): Promise<SubscriptionStatus> {
    const response = await apiFetch(
      `/api/v1/tournaments/${tournamentId}/subscription/me`,
    );
    return response.json();
  },

  /** Redeem a code published in a subscriber-only post. Returns the refreshed
   *  status so the caller does not need a second round-trip. */
  async redeemSubscriptionCode(
    tournamentId: number,
    code: string,
    provider = "boosty",
  ): Promise<SubscriptionStatus> {
    const response = await apiFetch(
      `/api/v1/tournaments/${tournamentId}/subscription/redeem-code`,
      { method: "POST", body: { code, provider } },
    );
    return response.json();
  },

  /** The whole envelope, not just the rows: `hidden`, `total`, `role_counts` and
   *  `max_participants` travel with it, and under `hidden` they ARE the payload —
   *  the server sends no rows at all. */
  async listRegistrations(tournamentId: number): Promise<RegistrationListResponse> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/registration/list`,
    );
    const data: RegistrationListResponse = await response.json();
    return { ...data, registrations: rehydrateRegistrationList(data) };
  },
};

export default registrationService;
