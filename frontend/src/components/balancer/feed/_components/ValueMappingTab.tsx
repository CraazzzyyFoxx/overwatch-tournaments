"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@craazzzyyfoxx/admin-kit/ui/card";
import { useTranslations } from "next-intl";
import type {
  MappingValueCategory,
  MappingValueCategoryName,
  ValueMapRow,
  ValueMappingState,
} from "@/types/balancer-admin.types";
import type { SubroleCatalog } from "@/types/registration.types";
import type { RoleOntology } from "@/lib/roster/ontology";

import { ValueMapEditor } from "./ValueMapEditor";

interface ValueMappingTabProps {
  valueState: ValueMappingState;
  valueCategories: MappingValueCategory[];
  subroleCatalog: SubroleCatalog;
  /** The tournament's game: the roles a sheet's text maps to. `null` while it loads. */
  ontology: RoleOntology | null;
  onAdd: (category: MappingValueCategoryName) => void;
  onUpdate: (
    category: MappingValueCategoryName,
    id: string,
    updates: Partial<Pick<ValueMapRow, "key" | "value">>,
  ) => void;
  onRemove: (category: MappingValueCategoryName, id: string) => void;
  onSeedDefaults: (category: MappingValueCategoryName, entries: Record<string, unknown>) => void;
}

function categoryEntries(
  categories: MappingValueCategory[],
  name: MappingValueCategoryName,
): Record<string, unknown> {
  return categories.find((category) => category.category === name)?.entries ?? {};
}

export function ValueMappingTab({
  valueState,
  valueCategories,
  subroleCatalog,
  ontology,
  onAdd,
  onUpdate,
  onRemove,
  onSeedDefaults,
}: Readonly<ValueMappingTabProps>) {
  const t = useTranslations("sheetsFeed.valueMapping");
  const booleanDefaults = categoryEntries(valueCategories, "booleans");
  const roleDefaults = categoryEntries(valueCategories, "roles");
  const subroleDefaults = categoryEntries(valueCategories, "subroles");
  const roleSubroleDefaults = categoryEntries(valueCategories, "role_subroles");
  const divisionDefaults = categoryEntries(valueCategories, "divisions");

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>
          {t("description")}
        </CardDescription>
      </CardHeader>
      {/* Five short key→value lists; two abreast at xl instead of five
          full-width rows of two 600px inputs. The role+sub-role editor has a
          wider value column and keeps the full row. */}
      <CardContent className="grid gap-4 xl:grid-cols-2">
        <ValueMapEditor
          title={t("categories.booleans")}
          description={t("descriptions.booleans")}
          kind="boolean"
          rows={valueState.booleans}
          canSeed={Object.keys(booleanDefaults).length > 0}
          onAdd={() => onAdd("booleans")}
          onUpdate={(id, updates) => onUpdate("booleans", id, updates)}
          onRemove={(id) => onRemove("booleans", id)}
          onSeedDefaults={() => onSeedDefaults("booleans", booleanDefaults)}
        />
        <ValueMapEditor
          title={t("categories.roles")}
          description={t("descriptions.roles")}
          kind="role"
          ontology={ontology}
          rows={valueState.roles}
          canSeed={Object.keys(roleDefaults).length > 0}
          onAdd={() => onAdd("roles")}
          onUpdate={(id, updates) => onUpdate("roles", id, updates)}
          onRemove={(id) => onRemove("roles", id)}
          onSeedDefaults={() => onSeedDefaults("roles", roleDefaults)}
        />
        <ValueMapEditor
          title={t("categories.subroles")}
          description={t("descriptions.subroles")}
          kind="subrole"
          rows={valueState.subroles}
          canSeed={Object.keys(subroleDefaults).length > 0}
          subroleCatalog={subroleCatalog}
          onAdd={() => onAdd("subroles")}
          onUpdate={(id, updates) => onUpdate("subroles", id, updates)}
          onRemove={(id) => onRemove("subroles", id)}
          onSeedDefaults={() => onSeedDefaults("subroles", subroleDefaults)}
        />
        <ValueMapEditor
          title={t("categories.divisions")}
          description={t("descriptions.divisions")}
          kind="number"
          rows={valueState.divisions}
          canSeed={Object.keys(divisionDefaults).length > 0}
          onAdd={() => onAdd("divisions")}
          onUpdate={(id, updates) => onUpdate("divisions", id, updates)}
          onRemove={(id) => onRemove("divisions", id)}
          onSeedDefaults={() => onSeedDefaults("divisions", divisionDefaults)}
        />
        <div className="xl:col-span-2">
          <ValueMapEditor
            title={t("categories.roleSubroles")}
            description={t("descriptions.roleSubroles")}
            kind="role_subrole"
            ontology={ontology}
            rows={valueState.role_subroles}
            canSeed={Object.keys(roleSubroleDefaults).length > 0}
            subroleCatalog={subroleCatalog}
            onAdd={() => onAdd("role_subroles")}
            onUpdate={(id, updates) => onUpdate("role_subroles", id, updates)}
            onRemove={(id) => onRemove("role_subroles", id)}
            onSeedDefaults={() => onSeedDefaults("role_subroles", roleSubroleDefaults)}
          />
        </div>
      </CardContent>
    </Card>
  );
}
