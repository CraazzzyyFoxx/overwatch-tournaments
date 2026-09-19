"use client";

import type {
  MappingParserDef,
  MappingTargetDef,
  MappingTargetGroup,
  MappingTargetMode,
  MappingTargetState,
} from "@/types/balancer-admin.types";
import type { SubroleCatalog } from "@/types/registration.types";

import { MappingFieldRow } from "./MappingFieldRow";
import { orderedRoleSubgroups, roleSubgroupId } from "./mappingConfig";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { cn } from "@/lib/utils";

interface MappingRowHandlers {
  onModeChange: (key: string, mode: MappingTargetMode) => void;
  onColumnsChange: (key: string, columns: string[]) => void;
  onValueChange: (key: string, value: string) => void;
  onParserChange: (key: string, parser: string) => void;
  onIsListChange: (key: string, is_list: boolean) => void;
}

interface MappingGroupSectionProps extends MappingRowHandlers {
  group: MappingTargetGroup;
  targets: MappingTargetDef[];
  mappingState: Record<string, MappingTargetState>;
  headerKeys: string[];
  parsers: MappingParserDef[];
  previewByTarget: Record<string, string>;
  errorsByTarget: Record<string, string>;
  disabled?: boolean;
  subroleCatalog?: SubroleCatalog;
}

export function MappingGroupSection({
  group,
  targets,
  mappingState,
  headerKeys,
  parsers,
  previewByTarget,
  errorsByTarget,
  disabled,
  subroleCatalog,
  onModeChange,
  onColumnsChange,
  onValueChange,
  onParserChange,
  onIsListChange,
}: Readonly<MappingGroupSectionProps>) {
  if (targets.length === 0) {
    return null;
  }

  const renderRow = (target: MappingTargetDef) => {
    const state = mappingState[target.key];
    if (!state) {
      return null;
    }
    return (
      <MappingFieldRow
        key={target.key}
        target={target}
        state={state}
        headerKeys={headerKeys}
        parsers={parsers}
        previewValue={previewByTarget[target.key] ?? null}
        error={errorsByTarget[target.key] ?? null}
        disabled={disabled}
        subroleCatalog={subroleCatalog}
        onModeChange={(mode) => onModeChange(target.key, mode)}
        onColumnsChange={(columns) => onColumnsChange(target.key, columns)}
        onValueChange={(value) => onValueChange(target.key, value)}
        onParserChange={(parser) => onParserChange(target.key, parser)}
        onIsListChange={(is_list) => onIsListChange(target.key, is_list)}
      />
    );
  };

  // Rows only — the enclosing card, its title and the group switcher live in
  // `ColumnMappingTab`, so one card carries the whole editor.
  if (group === "roles") {
    return (
      <div className="space-y-4">
        {orderedRoleSubgroups(targets).map((subgroup) => {
          const subTargets = targets.filter((target) => roleSubgroupId(target.key) === subgroup.id);
          if (subTargets.length === 0) {
            return null;
          }
          return (
            <div key={subgroup.id} className="overflow-hidden rounded-lg border">
              <div className={cn(EYEBROW_CLASS, "border-b bg-muted/40 px-4 py-2")}>
                {subgroup.label}
              </div>
              <div className="divide-y">{subTargets.map(renderRow)}</div>
            </div>
          );
        })}
      </div>
    );
  }

  return <div className="divide-y rounded-lg border">{targets.map(renderRow)}</div>;
}
