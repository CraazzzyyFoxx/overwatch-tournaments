"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { PROVIDER_LABELS, requiredProviders } from "@/lib/registration/subscription-requirement";
import registrationService from "@/services/registration.service";
import type { SubscriptionRequirement } from "@/types/registration.types";
import SubscriptionRow from "./SubscriptionRow";
import SubscriptionRuleNotice from "./SubscriptionRuleNotice";

interface CheckInSubscriptionProofProps {
  tournamentId: number;
  /** Declaration order for the rows; falls back to whatever the server resolved. */
  requirement?: SubscriptionRequirement | null;
  /** Whether the check-in dialog is on screen. Gates the query so a closed dialog
   *  never polls the provider-backed status endpoint. */
  active: boolean;
}

/**
 * The subscription half of the check-in dialog: the rule, one chip per required
 * provider, and — for providers verified by a secret published in a
 * subscriber-only post — the field to paste it.
 *
 * This is the ONLY place that field exists. Signup shows the same verdicts but
 * never asks for the phrase: at signup nothing has been offered yet, so the
 * registration gate deliberately defers every code-satisfiable provider (see
 * `shared/services/subscriptions/requirement.py`), and asking for a secret before a
 * registration exists put the one manual step in the flow at the point where it
 * could not be enforced. Check-in is where the requirement is final, so it is
 * also where the last manual proof belongs.
 */
export default function CheckInSubscriptionProof({
  tournamentId,
  requirement,
  active
}: Readonly<CheckInSubscriptionProofProps>) {
  const queryClient = useQueryClient();

  const statusQuery = useQuery({
    queryKey: tournamentQueryKeys.subscriptionStatus(tournamentId),
    queryFn: () => registrationService.getMySubscriptionStatus(tournamentId),
    enabled: active,
    staleTime: 30_000
  });

  const status = statusQuery.data;
  if (!status?.required) return null;

  const handleRedeemCode = async (code: string, provider: string) => {
    const next = await registrationService.redeemSubscriptionCode(tournamentId, code, provider);
    // The redemption response IS the recomposed status: writing it back turns the
    // chip green in place, so the patron sees the code land before pressing
    // check-in rather than discovering it in a 400.
    queryClient.setQueryData(tournamentQueryKeys.subscriptionStatus(tournamentId), next);
  };

  const declared = requiredProviders(requirement);
  const providers = declared.length > 0 ? declared : Object.keys(status.verdicts ?? {});

  return (
    <div className="grid gap-3 text-left">
      <SubscriptionRuleNotice subscription={status} />
      {providers.map((provider) => (
        <SubscriptionRow
          key={provider}
          provider={provider}
          providerLabel={PROVIDER_LABELS[provider] ?? provider}
          subscription={status}
          onRedeemCode={handleRedeemCode}
        />
      ))}
    </div>
  );
}
