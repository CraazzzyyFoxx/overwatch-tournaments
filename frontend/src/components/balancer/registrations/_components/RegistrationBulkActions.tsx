"use client";

import { Check } from "lucide-react";

import { BulkBar } from "@/components/kit/BulkBar";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { AdminRegistration } from "@/types/balancer-admin.types";

interface RegistrationBulkActionsProps {
  /** Only pending rows are selectable, which is what makes the undo of a bulk
   *  approve able to assume `pending` as every row's prior status. */
  selected: AdminRegistration[];
  clearSelection: () => void;
  onApprove: (
    registrationIds: number[],
    options: { onSuccess: () => void }
  ) => void;
  approvePending: boolean;
  onAddToBalancer: (
    input: { ids: number[]; previouslyExcluded: number[] },
    options: { onSuccess: () => void }
  ) => void;
  addToBalancerPending: boolean;
}

/** The two batch writes the registrations table offers over a selection. */
export default function RegistrationBulkActions({
  selected,
  clearSelection,
  onApprove,
  approvePending,
  onAddToBalancer,
  addToBalancerPending
}: Readonly<RegistrationBulkActionsProps>) {
  return (
    <BulkBar count={selected.length} unit="registrations" onClear={clearSelection}>
      <Button
        size="sm"
        onClick={() => {
          onApprove(
            selected.map((registration) => registration.id),
            { onSuccess: clearSelection }
          );
        }}
        disabled={approvePending}
      >
        {approvePending ? (
          <Spinner className="mr-2" />
        ) : (
          <Check className="mr-2 h-4 w-4" aria-hidden />
        )}
        Approve {selected.length}
      </Button>
      <Button
        size="sm"
        variant="outline"
        onClick={() => {
          onAddToBalancer(
            {
              ids: selected.map((registration) => registration.id),
              // The undo needs the pre-mutation inclusion state, which the
              // refetched rows no longer carry.
              previouslyExcluded: selected
                .filter((registration) => registration.balancer_status_meta.excludes_from_balancer)
                .map((registration) => registration.id)
            },
            { onSuccess: clearSelection }
          );
        }}
        disabled={addToBalancerPending}
      >
        {addToBalancerPending ? (
          <Spinner className="mr-2" />
        ) : (
          <Check className="mr-2 h-4 w-4" aria-hidden />
        )}
        Add to Balancer {selected.length}
      </Button>
    </BulkBar>
  );
}
