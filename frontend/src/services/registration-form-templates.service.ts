import { apiFetch } from "@/lib/api-fetch";
import type { AdminRegistrationForm } from "@/types/balancer-admin.types";
import type { FormSchema, RegistrationFormTemplate } from "@/types/forms.types";

/**
 * Saved form schemas, shared by every tournament of a workspace.
 *
 * Workspace-scoped, like the subscription providers: an organizer builds the
 * questionnaire once and applies it per tournament. `apply` is an ordinary
 * schema upsert on the tournament's form, so it bumps the form version by the
 * usual rule and comes back as the whole updated form.
 */
const registrationFormTemplatesService = {
  async list(workspaceId: number): Promise<RegistrationFormTemplate[]> {
    const response = await apiFetch(
      `/api/v1/admin/ws/${workspaceId}/registration-form-templates`,
    );
    return response.json();
  },

  async create(
    workspaceId: number,
    name: string,
    formSchema: FormSchema,
  ): Promise<RegistrationFormTemplate> {
    const response = await apiFetch(
      `/api/v1/admin/ws/${workspaceId}/registration-form-templates`,
      { method: "POST", body: { name, form_schema: formSchema } },
    );
    return response.json();
  },

  /** Replaced wholesale — there is no PATCH: a partial merge of a schema would
   *  be a silent edit of questions the organizer did not open. */
  async update(
    workspaceId: number,
    templateId: number,
    name: string,
    formSchema: FormSchema,
  ): Promise<RegistrationFormTemplate> {
    const response = await apiFetch(
      `/api/v1/admin/ws/${workspaceId}/registration-form-templates/${templateId}`,
      { method: "PUT", body: { name, form_schema: formSchema } },
    );
    return response.json();
  },

  async remove(workspaceId: number, templateId: number): Promise<void> {
    await apiFetch(
      `/api/v1/admin/ws/${workspaceId}/registration-form-templates/${templateId}`,
      { method: "DELETE" },
    );
  },

  /** Writes the template's schema onto the tournament's form and returns that
   *  form, so the builder re-renders from the server's answer rather than
   *  guessing the new version number. */
  async apply(tournamentId: number, templateId: number): Promise<AdminRegistrationForm> {
    const response = await apiFetch(
      `/api/v1/admin/balancer/tournaments/${tournamentId}/registration-form/apply-template`,
      { method: "POST", body: { template_id: templateId } },
    );
    return response.json();
  },

  /** Snapshots the tournament's CURRENT schema as a new workspace template. */
  async saveFromForm(tournamentId: number, name: string): Promise<RegistrationFormTemplate> {
    const response = await apiFetch(
      `/api/v1/admin/balancer/tournaments/${tournamentId}/registration-form/save-template`,
      { method: "POST", body: { name } },
    );
    return response.json();
  },
};

export default registrationFormTemplatesService;
