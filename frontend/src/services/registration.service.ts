import { apiFetch } from "@/lib/api-fetch";
import { rehydrateRegistrationList } from "@/services/registration.helpers";
import type {
  Registration,
  RegistrationCreateInput,
  RegistrationForm,
  RegistrationListResponse,
  RegistrationUpdateInput,
} from "@/types/registration.types";

const registrationService = {
  async getForm(tournamentId: number): Promise<RegistrationForm | null> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/registration/form`,
    );
    return response.json();
  },

  async register(
    tournamentId: number,
    input: RegistrationCreateInput,
  ): Promise<Registration> {
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
    input: RegistrationUpdateInput,
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

  async listRegistrations(tournamentId: number): Promise<Registration[]> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/registration/list`,
    );
    const data: RegistrationListResponse = await response.json();
    return rehydrateRegistrationList(data);
  },
};

export default registrationService;
