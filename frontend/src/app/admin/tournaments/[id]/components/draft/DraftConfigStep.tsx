"use client";

import { ChevronDown, Clock3, ShieldCheck, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type { DraftAutopickStrategy, DraftFormat } from "@/types/draft.types";

import { roundsForTeamSize } from "./setup-model";
import type { DraftSetupConfig } from "./setup-types";

interface DraftConfigStepProps {
  value: DraftSetupConfig;
  onChange: (next: DraftSetupConfig) => void;
  locked?: boolean;
}

const PICK_TIME_PRESETS = [30, 45, 60, 90];
const FORMATS: DraftFormat[] = ["snake", "linear", "custom"];

export function DraftConfigStep({ value, onChange, locked = false }: DraftConfigStepProps) {
  const t = useTranslations("draftAdmin");
  const rounds = roundsForTeamSize(value.teamSize);

  const patch = (next: Partial<DraftSetupConfig>) => onChange({ ...value, ...next });
  const setTeamSize = (teamSize: number) => {
    const nextRounds = roundsForTeamSize(teamSize);
    patch({
      teamSize,
      roundRules: Array.from(
        { length: nextRounds },
        (_, index) => value.roundRules[index] ?? "linear"
      )
    });
  };

  return (
    <div className="space-y-6">
      {locked && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-900 dark:text-amber-100">
          {t("configLocked")}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="draft-team-size">{t("teamSize")}</Label>
          <div className="relative">
            <Users className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              id="draft-team-size"
              className="pl-9"
              type="number"
              min={2}
              max={9}
              disabled={locked}
              value={value.teamSize}
              onChange={(event) => setTeamSize(Number(event.target.value) || 2)}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            {t("roundsDerived", { rounds })}
          </p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="draft-team-count">{t("teamCount")}</Label>
          <Input
            id="draft-team-count"
            type="number"
            min={2}
            max={12}
            disabled={locked}
            value={value.teamCount}
            onChange={(event) => patch({ teamCount: Number(event.target.value) || 2 })}
          />
          <p className="text-xs text-muted-foreground">{t("teamCountHint")}</p>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Clock3 className="h-4 w-4 text-muted-foreground" />
          <Label htmlFor="draft-pick-time">{t("pickTime")}</Label>
        </div>
        <div className="flex flex-wrap gap-2">
          {PICK_TIME_PRESETS.map((seconds) => (
            <Button
              key={seconds}
              type="button"
              size="sm"
              disabled={locked}
              variant={value.pickTimeSeconds === seconds ? "default" : "outline"}
              onClick={() => patch({ pickTimeSeconds: seconds })}
            >
              {seconds}s
            </Button>
          ))}
          <Input
            id="draft-pick-time"
            aria-label={t("customPickTime")}
            type="number"
            min={10}
            max={600}
            disabled={locked}
            value={value.pickTimeSeconds}
            onChange={(event) => patch({ pickTimeSeconds: Number(event.target.value) || 45 })}
            className="h-9 w-24"
          />
        </div>
      </div>

      <div className="space-y-3">
        <Label>{t("format")}</Label>
        <div className="grid gap-3 md:grid-cols-3">
          {FORMATS.map((format) => (
            <button
              key={format}
              type="button"
              disabled={locked}
              onClick={() => patch({ format })}
              className={cn(
                "rounded-xl border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60",
                value.format === format
                  ? "border-primary bg-primary/8 ring-1 ring-primary/30"
                  : "border-border/70 bg-card hover:border-primary/40"
              )}
            >
              <span className="font-medium">{t(`formats.${format}.title`)}</span>
              <span className="mt-1 block text-xs text-muted-foreground">
                {t(`formats.${format}.description`)}
              </span>
              <span className="mt-3 flex gap-1" aria-hidden>
                {[1, 2, 3, 4].map((seat, index) => (
                  <span
                    key={seat}
                    className={cn(
                      "grid h-6 w-6 place-items-center rounded-md bg-muted text-[10px] font-semibold",
                      format === "snake" && index > 1 && "bg-primary/15 text-primary"
                    )}
                  >
                    {format === "snake" && index > 1 ? 5 - seat : seat}
                  </span>
                ))}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="draft-autopick">{t("autopick")}</Label>
        <Select
          disabled={locked}
          value={value.autopickStrategy}
          onValueChange={(next) => patch({ autopickStrategy: next as DraftAutopickStrategy })}
        >
          <SelectTrigger id="draft-autopick">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="best_fit">{t("autopicks.best_fit.title")}</SelectItem>
            <SelectItem value="role_need">{t("autopicks.role_need.title")}</SelectItem>
            <SelectItem value="best_available">{t("autopicks.best_available.title")}</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-sm text-muted-foreground">
          {t(`autopicks.${value.autopickStrategy}.description`)}
        </p>
      </div>

      <details className="group rounded-xl border border-border/70 bg-muted/20">
        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium">
          {t("advanced")}
          <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
        </summary>
        <div className="space-y-4 border-t border-border/60 px-4 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <Label htmlFor="draft-admin-override">{t("allowOverride")}</Label>
              <p className="mt-1 text-xs text-muted-foreground">{t("allowOverrideHint")}</p>
            </div>
            <Switch
              id="draft-admin-override"
              disabled={locked}
              checked={value.allowAdminOverride}
              onCheckedChange={(allowAdminOverride) => patch({ allowAdminOverride })}
            />
          </div>
          {value.format === "custom" && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-muted-foreground" />
                <Label>{t("roundRules")}</Label>
                <Badge variant="secondary">{rounds}</Badge>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {Array.from({ length: rounds }, (_, index) => (
                  <Select
                    key={index}
                    disabled={locked}
                    value={value.roundRules[index] ?? "linear"}
                    onValueChange={(rule) => {
                      const roundRules = [...value.roundRules];
                      roundRules[index] = rule;
                      patch({ roundRules });
                    }}
                  >
                    <SelectTrigger aria-label={t("roundNumber", { round: index + 1 })}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="linear">{t("rules.linear")}</SelectItem>
                      <SelectItem value="reverse">{t("rules.reverse")}</SelectItem>
                      <SelectItem value="weakest_first">{t("rules.weakest_first")}</SelectItem>
                      <SelectItem value="strongest_first">{t("rules.strongest_first")}</SelectItem>
                      <SelectItem value="team_avg_asc">{t("rules.team_avg_asc")}</SelectItem>
                      <SelectItem value="team_avg_desc">{t("rules.team_avg_desc")}</SelectItem>
                    </SelectContent>
                  </Select>
                ))}
              </div>
            </div>
          )}
        </div>
      </details>
    </div>
  );
}
