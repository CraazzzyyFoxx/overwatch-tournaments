"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock, LogIn, UserPlus, XCircle } from "lucide-react";
import Link from "next/link";

import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { getCurrentPathForAuthRedirect } from "@/lib/auth-redirect";
import { cn } from "@/lib/utils";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import registrationService from "@/services/registration.service";

import { useTranslation } from "@/i18n/LanguageContext";
import RegistrationWizard from "@/components/registration/RegistrationWizard";

type Props = {
  workspaceId: number;
  tournamentId: number;
  tournamentName?: string;
};

export default function TournamentRegisterButton({ workspaceId, tournamentId, tournamentName }: Props) {
  const { t } = useTranslation();
  const { user, status: authStatus } = useAuthProfile();
  const openAuthModal = useAuthModalStore((state) => state.open);
  const isAuthenticated = authStatus === "authenticated" && user !== null;
  const [showModal, setShowModal] = useState(false);

  const formQuery = useQuery({
    queryKey: ["registration-form", workspaceId, tournamentId],
    queryFn: () => registrationService.getForm(tournamentId),
  });

  const myRegQuery = useQuery({
    queryKey: ["registration", workspaceId, tournamentId],
    queryFn: () => registrationService.getMyRegistration(tournamentId),
    enabled: isAuthenticated,
  });

  const form = formQuery.data;
  const myReg = myRegQuery.data;
  const handleAuthClick = () => {
    const nextPath =
      typeof window === "undefined"
        ? `/tournaments/${tournamentId}`
        : getCurrentPathForAuthRedirect(window.location);

    openAuthModal(nextPath);
  };

  if (formQuery.isLoading) return null;
  if (!form) return null;
  if (isAuthenticated && myRegQuery.isLoading) return null;

  if (!form.is_open) {
    return (
      <div className="inline-flex items-center gap-2 rounded-lg border border-white/7 bg-white/2 px-4 py-2 text-sm text-white/40">
        <Clock className="size-4" />
        {t("registration.button.closed")}
      </div>
    );
  }

  if (myReg) {
    const statusMap: Record<string, { icon: typeof Clock; label: string; className: string }> = {
      pending: { icon: Clock, label: t("common.pendingReview"), className: "border-amber-500/20 bg-amber-500/10 text-amber-400" },
      approved: { icon: CheckCircle2, label: t("common.approved"), className: "border-emerald-500/20 bg-emerald-500/10 text-emerald-400" },
      rejected: { icon: XCircle, label: t("common.rejected"), className: "border-red-500/20 bg-red-500/10 text-red-400" },
      withdrawn: { icon: XCircle, label: t("common.withdrawn"), className: "border-white/10 bg-white/5 text-white/55" },
    };
    const config = statusMap[myReg.status] ?? statusMap.pending;
    const StatusIcon = config.icon;
    return (
      <Link
        href={`/tournaments/${tournamentId}/participants`}
        className={cn("inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition-opacity hover:opacity-80", config.className)}
      >
        <StatusIcon className="size-4" />
        {config.label}
      </Link>
    );
  }

  if (!isAuthenticated) {
    return (
      <button
        type="button"
        onClick={handleAuthClick}
        className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/3 px-4 py-2 text-sm font-medium text-white/75 transition-colors hover:border-white/20 hover:bg-white/6 hover:text-white"
      >
        <LogIn className="size-4" />
        {t("registration.button.loginToRegister")}
      </button>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setShowModal(true)}
        className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-medium text-black transition-opacity hover:opacity-90"
      >
        <UserPlus className="size-4" />
        {t("registration.button.register")}
      </button>

      <Dialog open={showModal} onOpenChange={setShowModal}>
        <DialogContent className="max-h-[94vh] overflow-y-auto sm:max-w-2xl lg:max-w-3xl">
          <DialogTitle className="sr-only">
            {tournamentName ? t("registration.wizard.titleFor", { name: tournamentName }) : t("registration.wizard.title")}
          </DialogTitle>
          <RegistrationWizard
            workspaceId={workspaceId}
            tournamentId={tournamentId}
            tournamentName={tournamentName}
            form={form}
            onClose={() => setShowModal(false)}
          />
        </DialogContent>
      </Dialog>
    </>
  );
}
