"use client";

import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";

import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@craazzzyyfoxx/admin-kit/ui/select";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

const NONE = "none";

/**
 * The character a rule shows, chosen from that rule's *own* game's catalog. The
 * catalog is keyed by `discipline`, so an Overwatch list can never be offered
 * to a League rule. The read is the workspace-scoped one open to anyone who may edit
 * the workspace's achievements. When it still cannot be read the current link is kept and shown by id rather than silently cleared.
 */
export function RuleEntityField({
  discipline,
  value,
  onChange,
}: Readonly<{
  discipline: string;
  value: number | null | undefined;
  onChange: (entityId: number | null) => void;
}>) {
  const t = useTranslations("adminAchievements");
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const { data, isError, isPending } = useQuery({
    queryKey: achievementQueryKeys.entities(workspaceId, discipline),
    queryFn: () => adminService.getCatalogCharacters(workspaceId!, discipline),
    enabled: discipline !== "" && workspaceId !== null,
    staleTime: 5 * 60_000,
  });

  const options = (data ?? []).filter((entity) => entity.active || entity.id === value);
  const linked = value ?? null;
  const known = linked !== null && options.some((entity) => entity.id === linked);

  return (
    <div className="space-y-2">
      <Label htmlFor="rule-entity">{t("form.entity")}</Label>
      <Select
        value={linked === null ? NONE : String(linked)}
        onValueChange={(next) => onChange(next === NONE ? null : Number(next))}
        disabled={isPending}
      >
        <SelectTrigger id="rule-entity">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>{t("form.entityNone")}</SelectItem>
          {linked !== null && !known && (
            <SelectItem value={String(linked)}>{t("form.entityLinked", { id: linked })}</SelectItem>
          )}
          {options.map((entity) => (
            <SelectItem key={entity.id} value={String(entity.id)}>
              {entity.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {isError && (
        <p className="text-xs text-muted-foreground" role="status">
          {t("form.entityUnavailable")}
        </p>
      )}
    </div>
  );
}
