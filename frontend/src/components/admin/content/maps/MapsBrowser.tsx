"use client";

import { useId, useMemo } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";

import { DataTable } from "@/components/data-table";
import { CatalogAliasesField, CatalogImageField, CatalogNameField } from "@/components/admin/CatalogFormFields";
import { CatalogSyncDialog } from "@/components/admin/CatalogSyncDialog";
import { useCatalogCommands } from "@/components/admin/CatalogToolbarActions";
import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters } from "@/components/kit/useFilters";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import adminService from "@/services/admin.service";
import type { CatalogEntityRead } from "@/types/catalog.types";
import { usePermissions } from "@/hooks/usePermissions";
import { useCatalogEntityCrud } from "@/hooks/useCatalogEntityCrud";
import { useCatalogSync } from "@/hooks/useCatalogSync";
import { useKindLabel } from "@/hooks/useKindLabel";
import { catalogQueryKeys } from "@/lib/catalog/query-keys";
import { catalogSort } from "@/lib/catalog/sort";
import type { CatalogKindContext } from "@/app/admin/content/_components/ContentDiscipline";

import { CatalogEntityDialogs } from "../shared";
import { mapFilterDefs } from "./filters";
import { EMPTY_FORM, getMapForm, toWrite, type MapForm } from "./model";
import { useMapColumns } from "./useMapColumns";

/** The selected game's maps; where the game declares modes, each map is filed under one. */
export function MapsBrowser({ descriptor, discipline, kind, kindLabel }: Readonly<CatalogKindContext>) {
  const t = useTranslations("adminWorkspace.content");
  const modeLabel = useKindLabel()(descriptor, "mode");
  const hasModes = "mode" in descriptor.kinds;
  const { isSuperuser } = usePermissions();
  const formId = useId();
  const nameFieldId = `${formId}-name`;
  const modeFieldId = `${formId}-mode`;
  const aliasesFieldId = `${formId}-aliases`;

  // A map's mode is a catalog entity of the same discipline; a game without modes never asks.
  const { data: modesData } = useQuery({
    queryKey: catalogQueryKeys.adminList({ discipline }, "mode", { per_page: -1 }),
    queryFn: async ({ signal }) =>
      (await adminService.listCatalogEntities(discipline, "mode", { per_page: -1 }, { signal })).results,
    enabled: hasModes,
  });

  const crud = useCatalogEntityCrud<CatalogEntityRead, MapForm, MapForm>({
    discipline,
    kind,
    emptyForm: EMPTY_FORM,
    getForm: getMapForm,
    service: {
      create: (d, k, data) => adminService.createCatalogEntity(d, k, toWrite(hasModes, data)),
      update: (d, k, id, data) => adminService.updateCatalogEntity(d, k, id, toWrite(hasModes, data)),
      delete: (d, k, id) => adminService.deleteCatalogEntity(d, k, id),
    },
  });
  const { formData, setFormData } = crud;
  const sync = useCatalogSync(discipline);

  const filterDefs = useMemo(
    () => mapFilterDefs({ hasModes, modes: modesData ?? [], modeLabel, t }),
    [hasModes, modesData, modeLabel, t]
  );
  const filters = useFilters(filterDefs);
  const modeFilter = String(filters.values.mode ?? "");
  const competitiveFilter = String(filters.values.in_competitive ?? "");
  const activeFilter = String(filters.values.active ?? "");

  const listFilters = (page: number, search: string, pageSize: number, sortField: string | null, sortDir: "asc" | "desc") => ({
    page,
    per_page: pageSize,
    search,
    sort: catalogSort(sortField),
    order: sortDir,
    ...(modeFilter && { parent_id: Number(modeFilter) }),
    // `false` is a real filter value (the casual pool), so test the string, not truthiness.
    ...(competitiveFilter && { attrs: { in_competitive: competitiveFilter === "true" } }),
    ...(activeFilter && { active: activeFilter === "true" }),
  });

  const columns = useMapColumns({
    kindLabel,
    hasModes,
    modeLabel,
    isSuperuser,
    onEdit: crud.openEdit,
    onDelete: crud.setDeletingEntity,
  });
  const commands = useCatalogCommands({
    canSync: isSuperuser,
    isSyncing: sync.running,
    onSync: sync.start,
    syncLabel: t("catalog.entity.sync", { game: descriptor.name }),
    onCreate: crud.openCreate,
    createLabel: t("catalog.entity.create", { kind: kindLabel }),
  });

  return (
    <>
      <DataTable
        queryKey={(page, search, pageSize, sortField, sortDir) =>
          catalogQueryKeys.adminList({ discipline }, kind, listFilters(page, search, pageSize, sortField, sortDir))
        }
        queryFn={(page, search, pageSize, sortField, sortDir) =>
          adminService.listCatalogEntities(
            discipline,
            kind,
            listFilters(page, search, pageSize, sortField, sortDir)
          )
        }
        columns={columns}
        searchPlaceholder={t("catalog.entity.search", { kind: kindLabel })}
        filterKey={filters.filterKey}
        toolbar={<FilterBar defs={filterDefs} filters={filters} />}
        emptyMessage={t("catalog.entity.empty", { kind: kindLabel })}
        onRowDoubleClick={isSuperuser ? (row) => crud.openEdit(row.original) : undefined}
        commands={commands}
      />

      <CatalogEntityDialogs crud={crud} kindLabel={kindLabel}>
        <CatalogNameField id={nameFieldId} value={formData.name} onChange={(name) => setFormData({ ...formData, name })} />

        <CatalogImageField
          discipline={discipline}
          kind={kind}
          label={t("catalog.entity.image", { kind: kindLabel })}
          name={formData.name || kindLabel}
          value={formData.image_path}
          onChange={(image_path) => setFormData((form) => ({ ...form, image_path }))}
          width={128}
        />

        {hasModes && (
          <div className="space-y-2">
            <Label htmlFor={modeFieldId}>{modeLabel}</Label>
            <Select
              value={formData.parent_id ? formData.parent_id.toString() : ""}
              onValueChange={(value) => setFormData({ ...formData, parent_id: parseInt(value) })}
            >
              <SelectTrigger id={modeFieldId}>
                <SelectValue placeholder={t("catalog.map.selectMode", { kind: modeLabel })} />
              </SelectTrigger>
              <SelectContent>
                {modesData?.map((mode) => (
                  <SelectItem key={mode.id} value={mode.id.toString()}>
                    {mode.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        <CatalogAliasesField
          id={aliasesFieldId}
          aliases={formData.aliases}
          onChange={(aliases) => setFormData({ ...formData, aliases })}
          helperText={t("fields.aliasesHelp")}
        />

        {hasModes && (
          <div className="flex items-center gap-2 pt-2">
            <Checkbox
              id={`${formId}-in-competitive`}
              checked={formData.in_competitive}
              onCheckedChange={(checked) => setFormData({ ...formData, in_competitive: Boolean(checked) })}
            />
            <Label htmlFor={`${formId}-in-competitive`} className="cursor-pointer font-medium text-sm">
              {t("catalog.map.competitiveMap")}
            </Label>
          </div>
        )}

        <div className="flex items-center gap-2">
          <Checkbox
            id={`${formId}-active`}
            checked={formData.active}
            onCheckedChange={(checked) => setFormData({ ...formData, active: Boolean(checked) })}
          />
          <Label htmlFor={`${formId}-active`} className="cursor-pointer font-medium text-sm">
            {t("fields.activeHelp")}
          </Label>
        </div>
      </CatalogEntityDialogs>

      <CatalogSyncDialog descriptor={descriptor} sync={sync} />
    </>
  );
}
