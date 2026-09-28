"use client";

import { useQuery } from "@tanstack/react-query";
import { useDebounce } from "use-debounce";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import pickBanService from "@/services/pickBan.service";
import type {
  MapVetoMode,
  PickBanKind,
  PickBanRuleset,
  PickBanRulesIssue,
} from "@/types/tournament.types";

/** Long enough that typing a count does not fire a request per keystroke. */
const VALIDATE_DEBOUNCE_MS = 400;

/**
 * The engine's verdict on the ruleset being authored (§6 `validate_ruleset`).
 *
 * Deliberately the server's answer rather than a second implementation here:
 * the validator is the same code the session compiles rounds with, so an
 * editor that agreed with a local copy instead would let an organizer save a
 * ruleset the room then refuses to open.
 */
export function useRulesetValidation({
  tournamentId,
  kind,
  mode,
  ruleset,
}: {
  tournamentId: number;
  kind: PickBanKind;
  mode: MapVetoMode;
  ruleset: PickBanRuleset;
}): { issues: PickBanRulesIssue[]; errors: PickBanRulesIssue[]; pending: boolean } {
  const [debounced] = useDebounce(ruleset, VALIDATE_DEBOUNCE_MS);

  const query = useQuery({
    queryKey: tournamentQueryKeys.pickBanRulesValidation(tournamentId, kind, mode, debounced),
    queryFn: () => pickBanService.validateRuleset(tournamentId, { kind, mode, ruleset: debounced }),
  });

  const issues = query.data?.issues ?? [];
  return {
    issues,
    errors: issues.filter((issue) => issue.severity === "error"),
    // A ruleset edited a moment ago has not been judged yet; the caller must
    // not read "no errors" off a verdict about the previous draft.
    pending: query.isPending || debounced !== ruleset,
  };
}
