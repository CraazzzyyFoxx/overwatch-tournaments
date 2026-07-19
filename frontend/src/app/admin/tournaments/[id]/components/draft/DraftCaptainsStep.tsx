"use client";

import { Search, ShieldCheck, UserRoundCheck, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { DraftRole } from "@/types/draft.types";

import type { DraftCaptainSetup } from "./setup-types";
import { registrationLabel, summarizeRegistration } from "./setup-types";

interface DraftCaptainsStepProps {
  pool: AdminRegistration[];
  teamCount: number;
  value: DraftCaptainSetup;
  onChange: (next: DraftCaptainSetup) => void;
}

export function DraftCaptainsStep({ pool, teamCount, value, onChange }: DraftCaptainsStepProps) {
  const t = useTranslations("draftAdmin");
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<DraftRole | "all">("all");

  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return pool.filter((registration) => {
      const summary = summarizeRegistration(registration);
      return (
        (role === "all" || summary.roles.includes(role)) &&
        (!query || registrationLabel(registration).toLocaleLowerCase().includes(query))
      );
    });
  }, [pool, role, search]);

  const toggle = (id: number) => {
    const selected = value.ids.includes(id);
    if (!selected && value.ids.length >= teamCount) return;
    onChange({
      ...value,
      ids: selected ? value.ids.filter((candidate) => candidate !== id) : [...value.ids, id]
    });
  };

  return (
    <div className="space-y-5">
      <div
        className={cn(
          "sticky top-2 z-10 flex items-center justify-between rounded-xl border px-4 py-3 shadow-sm backdrop-blur",
          value.ids.length === teamCount
            ? "border-emerald-500/30 bg-emerald-500/10"
            : "border-amber-500/30 bg-background/95"
        )}
      >
        <div className="flex items-center gap-3">
          <UserRoundCheck className="h-5 w-5" />
          <span className="text-sm font-medium">{t("captainsSelected")}</span>
        </div>
        <strong className="tabular-nums">
          {value.ids.length} / {teamCount}
        </strong>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.65fr)]">
        <div className="space-y-3">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t("searchCaptains")}
                className="pl-9"
              />
            </div>
            <Select value={role} onValueChange={(next) => setRole(next as DraftRole | "all")}>
              <SelectTrigger className="w-36" aria-label={t("roleFilter")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("allRoles")}</SelectItem>
                <SelectItem value="tank">{t("roles.tank")}</SelectItem>
                <SelectItem value="dps">{t("roles.dps")}</SelectItem>
                <SelectItem value="support">{t("roles.support")}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="max-h-[420px] divide-y divide-border/60 overflow-auto rounded-xl border border-border/70">
            {filtered.map((registration) => {
              const summary = summarizeRegistration(registration);
              const selected = value.ids.includes(registration.id);
              const disabled = !selected && value.ids.length >= teamCount;
              return (
                <label
                  key={registration.id}
                  className={cn(
                    "flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors",
                    selected ? "bg-primary/8" : "hover:bg-muted/50",
                    disabled && "cursor-not-allowed opacity-50"
                  )}
                >
                  <Checkbox
                    checked={selected}
                    disabled={disabled}
                    onCheckedChange={() => toggle(registration.id)}
                    aria-label={t("selectCaptain", { name: registrationLabel(registration) })}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">
                      {registrationLabel(registration)}
                    </span>
                    <span className="mt-1 flex flex-wrap gap-1">
                      {summary.roles.map((entry) => (
                        <Badge key={entry} variant="secondary" className="text-[10px]">
                          {t(`roles.${entry}`)}
                        </Badge>
                      ))}
                    </span>
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {summary.rank ?? "—"}
                  </span>
                </label>
              );
            })}
            {filtered.length === 0 && (
              <p className="px-4 py-10 text-center text-sm text-muted-foreground">
                {t("noCaptainsFound")}
              </p>
            )}
          </div>
        </div>

        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold">{t("selectedTeams")}</h3>
          </div>
          {value.ids.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
              {t("selectCaptainsHint")}
            </div>
          ) : (
            <div className="space-y-2">
              {value.ids.map((id, index) => {
                const registration = pool.find((candidate) => candidate.id === id);
                if (!registration) return null;
                return (
                  <div key={id} className="rounded-xl border border-border/70 bg-card p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">
                        {index + 1}. {registrationLabel(registration)}
                      </span>
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7"
                        onClick={() => toggle(id)}
                        aria-label={t("removeCaptain", { name: registrationLabel(registration) })}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </div>
                    <Label htmlFor={`team-name-${id}`} className="sr-only">
                      {t("teamName")}
                    </Label>
                    <Input
                      id={`team-name-${id}`}
                      className="mt-2 h-8"
                      placeholder={t("teamName")}
                      value={value.teamNames[id] ?? ""}
                      onChange={(event) =>
                        onChange({
                          ...value,
                          teamNames: { ...value.teamNames, [id]: event.target.value }
                        })
                      }
                    />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

