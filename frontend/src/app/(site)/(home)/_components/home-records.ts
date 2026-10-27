import type { StatRecordCode } from "@/types/statistics.types";

/**
 * The records the leaders block features beside its podium. The hero's results
 * feed shows the others, so no record appears twice on `/`.
 */
export const LEADER_RECORDS = ["win_streak", "biggest_upset", "eliminations", "longest_map"] as const satisfies readonly StatRecordCode[];
