"use client";

import { useTranslations } from "next-intl";

import type { PresetLabels } from "./presets";

/** The translated node names a preset writes: they are public ("Register for Day 3"), so the viewer's locale picks them. */
export function usePresetLabels(): PresetLabels {
  const tNames = useTranslations("adminTournament.flow.presets.names");
  return {
    playoff: tNames("playoff"),
    groups: tNames("groups"),
    topPerGroup: (n) => tNames("topPerGroup", { n }),
    top: (n) => tNames("top", { n }),
    playoffTeams: tNames("playoffTeams"),
    swiss: tNames("swiss"),
    qualifiers: tNames("qualifiers"),
    day: (i) => tNames("day", { i }),
    dayTeams: (i) => tNames("dayTeams", { i }),
    season: tNames("season"),
    seasonTable: tNames("seasonTable")
  };
}
