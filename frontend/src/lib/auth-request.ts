import { refreshAccessToken } from "./auth-tokens";
import { notifyUnauthorized } from "./auth-events";

type RunAuthorizedRequest = (token?: string) => Promise<Response>;

type RetryWithRefreshOptions = {
  response: Response;
  token?: string;
  runRequest: RunAuthorizedRequest;
};

export async function retryWithRefreshOnUnauthorized({
  response,
  token,
  runRequest,
}: RetryWithRefreshOptions): Promise<Response> {
  if (response.status !== 401 || token || typeof window === "undefined") {
    return response;
  }

  const outcome = await refreshAccessToken();

  // The refresh token is dead (endpoint returned 401): the session is genuinely
  // over — surface a global logout.
  if (outcome.status === "unauthenticated") {
    notifyUnauthorized();
    return response;
  }

  // Transient refresh failure (network / 5xx). Do NOT log the user out — the
  // session is still valid and a later request (or the proactive scheduler)
  // will recover. Return the original 401 for this single request.
  if (outcome.status === "error") {
    return response;
  }

  // Refreshed successfully — retry once. A 401 on the retry is treated as a
  // per-resource / permission issue, not a dead session, so we do NOT trigger a
  // global logout here (that was the source of the focus-refetch race).
  return runRequest(outcome.token);
}
