import { ApiError } from "@/lib/api/error";

/**
 * The refusals a flow-node move, a formation export or a flow edit answers with (`errors.flow.<code>` in the message
 * catalogs); the server's English `msg` is data for logs, not for the organizer.
 */
export const FLOW_ERROR_CODES = [
  "invalid_node_transition",
  "input_not_final",
  "downstream_started",
  "node_frozen",
  "flow_invalid",
  "flow_node_not_found",
  "formation_not_forming",
  "formation_has_no_teams",
  "formation_wrong_mode",
  "qualification_not_locked",
  "boundary_tie"
] as const;

export type FlowErrorCode = (typeof FLOW_ERROR_CODES)[number];

/** The first known flow refusal code carried by `error`, or null for anything else. */
export function flowErrorCode(error: unknown): FlowErrorCode | null {
  if (!(error instanceof ApiError)) return null;
  for (const detail of error.details) {
    const code = FLOW_ERROR_CODES.find((known) => known === detail.code);
    if (code) return code;
  }
  return null;
}
