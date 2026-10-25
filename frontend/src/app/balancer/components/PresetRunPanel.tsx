"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";
import {
  Download,
  FolderInput,
  SlidersHorizontal,
  Sparkles,
  type LucideIcon
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FileButton } from "@/components/ui/file-button";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import type { BalancerPlayerExportFormat } from "@/types/balancer-admin.types";
import { TOOLBAR_BUTTON_CLASS } from "@/components/balancer/balancer-page-helpers";
import { Spinner } from "@/components/ui/spinner";
import { WorkspaceCounter } from "./WorkspaceCounter";
import type { JobStatus } from "./useBalancerJob";

type CounterItem = {
  label: string;
  value: number;
  icon: LucideIcon;
};

type PresetRunPanelProps = {
  counters: CounterItem[];
  presetOptions: string[];
  selectedPreset: string;
  onSelectPreset: (preset: string) => void;
  invalidPlayerCount: number;
  excludeInvalidPlayers: boolean;
  onExcludeInvalidPlayersChange: (value: boolean) => void;
  onOpenSettings: () => void;
  settingsDirty: boolean;
  canRunBalance: boolean;
  onRunBalance: () => void;
  isRunPending: boolean;
  onImportBalance: (file: File) => void;
  isImportPending: boolean;
  onExportPlayers: (format: BalancerPlayerExportFormat, includePrivate: boolean) => void;
  isExportPlayersPending: boolean;
  jobStatus: JobStatus | null;
  jobMessage: string | null;
  jobProgress: number | null;
};

