"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuthProfile } from "@/hooks/useAuthProfile";
import registrationService from "@/services/registration.service";
import userService from "@/services/user.service";
import type { RegistrationForm } from "@/types/registration.types";

import UnifiedRegistrationForm from "./UnifiedRegistrationForm";

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
}: RegistrationWizardProps) {
  const { user: authUser } = useAuthProfile();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const userQuery = useQuery({
    queryKey: ["user-profile-full", authUser?.username],
    queryFn: () => userService.getUserByName(authUser!.username),
    enabled: !!authUser?.username,
    staleTime: 60_000,
  });

  const mutation = useMutation({
    mutationFn: (payload: any) => {
      return registrationService.register(tournamentId, payload);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["registration", workspaceId, tournamentId] });
      await queryClient.invalidateQueries({
        queryKey: ["registrations-list", workspaceId, tournamentId],
      });
      onClose();
    },
    onError: (err: Error) => setError(err.message),
  });

  return (
    <div className="flex flex-col gap-4">
      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
        </div>
      )}
      <UnifiedRegistrationForm
        mode="public"
        tournamentId={tournamentId}
        workspaceId={workspaceId}
        formConfig={form}
        tournamentName={tournamentName}
        userProfile={userQuery.data}
        onSubmit={async (payload) => {
          setError(null);
          await mutation.mutateAsync(payload);
        }}
        onCancel={onClose}
        submitPending={mutation.isPending}
      />
    </div>
  );
}
