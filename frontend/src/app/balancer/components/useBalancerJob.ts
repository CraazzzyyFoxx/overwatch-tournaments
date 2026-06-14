import { useReducer } from "react";

export type JobState = {
  status: string | null;
  message: string | null;
  progress: number | null;
};

export type JobAction =
  | { type: "update"; status: string; message: string | null; progress: number | null }
  | { type: "clear" };

const initialJobState: JobState = { status: null, message: null, progress: null };

function jobReducer(_state: JobState, action: JobAction): JobState {
  if (action.type === "clear") return initialJobState;
  return { status: action.status, message: action.message, progress: action.progress };
}

export function useBalancerJob(): [JobState, React.Dispatch<JobAction>] {
  return useReducer(jobReducer, initialJobState);
}
