"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { ApiError, getApiErrorMessage } from "@/lib/api/error";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import meService from "@/services/me.service";
import registrationService from "@/services/registration.service";
import type {
  EditLockedReason,
  Registration,
  RegistrationForm,
  RegistrationSubmitInput,
} from "@/types/registration.types";

import RegistrationSchemaForm from "./RegistrationSchemaForm";

/**
 * The refusals of the write AS A WHOLE — the same codes `edit_locked_reason`
 * carries on the read model, which is why both surfaces translate them through
 * one `registration.edit.reason.*` namespace.
 *
 * They arrive as a 409 whose `detail` is the bare code, so the string lands in
 * the detail's `msg` rather than its `code` (see `normalizeDetailItem`); both
 * are checked because either is a legitimate shape for the server to pick.
 */
const EDIT_REFUSAL_CODES: Record<string, EditLockedReason> = {
  status_locked: "status_locked",
  checked_in: "checked_in",
  window_closed: "window_closed",
  nothing_editable: "nothing_editable",
};

/**
 * The registrant editing their own answers.
 *
 * Which answers is NOT this component's decision: it forwards the server's
 * `edit_writable_keys` allowlist and renders everything else read-only. The
 * same dialog is also the "the organizer added questions, answer them" path for
 * a `form_version_stale` row, which had no UI at all before.
 */
export default function MyRegistrationEditDialog({
  open,
  onOpenChange,
  workspaceId,
  tournamentId,
  form,
  registration,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: number;
  tournamentId: number;
  /** The CURRENT form: `writableKeys` is resolved against this version, and the
   *  server refuses a save filed against a stale one. */
  form: RegistrationForm;
  registration: Registration;
}>) {
  const t = useTranslations("registration");
  const { user: authUser } = useAuthProfile();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  // The registrant's own linked logins, for the identity questions' handle
  // suggestions — the same self view the sign-up wizard uses.
  const userQuery = useQuery({
    queryKey: ["me", "social"],
    queryFn: () => meService.getSocialAccounts(),
    enabled: open && authUser != null,
    staleTime: 60_000,
  });

  const mutation = useMutation({
    mutationFn: (payload: RegistrationSubmitInput) =>
      registrationService.updateMyRegistration(tournamentId, payload),
    onSuccess: async (updated) => {
      // The response IS the updated row, so the card behind the dialog re-reads
      // it without a round trip. The public list has to be refetched: this edit
      // may have moved the registrant between the main field and the reserve.
      queryClient.setQueryData(
        tournamentQueryKeys.registration(workspaceId, tournamentId),
        updated,
      );
      await queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationsList(workspaceId, tournamentId),
      });
      onOpenChange(false);
    },
    onError: (err: unknown) => {
      // Field-scoped rejections — `locked` on a key the form froze, `required`,
      // a malformed BattleTag — render under their own control through the
      // form's own `fieldErrorsFrom` plumbing. A banner here would be a second
      // copy of the same sentence. Only a refusal naming no field lands here.
      if (err instanceof ApiError && err.details.some((detail) => detail.field)) return;
      let refusal: EditLockedReason | undefined;
      if (err instanceof ApiError) {
        for (const detail of err.details) {
          refusal ??= EDIT_REFUSAL_CODES[detail.code] ?? EDIT_REFUSAL_CODES[detail.msg];
        }
      }
      setError(refusal ? t(`edit.reason.${refusal}`) : getApiErrorMessage(err));
    },
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        // A refusal from the previous attempt must not greet the next one.
        if (!next) setError(null);
      }}
    >
      <DialogContent className="max-h-[94vh] overflow-y-auto sm:max-w-2xl lg:max-w-3xl">
        <DialogTitle>{t("edit.title")}</DialogTitle>
        <p className="text-xs leading-5 text-[color:var(--aqt-fg-muted)]">
          {t("edit.description")}
        </p>

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive"
          >
            {error}
          </div>
        )}

        <RegistrationSchemaForm
          mode="public"
          form={form}
          tournamentId={tournamentId}
          initial={registration}
          userProfile={userQuery.data}
          writableKeys={registration.edit_writable_keys}
          hideTitle
          onSubmit={async ({ form_version_id, answers }) => {
            setError(null);
            await mutation.mutateAsync({ form_version_id, answers });
          }}
          onCancel={() => onOpenChange(false)}
          submitPending={mutation.isPending}
        />
      </DialogContent>
    </Dialog>
  );
}
