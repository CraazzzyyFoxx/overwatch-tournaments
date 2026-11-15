import type { useTranslations } from "next-intl";

import { BUILTIN_ANSWER_LABELS } from "@/components/balancer/registrations/_components/registrationColumnCells";
import { BUILTIN_STATUS_MESSAGE_KEYS } from "@/lib/registration/balancer-statuses";
import type { AdmissionDecision, StatusMeta } from "@/types/registration.types";

/** The `registrationsAdmin` translator the table hands to its column and row-action builders. */
export type RegistrationsTranslator = ReturnType<typeof useTranslations<"registrationsAdmin">>;

type StatusMessageKey = Parameters<RegistrationsTranslator>[0];

/** A built-in status by its name in the UI language; a value the catalog does not know reads as itself. */
export function builtinStatusName(value: string, t: RegistrationsTranslator): string {
  const keys = BUILTIN_STATUS_MESSAGE_KEYS[value];
  return keys ? t(`status.${keys.label}` as StatusMessageKey) : value;
}

/**
 * The status chip's meta with a built-in status named in the UI language. A workspace's own status
 * keeps the name and description the organizer gave it.
 */
export function localizedStatusMeta(meta: StatusMeta, t: RegistrationsTranslator): StatusMeta {
  const keys = meta.is_builtin ? BUILTIN_STATUS_MESSAGE_KEYS[meta.value] : undefined;
  if (!keys) return meta;
  return {
    ...meta,
    name: t(`status.${keys.label}` as StatusMessageKey),
    description: t(`status.${keys.description}` as StatusMessageKey)
  };
}

const TRANSLATED_ANSWER_KEYS = {
  stream_pov: "columns.streamPov",
  reserve: "columns.onCall",
  public_notes: "columns.publicNotes",
  organizer_notes: "columns.organizerNotes"
} as const;

/** A builtin answer's heading; `undefined` for a key the form builder does not ship. */
export function builtinAnswerLabel(key: string, t: RegistrationsTranslator): string | undefined {
  if (key in TRANSLATED_ANSWER_KEYS) return t(TRANSLATED_ANSWER_KEYS[key as keyof typeof TRANSLATED_ANSWER_KEYS]);
  return BUILTIN_ANSWER_LABELS[key];
}

const ADMISSION_LABEL_KEYS = {
  admitted: "common.admissionStatus.admitted",
  pending_check_in: "common.admissionStatus.pendingCheckIn",
  not_admitted: "common.admissionStatus.notAdmitted"
} as const satisfies Record<AdmissionDecision, string>;

/** One registration's admission decision, in the singular the status badges use (the grouping headers are plural). */
export function admissionDecisionLabel(
  decision: AdmissionDecision,
  t: (key: (typeof ADMISSION_LABEL_KEYS)[AdmissionDecision]) => string
): string {
  return t(ADMISSION_LABEL_KEYS[decision]);
}
