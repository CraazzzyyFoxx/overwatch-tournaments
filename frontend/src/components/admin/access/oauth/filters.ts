import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { PROVIDER_META } from "@/components/admin/OAuthProviderMark";
import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import type { OAuthProvider } from "@/types/rbac.types";

/** One chip, the provider — every provider the app knows, whether or not a row has it yet. */
export function useOAuthConnectionFilterDefs(
  /** Stable identity required: the defs are memoised on it. */
  providerLabel: (provider: OAuthProvider) => string
): FilterDef[] {
  const t = useTranslations("adminAccess.common");
  return useMemo<FilterDef[]>(
    () => [
      {
        key: "provider",
        label: t("provider"),
        kind: "single",
        options: (Object.keys(PROVIDER_META) as OAuthProvider[]).map((provider) => ({
          value: provider,
          label: providerLabel(provider)
        }))
      }
    ],
    [providerLabel, t]
  );
}
