import type { Schema } from "@/types/api";

/** What the collected game career says about registrants (`GET /admin/rank/career-signals`). */
export type CareerSignalsResponse = Schema<"stats.CareerSignalsResponse">;
export type CareerUserSignals = Schema<"stats.CareerUserSignals">;
export type CareerSignal = Schema<"stats.CareerSignal">;
