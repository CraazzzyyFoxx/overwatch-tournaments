"use client";

import { Building2, Globe2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useQueryParams } from "@/hooks/useQueryParams";
import type { StatsScopeState } from "@/lib/site/stats-scope";

/**
 * Switches the public statistics between the active workspace and every
 * workspace on the platform. Renders nothing on a tenant (white-label) host,
 * where there is only one workspace to read.
 *
 * `state` is resolved server-side so the first paint already agrees with the
 * host; toggling only rewrites `?scope`, leaving every other filter in place.
 */
export function StatsScopeToggle({
  state,
  className
}: Readonly<{ state: StatsScopeState; className?: string }>) {
  const t = useTranslations();
  const { setParams } = useQueryParams();

  if (!state.available) return null;

  return (
    <ToggleGroup
      type="single"
      variant="pill"
      size="sm"
      value={state.scope}
      onValueChange={(next) => next && setParams({ scope: next === "all" ? "all" : undefined })}
      aria-label={t("common.scope.label")}
      className={className}
    >
      <ToggleGroupItem value="workspace">
        <Building2 size={14} aria-hidden /> {t("common.scope.workspace")}
      </ToggleGroupItem>
      <ToggleGroupItem value="all">
        <Globe2 size={14} aria-hidden /> {t("common.scope.all")}
      </ToggleGroupItem>
    </ToggleGroup>
  );
}

export default StatsScopeToggle;
