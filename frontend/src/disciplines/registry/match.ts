"use client";

import type { MatchSlot } from "../types";
import { createDisciplineLoader } from "./create";

/** Match, series and per-match row slots (match, encounter and profile web zone). Z7: the only importer of these entrypoints. */
export const loadMatchUI = createDisciplineLoader<MatchSlot>({
  overwatch: () => import("../overwatch/match"),
  deadlock: () => import("../deadlock/match")
});
