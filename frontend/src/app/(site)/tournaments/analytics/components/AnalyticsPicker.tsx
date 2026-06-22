"use client";

import React from "react";

import { AlgorithmAnalytics } from "@/types/analytics.types";
import type { Tournament } from "@/types/tournament.types";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface AnalyticsPickerProps {
  tournaments: Tournament[];
  algorithms: AlgorithmAnalytics[];
  tournamentId: number | null;
  algorithmId: number | null;
  loadingTournaments: boolean;
  loadingAlgorithms: boolean;
  isErrorTournaments: boolean;
  isErrorAlgorithms: boolean;
  onTournamentChange: (value: string) => void;
  onAlgorithmChange: (value: string) => void;
}

interface TooltipSelectProps {
  tooltip: string;
  value: string;
  placeholder: string;
  disabled?: boolean;
  className?: string;
  onValueChange: (value: string) => void;
  children: React.ReactNode;
}

/**
 * A compact Select whose label lives in a hover tooltip (and aria-label) rather
 * than a stacked caption — keeps the picker row tidy under the KPI cards.
 */
function TooltipSelect({
  tooltip,
  value,
  placeholder,
  disabled,
  className,
  onValueChange,
  children,
}: TooltipSelectProps) {
  return (
    <TooltipProvider delayDuration={200}>
      <Select value={value} onValueChange={onValueChange} disabled={disabled}>
        <Tooltip>
          <TooltipTrigger asChild>
            <SelectTrigger aria-label={tooltip} className={cn("h-9", className)}>
              <SelectValue placeholder={placeholder} />
            </SelectTrigger>
          </TooltipTrigger>
          <TooltipContent side="top">{tooltip}</TooltipContent>
        </Tooltip>
        {children}
      </Select>
    </TooltipProvider>
  );
}

/**
 * Tournament + ranking-model selectors as a compact, label-less control row
 * (each select carries a tooltip). Sits under the KPI cards.
 */
export default function AnalyticsPicker({
  tournaments,
  algorithms,
  tournamentId,
  algorithmId,
  loadingTournaments,
  loadingAlgorithms,
  isErrorTournaments,
  isErrorAlgorithms,
  onTournamentChange,
  onAlgorithmChange,
}: AnalyticsPickerProps) {
  const { t } = useTranslation();

  return (
    <div className={styles.cPickerRow}>
      <TooltipSelect
        tooltip={t("analytics.briefing.tournament")}
        value={tournamentId == null ? "" : tournamentId.toString()}
        placeholder={
          loadingTournaments
            ? t("analytics.briefing.loadingTournaments")
            : isErrorTournaments
              ? t("analytics.briefing.errorTournaments")
              : t("analytics.briefing.selectTournament")
        }
        disabled={loadingTournaments || isErrorTournaments}
        className={styles.cPickTournament}
        onValueChange={onTournamentChange}
      >
        <SelectContent className="max-h-[min(var(--radix-select-content-available-height),20rem)]">
          <SelectGroup>
            {tournaments.map((item) => (
              <SelectItem key={item.id} value={item.id.toString()}>
                {item.name}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </TooltipSelect>

      <TooltipSelect
        tooltip={t("analytics.briefing.algorithm")}
        value={algorithmId == null ? "" : algorithmId.toString()}
        placeholder={
          loadingAlgorithms
            ? t("analytics.briefing.loadingAlgorithms")
            : isErrorAlgorithms
              ? t("analytics.briefing.errorAlgorithms")
              : t("analytics.briefing.selectAlgorithm")
        }
        disabled={loadingAlgorithms || isErrorAlgorithms}
        className={styles.cPickAlgorithm}
        onValueChange={onAlgorithmChange}
      >
        <SelectContent>
          <SelectGroup>
            {algorithms.map((item) => (
              <SelectItem key={item.id} value={item.id.toString()}>
                {item.name}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </TooltipSelect>
    </div>
  );
}