export function PresetRunPanel({
  counters,
  presetOptions,
  selectedPreset,
  onSelectPreset,
  invalidPlayerCount,
  excludeInvalidPlayers,
  onExcludeInvalidPlayersChange,
  onOpenSettings,
  settingsDirty,
  canRunBalance,
  onRunBalance,
  isRunPending,
  onImportBalance,
  isImportPending,
  onExportPlayers,
  isExportPlayersPending,
  jobStatus,
  jobMessage,
  jobProgress
}: Readonly<PresetRunPanelProps>) {
  const t = useTranslations("balancerTool.page");
  const [headerSlot, setHeaderSlot] = useState<HTMLElement | null>(null);
  const [includePrivate, setIncludePrivate] = useState(false);

  /* eslint-disable react-hooks/set-state-in-effect -- The portal target is outside this client component and is only available after hydration. */
  useEffect(() => {
    setHeaderSlot(document.getElementById("balancer-header-slot"));
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  const headerControls = (
    <>
      <div className="hidden flex-wrap items-center gap-1.5 md:flex">
        {counters.map((counter) => (
          <WorkspaceCounter
            key={counter.label}
            label={counter.label}
            value={counter.value}
            icon={counter.icon}
          />
        ))}
      </div>
      {invalidPlayerCount > 0 ? (
        <div className="flex h-8 items-center gap-2 rounded-lg border border-amber-400/25 bg-amber-400/[0.06] px-2.5">
          <Switch
            id="exclude-invalid"
            checked={excludeInvalidPlayers}
            onCheckedChange={onExcludeInvalidPlayersChange}
            className="data-[state=checked]:bg-amber-400"
          />
          <label
            htmlFor="exclude-invalid"
            className="cursor-pointer whitespace-nowrap text-xs text-amber-100/82"
          >
            {t("run.skipInvalid", { count: invalidPlayerCount })}
          </label>
        </div>
      ) : null}
      <div className="min-w-[140px] sm:w-[170px]">
        <Select value={selectedPreset} onValueChange={onSelectPreset}>
          <SelectTrigger size="sm">
            <SelectValue placeholder={t("run.presetPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {presetOptions.map((preset) => {
              // A server preset the catalog does not name reads as its key.
              const presetKey = `presets.${preset}` as "presets.DEFAULT";
              return (
                <SelectItem key={preset} value={preset}>
                  {t.has(presetKey) ? t(presetKey) : preset}
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onOpenSettings}
        className={TOOLBAR_BUTTON_CLASS}
      >
        <SlidersHorizontal className="mr-1.5 h-3.5 w-3.5" />
        {t("run.settings")}
        {settingsDirty ? "*" : ""}
      </Button>
      <Button
        onClick={onRunBalance}
        disabled={!canRunBalance}
        size="sm"
        className="rounded-lg bg-primary px-3 text-primary-foreground hover:bg-primary/90"
      >
        {isRunPending ? (
          <Spinner className="mr-1.5 size-3.5" />
        ) : (
          <Sparkles className="mr-1.5 h-3.5 w-3.5" />
        )}
        {t("run.runBalance")}
      </Button>
      <FileButton
        accept="application/json"
        variant="outline"
        size="sm"
        onFiles={([file]) => onImportBalance(file)}
        disabled={isImportPending}
        title={t("run.loadJsonHint")}
        className={TOOLBAR_BUTTON_CLASS}
      >
        {isImportPending ? (
          <Spinner className="mr-1.5 size-3.5" />
        ) : (
          <FolderInput className="mr-1.5 h-3.5 w-3.5" />
        )}
        {t("run.loadJson")}
      </FileButton>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={isExportPlayersPending}
            className={cn(TOOLBAR_BUTTON_CLASS, "shrink-0 px-2 sm:px-3")}
            aria-label={t("run.exportPlayers")}
            title={t("run.exportPlayers")}
          >
            {isExportPlayersPending ? (
              <Spinner className="size-3.5 sm:mr-1.5" />
            ) : (
              <Download className="h-3.5 w-3.5 sm:mr-1.5" />
            )}
            <span className="hidden sm:inline">{t("run.exportPlayers")}</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72">
          <DropdownMenuLabel>{t("run.exportPlayers")}</DropdownMenuLabel>
          <DropdownMenuItem onSelect={() => onExportPlayers("owt-1", includePrivate)}>
            <div>
              <div>{t("run.fullSnapshot")}</div>
              <div className="text-xs text-[color:var(--aqt-fg-dim)]">{t("run.fullSnapshotHint")}</div>
            </div>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => onExportPlayers("xv-1", false)}>
            <div>
              <div>{t("run.solverInput")}</div>
              <div className="text-xs text-[color:var(--aqt-fg-dim)]">{t("run.solverInputHint")}</div>
            </div>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuCheckboxItem
            checked={includePrivate}
            onCheckedChange={(checked) => setIncludePrivate(checked === true)}
            // Kept open so the choice and the export are one interaction.
            onSelect={(event) => event.preventDefault()}
          >
            <span className="text-xs">{t("run.includePrivate")}</span>
          </DropdownMenuCheckboxItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );

  return (
    <>
      {headerSlot ? createPortal(headerControls, headerSlot) : null}

      {jobStatus ? (
        <Card variant="flat" className="px-3 py-2">
          <div className="rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] p-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-sm font-medium text-[color:var(--aqt-fg)]">{t("run.job")}</div>
                {jobMessage ? <div className="text-xs text-[color:var(--aqt-fg-dim)]">{jobMessage}</div> : null}
              </div>
              <Badge
                className={cn(
                  "rounded-full border px-2.5 py-1 text-label font-medium capitalize",
                  jobStatus === "failed"
                    ? "border-red-400/20 bg-red-500/10 text-red-200"
                    : jobStatus === "succeeded"
                      ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200"
                      : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg-muted)]"
                )}
              >
                {t(`job.status.${jobStatus}`)}
              </Badge>
            </div>
            {jobProgress !== null ? (
              <Progress value={jobProgress} className="mt-2.5 h-2 bg-[color:var(--aqt-overlay-3)]" />
            ) : null}
          </div>
        </Card>
      ) : null}
    </>
  );
}
