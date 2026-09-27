import { LogStatsName } from "@/types/stats.types";

export const getHumanizedStats = (stats: LogStatsName) => {
  return stats
    .replace(/^[\s_]+|[\s_]+$/g, "")
    .replace(/[_\s]+/g, " ")
    .replace(/^[a-z]/, function (m) {
      return m.toUpperCase();
    });
};
