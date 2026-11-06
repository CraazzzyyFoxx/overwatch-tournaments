"use client";

import { useTranslations } from "next-intl";

import { notify } from "@/lib/notify";
import { flowErrorCode } from "@/lib/tournament/flow-errors";

/** The translated, actionable message of a known flow refusal (`errors.flow.<code>`), or null for any other error. */
export function useFlowErrorMessage() {
  const t = useTranslations("errors.flow");
  return (error: unknown): string | null => {
    const code = flowErrorCode(error);
    return code ? t(code) : null;
  };
}

/** Toasts a failed flow move or formation export: a known refusal reads translated, anything else as the API error under `title`. */
export function useFlowErrorNotifier() {
  const message = useFlowErrorMessage();
  return (error: unknown, title?: string) => {
    const known = message(error);
    if (known) notify.error(known);
    else notify.apiError(error, { title });
  };
}
