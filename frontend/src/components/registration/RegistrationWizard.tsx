"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuthProfile } from "@/hooks/useAuthProfile";
import { ApiError, getApiErrorMessage } from "@/lib/api-error";
import registrationService from "@/services/registration.service";
import meService from "@/services/me.service";
import type { RegistrationForm, RegistrationSubmitInput } from "@/types/registration.types";

import RegistrationSchemaForm from "./RegistrationSchemaForm";

interface RegistrationWizardProps {
  workspaceId: number;
  tournamentId: number;
  tournamentName?: string;
  form: RegistrationForm;
  onClose: () => void;
}

export default function RegistrationWizard({
  workspaceId,
  tournamentId,
  tournamentName,
  form,
  onClose,
}: Readonly<RegistrationWizardProps>) {
  const { user: authUser } = useAuthProfile();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  // Registrant's OWN social accounts — the authoritative self view, the same
  // source the profile settings modal uses. getUserByName was a public/
  // player-name lookup that could resolve to a different identity or omit
  // accounts, so it wrongly reported "no linked accounts" here even when the
  // profile showed them linked.
  const userQuery = useQuery({
    queryKey: ["me", "social"],
    queryFn: () => meService.getSocialAccounts(),
    enabled: !!authUser,
    staleTime: 60_000,
  });

  const mutation = useMutation({
    mutationFn: (payload: RegistrationSubmitInput) =>
      registrationService.register(tournamentId, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["registration", workspaceId, tournamentId] });
      await queryClient.invalidateQueries({
        queryKey: ["registrations-list", workspaceId, tournamentId],
      });
      onClose();
    },
    // `RegistrationSchemaForm` renders every field-scoped rejection under the
    // control it belongs to (and toasts the stale-version one, which names
    // `form_version_id`), so a banner here would be a second copy of the same
    // message. The banner is for what the form has no surface for: a failure
    // that names no field at all.
    onError: (err: unknown) => {
      if (err instanceof ApiError && err.details.some((detail) => detail.field)) return;
      setError(getApiErrorMessage(err));
    },
  });

  return (
    <div className="flex flex-col gap-4">
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
        tournamentId={tournamentId}
        form={form}
        tournamentName={tournamentName}
        userProfile={userQuery.data}
        onSubmit={async ({ form_version_id, answers }) => {
          setError(null);
          await mutation.mutateAsync({ form_version_id, answers });
        }}
        onCancel={onClose}
        submitPending={mutation.isPending}
      />
    </div>
  );
}
