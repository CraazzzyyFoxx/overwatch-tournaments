/** Staff-only notes on a registration or a registration team (`rpc.tournament.regnote_*`). */

export type RegistrationNoteAttachment = {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
};

export type RegistrationNote = {
  id: number;
  registration_id: number | null;
  registration_team_id: number | null;
  author_id: number | null;
  /** `null` once the author's account is gone. */
  author_username: string | null;
  /** Markdown. */
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: RegistrationNoteAttachment[];
};

/** Exactly one of the two: whose notes. */
export type RegistrationNoteTarget = { registrationId: number } | { teamId: number };

/** Notes per target across one tournament; targets without notes are absent. JSON keys are the ids as strings. */
export type RegistrationNoteCounts = {
  registrations: Record<string, number>;
  teams: Record<string, number>;
};
