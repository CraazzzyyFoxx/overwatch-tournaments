"use client";

import { useId, useMemo } from "react";
import { useTranslations } from "next-intl";

import { DataTable } from "@/components/data-table";
import { CatalogAliasesField, CatalogImageField, CatalogNameField } from "@/components/admin/CatalogFormFields";
import { CatalogSyncDialog } from "@/components/admin/CatalogSyncDialog";
import { useCatalogCommands } from "@/components/admin/CatalogToolbarActions";
import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters } from "@/components/kit/useFilters";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

import adminService from "@/services/admin.service";
import type { CatalogEntityRead, CatalogEntityWrite } from "@/types/catalog.types";
import { usePermissions } from "@/hooks/usePermissions";
import { useCatalogEntityCrud } from "@/hooks/useCatalogEntityCrud";
import { useCatalogSync } from "@/hooks/useCatalogSync";
import { catalogQueryKeys } from "@/lib/catalog/query-keys";
import { catalogSort } from "@/lib/catalog/sort";
import type { CatalogKindContext } from "@/app/admin/content/_components/ContentDiscipline";

import { activeFilterDef, CatalogEntityDialogs } from "../shared";
import { useGamemodeColumns } from "./useGamemodeColumns";

interface ModeForm {
  name: string;
  image_path: string;
  aliases: string[];
  active: boolean;
}

// Key order matters: `hasUnsavedChanges` compares JSON, so the edit form below
// must list the same fields in the same order or every dialog opens dirty.
const EMPTY_FORM: ModeForm = { name: "", image_path: "", aliases: [], active: true };

function getModeForm(entity: CatalogEntityRead | null): ModeForm {
  if (!entity) return { ...EMPTY_FORM };
  return { name: entity.name, image_path: entity.image_path ?? "", aliases: entity.aliases ?? [], active: entity.active };
}

const toWrite = (form: ModeForm): CatalogEntityWrite => ({ ...form, image_path: form.image_path || null });

export function GamemodesBrowser({ descriptor, discipline, kind, kindLabel }: Readonly<CatalogKindContext>) {
  const t = useTranslations("adminWorkspace.content");
  const { isSuperuser } = usePermissions();
  const formId = useId();
  const nameFieldId = `${formId}-name`;
  const aliasesFieldId = `${formId}-aliases`;

  const crud = useCatalogEntityCrud<CatalogEntityRead, ModeForm, ModeForm>({
    discipline,
    kind,
    emptyForm: EMPTY_FORM,
    getForm: getModeForm,
    service: {
      create: (d, k, data) => adminService.createCatalogEntity(d, k, toWrite(data)),
      update: (d, k, id, data) => adminService.updateCatalogEntity(d, k, id, toWrite(data)),
      delete: (d, k, id) => adminService.deleteCatalogEntity(d, k, id),
    },
  });
  const { formData, setFormData } = crud;
  const sync = useCatalogSync(discipline);

  const filterDefs = useMemo(() => [activeFilterDef(t)], [t]);
  const filters = useFilters(filterDefs);
  const activeFilter = String(filters.values.active ?? "");

  const columns = useGamemodeColumns({
    kindLabel,
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
          catalogQueryKeys.adminList({ discipline }, kind, {
            page,
            per_page: pageSize,
            search,
            sort: catalogSort(sortField),
            order: sortDir,
            ...(activeFilter && { active: activeFilter === "true" }),
          })
        }
        queryFn={(page, search, pageSize, sortField, sortDir) =>
          adminService.listCatalogEntities(discipline, kind, {
            page,
            per_page: pageSize,
            search,
            sort: catalogSort(sortField),
            order: sortDir,
            ...(activeFilter && { active: activeFilter === "true" }),
          })
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
        />

        <CatalogAliasesField
          id={aliasesFieldId}
          aliases={formData.aliases}
          onChange={(aliases) => setFormData({ ...formData, aliases })}
          helperText={t("fields.aliasesHelp")}
        />

        <div className="flex items-center gap-2 pt-2">
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
