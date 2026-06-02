import React from "react";
import { CheckCircle2, Circle, Lock, Unlock, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import StatusMetaBadge from "@/components/status/StatusMetaBadge";
import type { StatusMeta } from "@/types/balancer-admin.types";

interface StatusBadgeProps {
  status?: string | null;
  meta?: StatusMeta | null;
  className?: string;
  compact?: boolean;
}

export function RegistrationStatusBadge({
  status,
  meta,
  className,
  compact,
}: StatusBadgeProps) {
  return (
    <StatusMetaBadge
      meta={meta}
      fallbackValue={status ?? undefined}
      className={className}
      compact={compact}
    />
  );
}

export function BalancerStatusBadge({
  status,
  meta,
  className,
  compact,
}: StatusBadgeProps) {
  return (
    <StatusMetaBadge
      meta={meta}
      fallbackValue={status ?? "not_in_balancer"}
      className={className}
      compact={compact}
    />
  );
}

interface CheckInStatusBadgeProps {
  checkedIn: boolean | undefined | null;
  className?: string;
}

export function CheckInStatusBadge({
  checkedIn,
  className,
}: CheckInStatusBadgeProps) {
  const isCheckedIn = checkedIn === true;
  const label = isCheckedIn ? "Checked In" : "Not Checked In";

  return (
    <span
      title={label}
      aria-label={label}
      className={cn(
        "inline-flex size-5 items-center justify-center",
        isCheckedIn ? "text-emerald-400" : "text-white/35",
        className,
      )}
    >
      {isCheckedIn ? (
        <CheckCircle2 className="size-4" />
      ) : (
        <Circle className="size-4" />
      )}
    </span>
  );
}

interface AdmissionOptions {
  /** When the tournament requires open profiles, a confirmed-closed profile blocks admission. */
  requireOpenProfile?: boolean;
  /** True = public, False = closed, null/undefined = unknown (fails open). */
  profilesOpen?: boolean | null;
}

interface AdmissionStatusBadgeProps extends AdmissionOptions {
  registrationStatus: string;
  balancerStatus: string | undefined | null;
  checkedIn: boolean | undefined | null;
  className?: string;
}

export function isAdmitted(
  registrationStatus: string,
  balancerStatus: string | undefined | null,
  checkedIn: boolean | undefined | null,
  options?: AdmissionOptions,
): boolean {
  if (
    registrationStatus !== "approved" ||
    balancerStatus !== "ready" ||
    checkedIn !== true
  ) {
    return false;
  }
  // Open-profile requirement: only a *confirmed* closed profile blocks admission
  // (unknown fails open, matching the server-side check-in gate).
  if (options?.requireOpenProfile && options.profilesOpen === false) {
    return false;
  }
  return true;
}

export function AdmissionStatusBadge({
  registrationStatus,
  balancerStatus,
  checkedIn,
  requireOpenProfile,
  profilesOpen,
  className,
}: AdmissionStatusBadgeProps) {
  const admitted = isAdmitted(registrationStatus, balancerStatus, checkedIn, {
    requireOpenProfile,
    profilesOpen,
  });
  const label = admitted ? "Admitted" : "Not Admitted";

  return (
    <span
      title={label}
      aria-label={label}
      className={cn(
        "inline-flex size-5 items-center justify-center",
        admitted ? "text-emerald-400" : "text-red-400",
        className,
      )}
    >
      {admitted ? (
        <CheckCircle2 className="size-4" />
      ) : (
        <XCircle className="size-4" />
      )}
    </span>
  );
}

interface ProfileStatusBadgeProps {
  /** True = public, False = closed, null/undefined = unknown / not checked yet. */
  profilesOpen: boolean | null | undefined;
  className?: string;
}

export function ProfileStatusBadge({ profilesOpen, className }: ProfileStatusBadgeProps) {
  const label =
    profilesOpen === true
      ? "Profile open"
      : profilesOpen === false
        ? "Profile closed"
        : "Profile not checked";

  return (
    <span
      title={label}
      aria-label={label}
      className={cn(
        "inline-flex size-5 items-center justify-center",
        profilesOpen === true
          ? "text-emerald-400"
          : profilesOpen === false
            ? "text-red-400"
            : "text-white/35",
        className,
      )}
    >
      {profilesOpen === true ? (
        <Unlock className="size-4" />
      ) : profilesOpen === false ? (
        <Lock className="size-4" />
      ) : (
        <Circle className="size-4" />
      )}
    </span>
  );
}
