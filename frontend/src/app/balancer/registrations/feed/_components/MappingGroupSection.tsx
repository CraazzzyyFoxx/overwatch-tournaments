"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  MappingParserDef,
  MappingTargetDef,
  MappingTargetGroup,
  MappingTargetMode,
  MappingTargetState,
} from "@/types/balancer-admin.types";

import { MappingFieldRow } from "./MappingFieldRow";
import {
  GROUP_DESCRIPTIONS,
  GROUP_LABELS,
  orderedRoleSubgroups,
  roleSubgroupId,
} from "./mappingConfig";

export interface MappingRowHandlers {
  onModeChange: (key: string, mode: MappingTargetMode) => void;
  onColumnsChange: (key: string, columns: string[]) => void;
  onValueChange: (key: string, value: string) => void;
  onParserChange: (key: string, parser: string) => void;
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
  onModeChange,
  onColumnsChange,
  onValueChange,
  onParserChange,
}: MappingGroupSectionProps) {
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
        onModeChange={(mode) => onModeChange(target.key, mode)}
        onColumnsChange={(columns) => onColumnsChange(target.key, columns)}
        onValueChange={(value) => onValueChange(target.key, value)}
        onParserChange={(parser) => onParserChange(target.key, parser)}
      />
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{GROUP_LABELS[group]}</CardTitle>
        <CardDescription>{GROUP_DESCRIPTIONS[group]}</CardDescription>
      </CardHeader>
      <CardContent>
        {group === "roles" ? (
          <div className="space-y-4">
            {orderedRoleSubgroups(targets).map((subgroup) => {
              const subTargets = targets.filter((target) => roleSubgroupId(target.key) === subgroup.id);
              if (subTargets.length === 0) {
                return null;
              }
              return (
                <div key={subgroup.id} className="overflow-hidden rounded-lg border">
                  <div className="border-b bg-muted/40 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {subgroup.label}
                  </div>
                  <div className="divide-y">{subTargets.map(renderRow)}</div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="divide-y rounded-lg border">{targets.map(renderRow)}</div>
        )}
      </CardContent>
    </Card>
  );
}
