"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  MappingValueCategory,
  MappingValueCategoryName,
  ValueMapRow,
  ValueMappingState,
} from "@/types/balancer-admin.types";
import type { SubroleCatalog } from "@/types/registration.types";

import { ValueMapEditor } from "./ValueMapEditor";

interface ValueMappingTabProps {
  valueState: ValueMappingState;
  valueCategories: MappingValueCategory[];
  subroleCatalog: SubroleCatalog;
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
  onAdd,
  onUpdate,
  onRemove,
  onSeedDefaults,
}: Readonly<ValueMappingTabProps>) {
  const booleanDefaults = categoryEntries(valueCategories, "booleans");
  const roleDefaults = categoryEntries(valueCategories, "roles");
  const subroleDefaults = categoryEntries(valueCategories, "subroles");
  const roleSubroleDefaults = categoryEntries(valueCategories, "role_subroles");
  const divisionDefaults = categoryEntries(valueCategories, "divisions");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Value mapping</CardTitle>
        <CardDescription>
          Translate free-text cell values into the canonical values the balancer expects. Seed the
          catalog defaults, then add or adjust rows as needed.
        </CardDescription>
      </CardHeader>
      {/* Five short key→value lists; two abreast at xl instead of five
          full-width rows of two 600px inputs. The role+sub-role editor has a
          wider value column and keeps the full row. */}
      <CardContent className="grid gap-4 xl:grid-cols-2">
        <ValueMapEditor
          title="Booleans"
          description="Map cell text (e.g. “yes”, “да”) to true/false (used by checkbox-style fields)."
          kind="boolean"
          rows={valueState.booleans}
          canSeed={Object.keys(booleanDefaults).length > 0}
          onAdd={() => onAdd("booleans")}
          onUpdate={(id, updates) => onUpdate("booleans", id, updates)}
          onRemove={(id) => onRemove("booleans", id)}
          onSeedDefaults={() => onSeedDefaults("booleans", booleanDefaults)}
        />
        <ValueMapEditor
          title="Roles"
          description="Map role text (e.g. “танк”, “heal”) to tank / damage / support."
          kind="role"
          rows={valueState.roles}
          canSeed={Object.keys(roleDefaults).length > 0}
          onAdd={() => onAdd("roles")}
          onUpdate={(id, updates) => onUpdate("roles", id, updates)}
          onRemove={(id) => onRemove("roles", id)}
          onSeedDefaults={() => onSeedDefaults("roles", roleDefaults)}
        />
        <ValueMapEditor
          title="Sub-roles"
          description="Map sub-role text from the sheet to a workspace sub-role."
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
          title="Divisions"
          description="Map division text from the sheet directly to the numeric rank value used by the balancer."
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
            title="Role + Sub-role combined"
            description={`Map a single cell value to one or more roles (e.g. "Хитскан ДПС" → DPS/Hitscan, or "Флекс, Танк или Сап" → Tank + Support). Use "Add role" to expand a value into multiple roles.`}
            kind="role_subrole"
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
