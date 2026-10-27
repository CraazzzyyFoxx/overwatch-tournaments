"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import type {
  MappingParserDef,
  MappingTargetDef,
  MappingTargetMode,
  MappingTargetState,
} from "@/types/balancer-admin.types";
import type { SubroleCatalog } from "@/types/registration.types";

import { HeaderCombobox } from "./HeaderCombobox";
import { HeaderMultiCombobox } from "./HeaderMultiCombobox";
import { ModeToggle } from "./ModeToggle";
import { eyebrowClass } from "@/components/ui/eyebrow";

const AUTO_FIELD_MODES: MappingTargetMode[] = ["auto", "columns"];
const STANDARD_FIELD_MODES: MappingTargetMode[] = ["columns", "constant", "disabled"];
const NONE = "__none__";

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
  subroleCatalog?: SubroleCatalog;
  onModeChange: (mode: MappingTargetState["mode"]) => void;
  onColumnsChange: (columns: string[]) => void;
  onValueChange: (value: string) => void;
  onParserChange: (parser: string) => void;
  onIsListChange: (is_list: boolean) => void;
}

/** The role a `roles.<code>.subrole` target takes its sub-role options from, whatever game's role it is. */
function subroleRoleFromTarget(key: string): string | null {
  const match = /^roles\.([^.]+)\.subrole$/.exec(key);
  return match?.[1] ?? null;
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
  subroleCatalog,
  onModeChange,
  onColumnsChange,
  onValueChange,
  onParserChange,
  onIsListChange,
}: Readonly<MappingFieldRowProps>) {
  const t = useTranslations("sheetsFeed.mappingField");
  const acceptedParsers = parsers.filter((def) => target.accepted_parsers.includes(def.parser));
  const showParser = state.mode !== "disabled" && state.mode !== "auto" && acceptedParsers.length > 1;
  const activeParser = state.parser ?? target.default_parser;
  const availableModes = target.default_mode === "auto" ? AUTO_FIELD_MODES : STANDARD_FIELD_MODES;
  const showIsListToggle = target.default_is_list && state.mode === "columns";
  const subroleRole = target.default_parser === "subrole_token" ? subroleRoleFromTarget(target.key) : null;
  const subroleOptions = subroleRole ? (subroleCatalog?.[subroleRole] ?? []) : [];

  // Four columns at lg: label · mode · input · preview. The preview used to
  // stack under the input, leaving the picker to stretch across the hub.
  return (
    <div className={cn("px-4 py-3", error && "bg-destructive/5")}>
      <div className="grid items-start gap-3 md:grid-cols-[minmax(160px,220px)_auto_minmax(220px,1fr)] lg:grid-cols-[minmax(160px,220px)_auto_minmax(220px,420px)_minmax(0,1fr)]">
        {/* Label + required badge */}
        <div className="min-w-0 pt-1.5">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium" title={target.label}>
              {target.label}
            </span>
            {target.required ? (
              <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-semibold text-primary">
                {t("required")}
              </span>
            ) : null}
          </div>
          <p className="truncate font-mono text-xs text-muted-foreground/60" title={target.key}>
            {target.key}
          </p>
        </div>

        {/* Mode toggle */}
        <div className="pt-0.5">
          <ModeToggle
            value={state.mode}
            onChange={onModeChange}
            fieldLabel={target.label}
            availableModes={availableModes}
            disabled={disabled}
          />
        </div>

        {/* Mode-specific input + parser */}
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
            subroleRole ? (
              <Select
                value={state.value ? state.value : NONE}
                onValueChange={(value) => onValueChange(value === NONE ? "" : value)}
                disabled={disabled || subroleOptions.length === 0}
              >
                <SelectTrigger>
                  <SelectValue
                    placeholder={subroleOptions.length === 0 ? t("noSubroles") : t("subrole")}
                  />
                </SelectTrigger>
                <SelectContent>
                    <SelectItem value={NONE}>{t("none")}</SelectItem>
                  {subroleOptions.map((option) => (
                    <SelectItem key={option.slug} value={option.slug}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input
                value={state.value ?? ""}
                onChange={(event) => onValueChange(event.target.value)}
                placeholder={t("constantPlaceholder")}
                disabled={disabled}
              />
            )
          ) : null}

          {state.mode === "disabled" ? (
            <p className="text-xs italic text-muted-foreground/60">{t("notSynced")}</p>
          ) : null}

          {state.mode === "auto" ? (
            <p className="text-xs italic text-muted-foreground/60">{t("derivedAutomatically")}</p>
          ) : null}

          {showIsListToggle ? (
            <label className="flex cursor-pointer items-center gap-2 text-xs">
              <Checkbox
                checked={state.is_list ?? target.default_is_list}
                onCheckedChange={(checked) => onIsListChange(checked === true)}
                disabled={disabled}
              />
              <span className="text-muted-foreground">{t("parseAsList")}</span>
            </label>
          ) : null}

          {showParser ? (
            <div className="flex items-center gap-2">
              <span className={eyebrowClass("muted")}>
                {t("parser")}
              </span>
              <Select value={activeParser} onValueChange={onParserChange} disabled={disabled}>
                <SelectTrigger size="sm">
                  <SelectValue>{parserLabel(parsers, activeParser)}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {acceptedParsers.map((def) => (
                    <SelectItem key={def.parser} value={def.parser}>
                      {def.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}
        </div>

        {/* Preview + error */}
        {(state.mode !== "disabled" && previewValue) || error ? (
          <div className="min-w-0 space-y-1 lg:pt-2">
            {state.mode !== "disabled" && previewValue ? (
              <p className="truncate text-xs text-muted-foreground" title={previewValue}>
                <span className="text-muted-foreground/60">{t("preview")}:</span> {previewValue}
              </p>
            ) : null}
            {error ? <p className="text-xs font-medium text-destructive">{error}</p> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
