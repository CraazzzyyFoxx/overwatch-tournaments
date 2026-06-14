"use client";

import { Check, MoreHorizontal, Pencil, ShieldX, Trash2, Undo2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import type { AdminRegistration } from "@/types/balancer-admin.types";

interface RegistrationRowActionsProps {
  registration: AdminRegistration;
  onEdit: (registration: AdminRegistration) => void;
  onApprove: (registrationId: number) => void;
  onReject: (registrationId: number) => void;
  onToggleBalancer: (registration: AdminRegistration) => void;
  onToggleCheckIn: (registration: AdminRegistration) => void;
  onWithdraw: (registrationId: number) => void;
  onRestore: (registrationId: number) => void;
  onDelete: (registrationId: number) => void;
}

function PrimaryAction({
  registration,
  onApprove,
  onToggleBalancer,
  onRestore
}: Pick<
  RegistrationRowActionsProps,
  "registration" | "onApprove" | "onToggleBalancer" | "onRestore"
>) {
  const { status, status_meta } = registration;

  if (status === "pending") {
    return (
      <Button
        size="sm"
        variant="outline"
        className="h-8 px-2.5 text-xs"
        onClick={() => onApprove(registration.id)}
      >
        <Check className="mr-1.5 h-3.5 w-3.5" />
        Approve
      </Button>
    );
  }

  if (status === "approved") {
    const inBalancer = registration.balancer_status === "ready";
    return (
      <Button
        size="sm"
        variant="outline"
        className="h-8 px-2.5 text-xs"
        onClick={() => onToggleBalancer(registration)}
      >
        {inBalancer ? (
          <ShieldX className="mr-1.5 h-3.5 w-3.5" />
        ) : (
          <Check className="mr-1.5 h-3.5 w-3.5" />
        )}
        {inBalancer ? "Remove" : "Add"}
      </Button>
    );
  }

  if (status === "withdrawn") {
    return (
      <Button
        size="sm"
        variant="outline"
        className="h-8 px-2.5 text-xs"
        onClick={() => onRestore(registration.id)}
      >
        <Undo2 className="mr-1.5 h-3.5 w-3.5" />
        Restore
      </Button>
    );
  }

  if (status_meta.kind === "custom") {
    const inBalancer = registration.balancer_status === "ready";
    return (
      <Button
        size="sm"
        variant="outline"
        className="h-8 px-2.5 text-xs"
        onClick={() => onToggleBalancer(registration)}
      >
        {inBalancer ? (
          <ShieldX className="mr-1.5 h-3.5 w-3.5" />
        ) : (
          <Check className="mr-1.5 h-3.5 w-3.5" />
        )}
        {inBalancer ? "Remove" : "Add"}
      </Button>
    );
  }

  return null;
}

export default function RegistrationRowActions({
  registration,
  onEdit,
  onApprove,
  onReject,
  onToggleBalancer,
  onToggleCheckIn,
  onWithdraw,
  onRestore,
  onDelete
}: RegistrationRowActionsProps) {
  const inBalancer = registration.balancer_status === "ready";

  return (
    <div className="flex items-center justify-end gap-1">
      <PrimaryAction
        registration={registration}
        onApprove={onApprove}
        onToggleBalancer={onToggleBalancer}
        onRestore={onRestore}
      />

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-lg border border-white/10 text-white/55 hover:bg-white/5 hover:text-white"
          >
            <MoreHorizontal className="h-4 w-4" />
            <span className="sr-only">Registration actions</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          <DropdownMenuLabel>Actions</DropdownMenuLabel>
          {registration.status !== "withdrawn" ? (
            <DropdownMenuItem onClick={() => onEdit(registration)}>
              <Pencil className="h-4 w-4" />
              Edit
            </DropdownMenuItem>
          ) : null}

          {registration.status === "pending" ? (
            <>
              <DropdownMenuItem onClick={() => onApprove(registration.id)}>
                <Check className="h-4 w-4" />
                Approve
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onReject(registration.id)}>
                <X className="h-4 w-4" />
                Reject
              </DropdownMenuItem>
            </>
          ) : null}

          {registration.status === "approved" || registration.status_meta.kind === "custom" ? (
            <>
              <DropdownMenuItem onClick={() => onToggleBalancer(registration)}>
                {inBalancer ? <ShieldX className="h-4 w-4" /> : <Check className="h-4 w-4" />}
                {inBalancer ? "Remove from balancer" : "Add to balancer"}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onToggleCheckIn(registration)}>
                <Check className="h-4 w-4" />
                {registration.checked_in ? "Uncheck-in" : "Check-in"}
              </DropdownMenuItem>
            </>
          ) : null}

          <DropdownMenuSeparator />

          {registration.status === "withdrawn" ? (
            <DropdownMenuItem onClick={() => onRestore(registration.id)}>
              <Undo2 className="h-4 w-4" />
              Restore
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem onClick={() => onWithdraw(registration.id)}>
              <Undo2 className="h-4 w-4" />
              Withdraw
            </DropdownMenuItem>
          )}

          <DropdownMenuItem
            onClick={() => onDelete(registration.id)}
            className="text-destructive focus:text-destructive"
          >
            <Trash2 className="h-4 w-4" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
