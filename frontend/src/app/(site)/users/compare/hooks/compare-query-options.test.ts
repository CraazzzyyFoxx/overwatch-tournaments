import { describe, expect, it, vi } from "vitest";

import { LogStatsName } from "@/types/stats.types";

import {
  buildHeroCompareQueryOptions,
  buildOverallCompareQueryOptions,
  getCompareActivity,
  keepPreviousCompareData,
  shouldLoadHeroCatalogs
} from "./compare-query-options";

describe("compare query options", () => {
  it("forwards TanStack Query's abort signal to the overall request", async () => {
    const fetchCompare = vi.fn().mockResolvedValue({ metrics: [] });
    const options = buildOverallCompareQueryOptions({
      isHeroScope: false,
      subjectUserId: 42,
      baseline: "global",
      fetchCompare
    });
    const controller = new AbortController();

    await options.queryFn({ signal: controller.signal });

    expect(fetchCompare).toHaveBeenCalledWith(
      42,
      expect.objectContaining({ baseline: "global", signal: controller.signal })
    );
  });

  it("forwards the abort signal and stable stat set to a hero request", async () => {
    const fetchCompare = vi.fn().mockResolvedValue({ metrics: [] });
    const options = buildHeroCompareQueryOptions({
      isHeroScope: true,
      subjectUserId: 42,
      baseline: "cohort",
      stats: [LogStatsName.Eliminations, LogStatsName.Deaths],
      fetchCompare
    });
    const controller = new AbortController();

    await options.queryFn({ signal: controller.signal });

    expect(fetchCompare).toHaveBeenCalledWith(
      42,
      expect.objectContaining({
        baseline: "cohort",
        stats: [LogStatsName.Eliminations, LogStatsName.Deaths],
        signal: controller.signal
      })
    );
  });

  it("keeps previous compare data while a new filter combination is fetched", () => {
    const previous = { metrics: [{ key: "maps_total" }] };

    expect(keepPreviousCompareData(previous)).toBe(previous);
  });

  it("loads hero and map catalogs only in Hero / Map scope", () => {
    expect(shouldLoadHeroCatalogs(true)).toBe(true);
    expect(shouldLoadHeroCatalogs(false)).toBe(false);
  });

  it("distinguishes the first load from a background refresh", () => {
    expect(getCompareActivity({ isLoading: true, isFetching: true })).toEqual({
      isInitialLoading: true,
      isRefreshing: false
    });
    expect(getCompareActivity({ isLoading: false, isFetching: true })).toEqual({
      isInitialLoading: false,
      isRefreshing: true
    });
  });
});
