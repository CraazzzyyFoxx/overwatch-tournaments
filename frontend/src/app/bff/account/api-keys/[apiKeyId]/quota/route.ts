import { NextRequest } from "next/server";

import { authServiceRequest } from "../../../_lib";

type RouteContext = {
  params: Promise<{ apiKeyId: string }>;
};

export async function GET(_request: NextRequest, context: RouteContext) {
  const { apiKeyId } = await context.params;
  return authServiceRequest(`/api-keys/${encodeURIComponent(apiKeyId)}/quota`, {
    errorDetail: "Failed to load quota usage"
  });
}

export async function PUT(request: NextRequest, context: RouteContext) {
  const { apiKeyId } = await context.params;
  // Forwarded verbatim: the quota gate answers 422 `quota_above_inherited`
  // with the offending dimension in the body, and the screen marks that field
  // — rewriting the payload here would also have to rewrite that answer.
  return authServiceRequest(`/api-keys/${encodeURIComponent(apiKeyId)}/quota`, {
    method: "PUT",
    body: () => request.json(),
    errorDetail: "Failed to save quota"
  });
}
