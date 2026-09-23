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
 * no form yet has no schema to echo, so it gets the same default the server
 * would have built.
 *
 * `is_open` and `subscription_requirement_json` are absent on purpose: both are
 * server-derived read-only projections, and the schema drops them on the way in.
 */
export function toRegistrationFormUpsert(
  form: AdminRegistrationForm | null | undefined
): AdminRegistrationFormUpsert {
  return {
    auto_approve: form?.auto_approve ?? false,
    require_open_profile: form?.require_open_profile ?? false,
    open_profile_scope: form?.open_profile_scope ?? "main",
    show_ranks: form?.show_ranks ?? false,
    hide_registrations: form?.hide_registrations ?? false,
    max_participants: form?.max_participants ?? null,
    max_substitutes: form?.max_substitutes ?? 0,
    subscription_scope: form?.subscription_scope === "team" ? "team" : "player",
    team_rank_min: form?.team_rank_min ?? null,
    team_rank_max: form?.team_rank_max ?? null,
    team_max_rank_spread: form?.team_max_rank_spread ?? null,
    team_unique_identity: form?.team_unique_identity ?? false,
    team_require_discord_guild: form?.team_require_discord_guild ?? false,
    require_subscription: form?.require_subscription ?? false,
    // The looser stage for a form saved before the field existed, so loading an
    // old form never silently arms a sign-up wall.
    subscription_stage: form?.subscription_stage === "registration" ? "registration" : "check_in",
    form_schema: form?.form_schema ?? defaultFormSchema()
  };
}
