"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { parseQuotaAboveInherited } from "@/lib/auth/quota";
import type { QuotaDimension, QuotaScopePolicy } from "@/types/auth.types";
import {
  draftFromLimits,
  hasQuotaOverride,
  raisedDimensions,
  sameQuotaLimits,
  type QuotaLimitsDraft
} from "./dimensions";

export interface QuotaDraft {
  /** What the fields show: the stored row until the operator edits it. */
  draft: QuotaLimitsDraft;
  /** The row as the server has it, i.e. what `reset` goes back to. */
  stored: QuotaLimitsDraft;
  /** Per-dimension rejection text, keyed by the input it belongs under. */
  errors: Partial<Record<QuotaDimension, string>>;
  /** Dimensions the draft raises above the scope's ceiling — superuser-only edits. */
  raised: QuotaDimension[];
  /** Whether saving would change the stored row at all. */
  dirty: boolean;
  /** Whether a row is stored right now, as opposed to the scope inheriting. */
  overridden: boolean;
  set: (dimension: QuotaDimension, value: number | null) => void;
  reset: () => void;
  /** Mark a refused write on the field it names; `false` when it named none. */
  reject: (error: unknown) => boolean;
}

/**
 * The editing half of one quota scope, shared by the workspace screen and the
 * API-key dialog.
 *
 * Seeded from the STORED override rather than from the effective ceiling: an
 * effective number is mostly inherited, so pre-filling with it would turn every
 * glance into a permanent override — and starting empty is worse, because an
 * all-null payload deletes the row, which made "open the form and press the
 * button" a silent reset of limits nobody could see in the first place.
 */
export function useQuotaDraft(policy: QuotaScopePolicy | null | undefined): QuotaDraft {
  const t = useTranslations("quota");
  const stored = draftFromLimits(policy?.override);
  const [state, setState] = useState<{ seed: QuotaLimitsDraft; draft: QuotaLimitsDraft }>(() => ({
    seed: stored,
    draft: stored
  }));
  const [errors, setErrors] = useState<Partial<Record<QuotaDimension, string>>>({});

  // The row arrives one render after mount and can move again under a
  // background refetch. Re-seeding compares VALUES, never object identity: a
  // refetch that returns the same numbers must not wipe an edit in progress,
  // while one that returns different numbers means somebody else moved the row
  // and the stale draft is the wrong thing to keep.
  const fresh = !sameQuotaLimits(state.seed, stored);
  if (fresh) {
    setState({ seed: stored, draft: stored });
    setErrors({});
  }
  const draft = fresh ? stored : state.draft;

  return {
    draft,
    stored,
    errors,
    raised: raisedDimensions(draft, policy?.inherited),
    dirty: !sameQuotaLimits(draft, stored),
    overridden: hasQuotaOverride(stored),
    set: (dimension, value) => {
      setState((current) => ({ ...current, draft: { ...current.draft, [dimension]: value } }));
      setErrors((current) => (current[dimension] ? { ...current, [dimension]: undefined } : current));
    },
    reset: () => {
      setState({ seed: stored, draft: stored });
      setErrors({});
    },
    reject: (error) => {
      const rejection = parseQuotaAboveInherited(error);
      if (!rejection) return false;
      // The refusal names one dimension of one scope. Marking that input is the
      // only rendering an admin can act on: "lower this number, or ask a
      // superuser to raise the plan".
      const dimension = t(`dimensions.${rejection.dimension}.label`);
      setErrors({
        [rejection.dimension]:
          rejection.limit === null
            ? t("errors.aboveInheritedUnlimited", { dimension })
            : t("errors.aboveInherited", {
                dimension,
                limit: rejection.limit,
                requested: rejection.requested ?? draft[rejection.dimension] ?? 0
              })
      });
      return true;
    }
  };
}
