import { defaultFormSchema } from "@/lib/forms/default-schema";
import type {
  AdminRegistrationForm,
  AdminRegistrationFormUpsert
} from "@/types/balancer-admin.types";

/**
 * The saved form as a complete upsert body.
 *
 * `PUT .../registration-form` is a FULL REPLACE: a field the client omits is
 * written back as its default, deliberately (see `RegistrationFormUpsert` in
 * `schemas/registration.py`). One row is now edited from four screens — the
 * questionnaire builder plus the Registration, Admission and Roster shape
 * settings sections — so each of them has to send the other three's fields
 * untouched. This is that baseline: load the form, spread the section's own
 * edits over it, send the result.
 *
 * Values are echoed verbatim rather than re-normalized. `form_schema` in
 * particular travels back exactly as it was read: a policy save must never
 * rewrite questions the screen it came from never displayed. A tournament with
 * no form yet has no schema to echo, so its caller must resolve the owner's
 * identity provider before generating the same default the server would build.
 *
 * `subscription_requirement_json` is absent on purpose: it is a server-derived read-only projection, and the schema
 * drops it on the way in. The intake settings are not on the form at all: they are the registration node's config.
 */
/** The default questionnaire of the owner's game; with the provider unresolved there is no honest default. */
function ownerDefaultSchema(identityProvider: string | undefined) {
  if (!identityProvider) throw new Error("The owner's identity provider is not resolved yet");
  return defaultFormSchema(identityProvider);
}

export function toRegistrationFormUpsert(
  form: AdminRegistrationForm | null | undefined,
  identityProvider?: string
): AdminRegistrationFormUpsert {
  return {
    require_open_profile: form?.require_open_profile ?? false,
    open_profile_scope: form?.open_profile_scope ?? "main",
    show_ranks: form?.show_ranks ?? false,
    hide_registrations: form?.hide_registrations ?? false,
    form_schema: form?.form_schema ?? ownerDefaultSchema(identityProvider)
  };
}
