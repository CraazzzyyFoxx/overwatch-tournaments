"use client";

import { useCallback, useMemo, useReducer } from "react";

/**
 * One of the three master-detail views. The reducer keeps them on a stack so
 * the same state serves desktop (read the top to decide what the sticky aside
 * shows) and mobile (use the stack as push-nav history with a back button).
 */
export type SelectionView =
  | { kind: "overview" }
  | { kind: "team"; teamId: number }
  | { kind: "player"; teamId: number; playerId: number };

interface SelectionState {
  stack: SelectionView[];
}

type SelectionAction =
  | { type: "selectTeam"; teamId: number }
  | { type: "selectPlayer"; teamId: number; playerId: number }
  | { type: "back" }
  | { type: "reset" };

const INITIAL_STATE: SelectionState = { stack: [{ kind: "overview" }] };

function reducer(state: SelectionState, action: SelectionAction): SelectionState {
  switch (action.type) {
    case "selectTeam":
      return { stack: [{ kind: "overview" }, { kind: "team", teamId: action.teamId }] };
    case "selectPlayer":
      return {
        stack: [
          { kind: "overview" },
          { kind: "team", teamId: action.teamId },
          { kind: "player", teamId: action.teamId, playerId: action.playerId },
        ],
      };
    case "back":
      return state.stack.length > 1 ? { stack: state.stack.slice(0, -1) } : state;
    case "reset":
      return INITIAL_STATE;
    default:
      return state;
  }
}

export interface MasterDetailSelection {
  /** Current (deepest) view — what mobile renders and the back button pops. */
  current: SelectionView;
  /** Whether a back step exists (stack depth > 1). */
  canGoBack: boolean;
  /** Team to show on desktop (current selection, defaulting to the first team). */
  selectedTeamId: number | null;
  /** Player to show on desktop, or null when only a team is selected. */
  selectedPlayerId: number | null;
  selectTeam: (teamId: number) => void;
  selectPlayer: (teamId: number, playerId: number) => void;
  back: () => void;
  reset: () => void;
}

/**
 * Drives the standings → team → player drill-down. `defaultTeamId` is the team
 * the desktop aside falls back to when nothing is explicitly selected (mirrors
 * the mock, which opens on the first team).
 */
export function useMasterDetailSelection(defaultTeamId: number | null): MasterDetailSelection {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);

  const selectTeam = useCallback((teamId: number) => dispatch({ type: "selectTeam", teamId }), []);
  const selectPlayer = useCallback(
    (teamId: number, playerId: number) => dispatch({ type: "selectPlayer", teamId, playerId }),
    [],
  );
  const back = useCallback(() => dispatch({ type: "back" }), []);
  const reset = useCallback(() => dispatch({ type: "reset" }), []);

  return useMemo(() => {
    const current = state.stack[state.stack.length - 1];
    const selectedTeamId = current.kind === "overview" ? defaultTeamId : current.teamId;
    const selectedPlayerId = current.kind === "player" ? current.playerId : null;
    return {
      current,
      canGoBack: state.stack.length > 1,
      selectedTeamId,
      selectedPlayerId,
      selectTeam,
      selectPlayer,
      back,
      reset,
    };
  }, [state, defaultTeamId, selectTeam, selectPlayer, back, reset]);
}
