import { apiFetch } from "@/lib/api/fetch";
import type {
  RegistrationNote,
  RegistrationNoteCounts,
  RegistrationNoteTarget
} from "@/types/registration-note.types";

const base = (tournamentId: number) => `/api/v1/admin/balancer/tournaments/${tournamentId}/registration-notes`;

function targetFields(target: RegistrationNoteTarget) {
  return "registrationId" in target
    ? { registration_id: target.registrationId }
    : { registration_team_id: target.teamId };
}

/** Server-side caps, mirrored so a bad pick fails before the upload starts. */
export const NOTE_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024;
export const NOTE_ATTACHMENTS_PER_NOTE = 5;
export const NOTE_ATTACHMENT_ACCEPT = ".png,.jpg,.jpeg,.webp,.gif,.pdf,.txt,.csv,.zip";

const registrationNoteService = {
  async list(tournamentId: number, target: RegistrationNoteTarget): Promise<RegistrationNote[]> {
    const response = await apiFetch(base(tournamentId), { query: targetFields(target) });
    return response.json();
  },

  async counts(tournamentId: number): Promise<RegistrationNoteCounts> {
    const response = await apiFetch(`${base(tournamentId)}/counts`);
    return response.json();
  },

  async create(tournamentId: number, target: RegistrationNoteTarget, body: string): Promise<RegistrationNote> {
    const response = await apiFetch(base(tournamentId), {
      method: "POST",
      body: { ...targetFields(target), body }
    });
    return response.json();
  },

  async update(tournamentId: number, noteId: number, body: string): Promise<RegistrationNote> {
    const response = await apiFetch(`${base(tournamentId)}/${noteId}`, { method: "PATCH", body: { body } });
    return response.json();
  },

  async remove(tournamentId: number, noteId: number): Promise<void> {
    await apiFetch(`${base(tournamentId)}/${noteId}`, { method: "DELETE" });
  },

  async uploadAttachment(tournamentId: number, noteId: number, file: File): Promise<RegistrationNote> {
    const formData = new FormData();
    formData.append("file", file);
    const response = await apiFetch(`${base(tournamentId)}/${noteId}/attachments`, {
      method: "POST",
      body: formData
    });
    return response.json();
  },

  async removeAttachment(tournamentId: number, noteId: number, attachmentId: number): Promise<RegistrationNote> {
    const response = await apiFetch(`${base(tournamentId)}/${noteId}/attachments/${attachmentId}`, {
      method: "DELETE"
    });
    return response.json();
  },

  /** A short-lived presigned link to the private object. */
  async attachmentUrl(tournamentId: number, noteId: number, attachmentId: number): Promise<string> {
    const response = await apiFetch(`${base(tournamentId)}/${noteId}/attachments/${attachmentId}/url`);
    const { url }: { url: string } = await response.json();
    return url;
  }
};

export default registrationNoteService;
