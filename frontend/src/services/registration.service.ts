import { apiFetch } from "@/lib/api-fetch";
import type {
  Registration,
  RegistrationCreateInput,
  RegistrationForm,
  RegistrationUpdateInput,
} from "@/types/registration.types";

const registrationService = {
  async getForm(tournamentId: number): Promise<RegistrationForm | null> {
    const response = await apiFetch(
      "tournament",
      `tournaments/${tournamentId}/registration/form`,
    );
    return response.json();
  },

  async register(
    tournamentId: number,
    input: RegistrationCreateInput,
  ): Promise<Registration> {
    const response = await apiFetch(
      "tournament",
      `tournaments/${tournamentId}/registration`,
      { method: "POST", body: input },
    );
    return response.json();
  },

  async getMyRegistration(tournamentId: number): Promise<Registration | null> {
    const response = await apiFetch(
      "tournament",
      `tournaments/${tournamentId}/registration/me`,
    );
    return response.json();
  },

  async updateMyRegistration(
    tournamentId: number,
    input: RegistrationUpdateInput,
  ): Promise<Registration> {
    const response = await apiFetch(
      "tournament",
      `tournaments/${tournamentId}/registration/me`,
      { method: "PATCH", body: input },
    );
    return response.json();
  },

  async withdrawMyRegistration(tournamentId: number): Promise<void> {
    await apiFetch(
      "tournament",
      `tournaments/${tournamentId}/registration/me`,
      { method: "DELETE" },
    );
  },

  async checkInMyRegistration(tournamentId: number): Promise<Registration> {
    const response = await apiFetch(
      "tournament",
      `tournaments/${tournamentId}/registration/me/check-in`,
      { method: "POST" },
    );
    return response.json();
  },

  async listRegistrations(tournamentId: number): Promise<Registration[]> {
    const response = await apiFetch(
      "tournament",
      `tournaments/${tournamentId}/registration/list`,
    );
    return response.json();
  },
};

export default registrationService;
