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

/**
 * Compact tournament + ranking-model selectors that drive the page. Extracted
 * from the old briefing card so the picker stays a thin control bar above the
 * hero (the hero itself reflects the current selection).
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
    <div className={styles.cPicker}>
      <div className={styles.cPickerField}>
        <span className={styles.cPickerLabel}>{t("analytics.briefing.tournament")}</span>
        <Select
          value={tournamentId == null ? "" : tournamentId.toString()}
          onValueChange={onTournamentChange}
          disabled={loadingTournaments || isErrorTournaments}
        >
          <SelectTrigger aria-label={t("analytics.briefing.tournament")} className="h-11">
            <SelectValue
              placeholder={
                loadingTournaments
                  ? t("analytics.briefing.loadingTournaments")
                  : isErrorTournaments
                    ? t("analytics.briefing.errorTournaments")
                    : t("analytics.briefing.selectTournament")
              }
            />
          </SelectTrigger>
          <SelectContent className="max-h-[min(var(--radix-select-content-available-height),20rem)]">
            <SelectGroup>
              {tournaments.map((item) => (
                <SelectItem key={item.id} value={item.id.toString()}>
                  {item.name}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>

      <div className={styles.cPickerField}>
        <span className={styles.cPickerLabel}>{t("analytics.briefing.algorithm")}</span>
        <Select
          value={algorithmId == null ? "" : algorithmId.toString()}
          onValueChange={onAlgorithmChange}
          disabled={loadingAlgorithms || isErrorAlgorithms}
        >
          <SelectTrigger aria-label={t("analytics.briefing.algorithm")} className="h-11">
            <SelectValue
              placeholder={
                loadingAlgorithms
                  ? t("analytics.briefing.loadingAlgorithms")
                  : isErrorAlgorithms
                    ? t("analytics.briefing.errorAlgorithms")
                    : t("analytics.briefing.selectAlgorithm")
              }
            />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {algorithms.map((item) => (
                <SelectItem key={item.id} value={item.id.toString()}>
                  {item.name}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
