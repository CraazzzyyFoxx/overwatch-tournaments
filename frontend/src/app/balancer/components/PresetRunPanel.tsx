"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Download,
  FolderInput,
  Loader2,
  SlidersHorizontal,
  Sparkles,
  type LucideIcon
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { PANEL_CLASS, PRESET_LABELS } from "./balancer-page-helpers";
import { WorkspaceCounter } from "./WorkspaceCounter";

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
  onImportTeams: (file: File) => void;
  isImportPending: boolean;
  onExportPlayers: () => void;
  isExportPlayersPending: boolean;
  jobStatus: string | null;
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
  onImportTeams,
  isImportPending,
  onExportPlayers,
  isExportPlayersPending,
  jobStatus,
  jobMessage,
  jobProgress
}: PresetRunPanelProps) {
  const [headerSlot, setHeaderSlot] = useState<HTMLElement | null>(null);
  const importFileRef = useRef<HTMLInputElement>(null);

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
            Skip {invalidPlayerCount} invalid
          </label>
        </div>
      ) : null}
      <div className="min-w-[140px] sm:w-[170px]">
        <Select value={selectedPreset} onValueChange={onSelectPreset}>
          <SelectTrigger className="h-8 rounded-lg border-white/10 bg-black/15 text-sm text-white/82">
            <SelectValue placeholder="Preset" />
          </SelectTrigger>
          <SelectContent>
            {presetOptions.map((preset) => (
              <SelectItem key={preset} value={preset}>
                {PRESET_LABELS[preset] ?? preset}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Button
        type="button"
        variant="outline"
        onClick={onOpenSettings}
        className="h-8 rounded-lg border-white/10 bg-black/15 px-3 text-sm text-white/72 hover:bg-white/[0.05] hover:text-white"
      >
        <SlidersHorizontal className="mr-1.5 h-3.5 w-3.5" />
        Settings{settingsDirty ? "*" : ""}
      </Button>
      <Button
        onClick={onRunBalance}
        disabled={!canRunBalance}
        className="h-8 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
      >
        {isRunPending ? (
          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
        ) : (
          <Sparkles className="mr-1.5 h-3.5 w-3.5" />
        )}
        Run balance
      </Button>
      <input
        ref={importFileRef}
        type="file"
        accept="application/json"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onImportTeams(file);
          event.target.value = "";
        }}
      />
      <Button
        type="button"
        variant="outline"
        onClick={() => importFileRef.current?.click()}
        disabled={isImportPending}
        className="h-8 rounded-lg border-white/10 bg-black/15 px-3 text-sm text-white/72 hover:bg-white/[0.05] hover:text-white"
      >
        {isImportPending ? (
          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
        ) : (
          <FolderInput className="mr-1.5 h-3.5 w-3.5" />
        )}
        Import JSON
      </Button>
      <Button
        type="button"
        variant="outline"
        onClick={onExportPlayers}
        disabled={isExportPlayersPending}
        className="h-8 shrink-0 rounded-lg border-white/10 bg-black/15 px-2 text-sm text-white/72 hover:bg-white/[0.05] hover:text-white sm:px-3"
        aria-label="Export players"
        title="Export players"
      >
        {isExportPlayersPending ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin sm:mr-1.5" />
        ) : (
          <Download className="h-3.5 w-3.5 sm:mr-1.5" />
        )}
        <span className="hidden sm:inline">Export players</span>
      </Button>
    </>
  );

  return (
    <>
      {headerSlot ? createPortal(headerControls, headerSlot) : null}

      {jobStatus ? (
        <div className={cn(PANEL_CLASS, "px-3 py-2")}>
          <div className="rounded-lg border border-white/8 bg-black/15 p-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-sm font-medium text-white/88">Balance job</div>
                {jobMessage ? <div className="text-xs text-white/40">{jobMessage}</div> : null}
              </div>
              <Badge
                className={cn(
                  "rounded-full border px-2.5 py-1 text-[11px] font-medium capitalize",
                  jobStatus === "failed"
                    ? "border-red-400/20 bg-red-500/10 text-red-200"
                    : jobStatus === "succeeded"
                      ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200"
                      : "border-white/10 bg-white/4 text-white/70"
                )}
              >
                {jobStatus}
              </Badge>
            </div>
            {jobProgress !== null ? (
              <Progress value={jobProgress} className="mt-2.5 h-2 bg-white/8" />
            ) : null}
          </div>
        </div>
      ) : null}
    </>
  );
}
