"use client";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type {
  MappingParserDef,
  MappingTargetDef,
  MappingTargetState,
} from "@/types/balancer-admin.types";

import { HeaderCombobox } from "./HeaderCombobox";
import { HeaderMultiCombobox } from "./HeaderMultiCombobox";
import { ModeToggle } from "./ModeToggle";

interface MappingFieldRowProps {
  target: MappingTargetDef;
  state: MappingTargetState;
  headerKeys: string[];
  parsers: MappingParserDef[];
  /** Inline preview value derived from preview row 0, if any. */
  previewValue?: string | null;
  /** Inline per-field error message, if any. */
  error?: string | null;
  disabled?: boolean;
  onModeChange: (mode: MappingTargetState["mode"]) => void;
  onColumnsChange: (columns: string[]) => void;
  onValueChange: (value: string) => void;
  onParserChange: (parser: string) => void;
}

function parserLabel(parsers: MappingParserDef[], parser: string): string {
  return parsers.find((def) => def.parser === parser)?.label ?? parser;
}

export function MappingFieldRow({
  target,
  state,
  headerKeys,
  parsers,
  previewValue,
  error,
  disabled,
  onModeChange,
  onColumnsChange,
  onValueChange,
  onParserChange,
}: MappingFieldRowProps) {
  const acceptedParsers = parsers.filter((def) => target.accepted_parsers.includes(def.parser));
  const showParser = state.mode !== "disabled" && acceptedParsers.length > 1;
  const activeParser = state.parser ?? target.default_parser;

  return (
    <div className={cn("px-4 py-3", error && "bg-destructive/5")}>
      <div className="grid items-start gap-3 md:grid-cols-[minmax(170px,1fr)_auto_minmax(220px,1.4fr)]">
        {/* Label + required badge */}
        <div className="min-w-0 pt-1.5">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium" title={target.label}>
              {target.label}
            </span>
            {target.required ? (
              <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                Required
              </span>
            ) : null}
          </div>
          <p className="truncate font-mono text-[10px] text-muted-foreground/60" title={target.key}>
            {target.key}
          </p>
        </div>

        {/* Mode toggle */}
        <div className="pt-0.5">
          <ModeToggle value={state.mode} onChange={onModeChange} disabled={disabled} />
        </div>

        {/* Mode-specific input + parser + preview + error */}
        <div className="min-w-0 space-y-2">
          {state.mode === "columns" ? (
            target.multi_column ? (
              <HeaderMultiCombobox
                options={headerKeys}
                value={state.columns}
                onChange={onColumnsChange}
                disabled={disabled}
              />
            ) : (
              <HeaderCombobox
                options={headerKeys}
                value={state.columns[0] ?? null}
                onChange={(next) => onColumnsChange(next ? [next] : [])}
                disabled={disabled}
              />
            )
          ) : null}

          {state.mode === "constant" ? (
            <Input
              value={state.value ?? ""}
              onChange={(event) => onValueChange(event.target.value)}
              placeholder="Constant value applied to every row"
              disabled={disabled}
              className="h-9"
            />
          ) : null}

          {state.mode === "disabled" ? (
            <p className="text-xs italic text-muted-foreground/60">Not synced.</p>
          ) : null}

          {showParser ? (
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/75">
                Parser
              </span>
              <Select value={activeParser} onValueChange={onParserChange} disabled={disabled}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue>{parserLabel(parsers, activeParser)}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {acceptedParsers.map((def) => (
                    <SelectItem key={def.parser} value={def.parser} className="text-xs">
                      {def.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}

          {state.mode !== "disabled" && previewValue ? (
            <p className="truncate text-xs text-muted-foreground" title={previewValue}>
              <span className="text-muted-foreground/60">Preview:</span> {previewValue}
            </p>
          ) : null}

          {error ? <p className="text-xs font-medium text-destructive">{error}</p> : null}
        </div>
      </div>
    </div>
  );
}
