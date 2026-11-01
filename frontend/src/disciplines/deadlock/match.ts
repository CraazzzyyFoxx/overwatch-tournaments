import { lazy } from "react";

import type { DisciplineUI, MatchSlot } from "../types";
// The side and item-slot hues the match view paints with (`--dl-*`).
import "./theme.css";

/** Deadlock's match renderer: the scoreboard with builds (lazy identity created once at module top level). */
const deadlock: DisciplineUI<MatchSlot> = {
  code: "deadlock",
  slots: {
    matchStats: lazy(() => import("./match/MatchStats"))
  }
};

export default deadlock;
