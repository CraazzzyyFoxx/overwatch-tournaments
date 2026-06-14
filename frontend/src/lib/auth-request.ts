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

  const refreshedToken = await refreshAccessToken();
  if (!refreshedToken) {
    notifyUnauthorized();
    return response;
  }

  const retryResponse = await runRequest(refreshedToken);
  if (retryResponse.status === 401) {
    notifyUnauthorized();
  }

  return retryResponse;
}
