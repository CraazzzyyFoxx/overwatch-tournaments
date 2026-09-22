/**
 * The questionnaire a form starts from, mirroring
 * `backend/shared/domain/forms/schema.py::default_schema`.
 *
 * Both sides need it for the same reason: `PUT registration-form` takes a
 * REQUIRED `form_schema`, so the first save of a tournament that has no form
 * yet — which may come from an admission toggle, not from the builder — has to
 * send something. Sending anything other than the server's own default would
 * make "who created the row first" decide what the questionnaire asks.
 *
 * Sections are deliberately untitled, exactly as the server builds them: a
 * title is organizer copy, and inventing English ones here would diverge from a
 * form created server-side.
 */

import { identityKey } from "./builtin-keys";
import type { FormField, FormSchema } from "@/types/forms.types";

function builtin(key: string, required = false): FormField {
  return {
    key,
    kind: "builtin",
    required,
    visibility: "public",
    params: {},
    // The server's own default: a question is frozen at submit until an
    // organizer opens it for self-editing.
    editable: false,
  };
}

export function defaultFormSchema(): FormSchema {
  return {
    schema_version: 1,
    sections: [
      {
        key: "accounts",
        fields: [
          builtin("battle_tag", true),
          builtin("smurf_tags"),
          builtin(identityKey("discord")),
          builtin(identityKey("twitch")),
        ],
      },
      { key: "roles", fields: [builtin("roles")] },
      { key: "details", fields: [builtin("public_notes")] },
    ],
  };
}
