"use client";

import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle } from "lucide-react";

import { StatusIcon } from "@/components/admin/StatusIcon";
import SearchableImageSelect from "@/components/ui/searchable-image-select";
import { useDisciplines } from "@/hooks/useDisciplineMetadata";
import { useKindLabel } from "@/hooks/useKindLabel";
import { catalogQueryKeys } from "@/lib/catalog/query-keys";
import { WHOLE_CATALOG } from "@/lib/catalog/query-options";
import adminService from "@/services/admin.service";
import type { CatalogAliasMissRead } from "@/types/admin.types";
import type { CatalogKind } from "@/types/catalog.types";

import { attachableKind } from "./model";

/**
 * The row's target picker: the entities of the miss's discipline and kind, loaded when the row renders and shared by
 * every row that names the same game and kind. Rendered twice — in the "Attach to" column and, below `md`, inside
 * the card — because without it the Attach button on a phone would be permanently disabled with no way to arm it.
 */
function MissTargetPicker({
  miss,
  kind,
  value,
  onChange,
  disabled,
}: Readonly<{
  miss: CatalogAliasMissRead;
  kind: CatalogKind;
  value: number | undefined;
  onChange: (entityId: number | undefined) => void;
  disabled: boolean;
}>) {
  const t = useTranslations("adminWorkspace.content");
  const labelOf = useKindLabel();
  const disciplines = useDisciplines("all");
  const targets = useQuery({
    queryKey: catalogQueryKeys.adminList({ discipline: miss.discipline }, kind, WHOLE_CATALOG),
    queryFn: ({ signal }) => adminService.listCatalogEntities(miss.discipline, kind, WHOLE_CATALOG, { signal }),
  });
  const descriptor = disciplines.data?.find((discipline) => discipline.code === miss.discipline);
  const kindLabel = (descriptor ? labelOf(descriptor, kind) : t(`catalog.kinds.${kind}`)).toLowerCase();

  // The mode disambiguates the handful of maps that share a name across modes, which is exactly the pair the
  // parser resolves.
  const options = (targets.data?.results ?? []).map((entity) => ({
    value: String(entity.id),
    label: entity.parent ? `${entity.name} · ${entity.parent.name}` : entity.name,
  }));

  if (targets.isError) {
    return <span className="text-xs text-muted-foreground">{t("catalog.targetsError")}</span>;
  }
  return (
    <SearchableImageSelect
      value={value?.toString()}
      onValueChange={(next) => onChange(next === undefined ? undefined : Number(next))}
      options={options}
      placeholder={t("catalog.pickEntity", { entity: kindLabel })}
      searchPlaceholder={t("catalog.search")}
      isLoading={targets.isLoading}
      disabled={targets.isLoading || disabled}
      size="default"
    />
  );
}

/**
 * The "Attach to" cell and the card's picker line: nothing for a reader, a tick once resolved, a note where dismiss
 * is the only action, otherwise the target picker.
 */
export function MissTarget({
  miss,
  canTriage,
  value,
  onChange,
  disabled,
}: Readonly<{
  miss: CatalogAliasMissRead;
  canTriage: boolean;
  value: number | undefined;
  onChange: (entityId: number | undefined) => void;
  disabled: boolean;
}>) {
  const t = useTranslations("adminWorkspace.content");
  if (!canTriage) {
    return null;
  }
  if (miss.resolved_at) {
    return <StatusIcon icon={CheckCircle} label={t("catalog.resolved")} variant="success" />;
  }
  const kind = attachableKind(miss);
  if (kind === null) {
    return <span className="text-xs text-muted-foreground">{t("catalog.dismissOnly")}</span>;
  }

  return <MissTargetPicker miss={miss} kind={kind} value={value} onChange={onChange} disabled={disabled} />;
}
